"""HTML parsers for amazon.ae pages.

Selectors favour stable hooks (ids, data-* attributes, aria labels, visible
text) over Amazon's hashed CSS class names, and every field degrades to a
default instead of raising, so a layout change loses a field, not the run.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .config import BASE_URL
from .models import Listing, ProductDetail

try:  # lxml is ~5x faster, but keep working without it
    import lxml  # noqa: F401

    _PARSER = "lxml"
except ImportError:  # pragma: no cover
    _PARSER = "html.parser"

ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})")
NODE_RE = re.compile(r"/gp/(?:bestsellers|new-releases|movers-and-shakers)/([a-z0-9-]+)(?:/(\d+))?")


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, _PARSER)


def _text(el: Tag | None) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el else ""


def _clean(s: str) -> str:
    return re.sub(r"[‎‏‪-‮]", "", s).strip(" :\n\t")


# -- primitive value parsers --------------------------------------------------


def parse_price(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?", text.replace("\xa0", " "))
    if not m:
        return None
    whole = m.group(1).replace(",", "")
    frac = m.group(2) or "0"
    try:
        return float(f"{whole}.{frac}")
    except ValueError:
        return None


def parse_count(text: str | None) -> int:
    """'(1,234)' -> 1234, '2.1K' -> 2100, '746 ratings' -> 746."""
    if not text:
        return 0
    m = re.search(r"(\d+(?:[.,]\d+)*)\s*([KkMm])?", text.replace("\xa0", " "))
    if not m:
        return 0
    num, suffix = m.group(1), (m.group(2) or "").upper()
    if suffix:
        value = float(num.replace(",", "."))
        return int(value * (1000 if suffix == "K" else 1_000_000))
    return int(num.replace(",", "").replace(".", ""))


def parse_rating(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"(\d(?:[.,]\d)?)\s*out of\s*5", text)
    if not m:
        m = re.match(r"\s*(\d(?:[.,]\d)?)\s*$", text)
    return float(m.group(1).replace(",", ".")) if m else None


def parse_bought(text: str | None) -> int | None:
    """'2K+ bought in past month' -> 2000."""
    if not text:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*([KkMm])?\+?\s*bought in past month", text)
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    if m.group(2):
        value *= 1000 if m.group(2).upper() == "K" else 1_000_000
    return int(value)


def parse_weight_kg(text: str | None) -> float | None:
    if not text:
        return None
    t = text.lower().replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(kilograms|kilogram|kg|grams|gram|g|pounds|pound|lbs|lb|ounces|ounce|oz)\b", t)
    if not m:
        return None
    v, unit = float(m.group(1)), m.group(2)
    if unit.startswith("k"):
        return v
    if unit in ("g", "gram", "grams"):
        return v / 1000
    if unit.startswith(("lb", "pound")):
        return v * 0.4536
    return v * 0.02835  # ounces


def parse_dimensions_cm(text: str | None) -> tuple[float, float, float] | None:
    if not text:
        return None
    t = text.lower().replace(",", ".")
    num = r"(\d+(?:\.\d+)?)\s*[lwhd]?\s*"
    m = re.search(num + r"[x×]\s*" + num + r"[x×]\s*" + num + r"(cm|centimetres|centimeters|mm|millimetres|millimeters|inches|inch|in)?", t)
    if not m:
        return None
    dims = [float(m.group(i)) for i in (1, 2, 3)]
    unit = m.group(4) or "cm"
    factor = 0.1 if unit.startswith("m") else 2.54 if unit.startswith("in") else 1.0
    dims = sorted((d * factor for d in dims), reverse=True)
    return (round(dims[0], 2), round(dims[1], 2), round(dims[2], 2))


def asin_from_url(url: str) -> str | None:
    m = ASIN_RE.search(url or "")
    return m.group(1) if m else None


def canonical_url(asin: str) -> str:
    return f"{BASE_URL}/dp/{asin}"


# -- best sellers / new releases / movers & shakers ---------------------------


def _recs_metadata(s: BeautifulSoup) -> dict[str, dict]:
    meta: dict[str, dict] = {}
    for el in s.select("[data-client-recs-list]"):
        try:
            for rec in json.loads(el["data-client-recs-list"]):
                meta[rec.get("id", "")] = rec.get("metadataMap", {})
        except (ValueError, TypeError):
            continue
    return meta


def parse_list_page(html: str, source: str = "bestsellers", category: str = "", node: str = "") -> list[Listing]:
    """Parse a Best Sellers / New Releases / Movers & Shakers grid page."""
    s = soup(html)
    meta = _recs_metadata(s)
    node_name = _current_node_name(s)
    out: dict[str, Listing] = {}
    for card in s.select("[data-asin]"):
        asin = (card.get("data-asin") or "").strip()
        if not re.fullmatch(r"[A-Z0-9]{10}", asin) or asin in out:
            continue
        link = card.select_one("a[href*='/dp/']")
        title_el = card.select_one("div[class*='line-clamp']") or card.select_one("a[role='link'] span")
        img = card.select_one("img")
        title = _text(title_el) if title_el and not _text(title_el).startswith("#") else ""
        title = title or (img.get("alt", "") if img else "")
        rank_el = card.select_one(".zg-bdg-text")
        rating_link = card.select_one("a[aria-label*='out of 5']")
        rating = reviews = None
        if rating_link:
            label = rating_link.get("aria-label", "")
            rating = parse_rating(label)
            m = re.search(r"([\d,]+)\s+ratings?", label)
            reviews = int(m.group(1).replace(",", "")) if m else None
        if rating is None:
            rating = parse_rating(_text(card.select_one(".a-icon-alt")))
        if reviews is None:
            reviews = parse_count(_text(card.select_one("a[href*='product-reviews'] span.a-size-small")))
        price_el = card.select_one("[class*='p13n-sc-price'], .a-color-price, .a-price .a-offscreen")
        m = meta.get(asin, {})
        change = None
        pct = m.get("render.zg.bsms.percentageChange") or ""
        if pct:
            change = parse_price(pct)
        pct_el = card.select_one(".zg-percent-change, [class*='percent-change']")
        if change is None and pct_el:
            change = parse_price(_text(pct_el))
        rank = None
        if rank_el:
            rank = int(re.sub(r"\D", "", _text(rank_el)) or 0) or None
        elif m.get("render.zg.rank"):
            rank = int(m["render.zg.rank"])
        out[asin] = Listing(
            asin=asin,
            title=title,
            url=canonical_url(asin) if not link else urljoin(BASE_URL, link["href"].split("/ref=")[0]),
            price=parse_price(_text(price_el)),
            rating=rating,
            reviews=reviews or 0,
            image=img.get("src", "") if img else "",
            source=source,
            category=category,
            node=node,
            node_name=node_name,
            list_rank=rank,
            rank_change_pct=change,
        )
    return list(out.values())


def list_page_asins(html: str) -> list[str]:
    """All ASINs on a list page, including lazily rendered ones."""
    return [a for a in _recs_metadata(soup(html)) if a]


def _current_node_name(s: BeautifulSoup) -> str:
    title = _text(s.select_one("title"))
    m = re.search(r"(?:best items|biggest gainers|newest items|best sellers|releases) in (.+?)(?: based on| sales rank|$)", title, re.I)
    if m:
        return m.group(1).strip()
    h1 = _text(s.select_one("h1"))
    return re.sub(r"^(Best Sellers|New Releases|Movers & Shakers) in ", "", h1)


def parse_subcategories(html: str, current_path: str) -> list[tuple[str, str]]:
    """Return [(node_path, name)] children of ``current_path`` from the nav tree.

    ``current_path`` looks like 'kitchen' or 'kitchen/12134077031'. The tree
    renders ancestors, then the selected node (``aria-current``), then its
    children, so children are the node links that follow the selected node.
    """
    s = soup(html)
    selected = s.select_one("[aria-current='page']")
    links = selected.find_all_next("a", href=True) if selected else s.find_all("a", href=True)
    children: dict[str, str] = {}
    for a in links:
        m = NODE_RE.search(a["href"])
        if not m or not m.group(2):
            continue
        path = f"{m.group(1)}/{m.group(2)}"
        name = _text(a)
        if path == current_path or not name or re.fullmatch(r"\d+|.*page.*", name, re.I):
            continue
        if m.group(1) != current_path.split("/")[0]:
            continue
        children.setdefault(path, name)
    return list(children.items())


# -- search results -----------------------------------------------------------


def parse_search_page(html: str, keyword: str = "") -> tuple[list[Listing], int | None]:
    s = soup(html)
    listings: dict[str, Listing] = {}
    for pos, r in enumerate(s.select("div[data-component-type='s-search-result']"), start=1):
        asin = r.get("data-asin", "")
        if not asin or asin in listings:
            continue
        classes = " ".join(r.get("class", []))
        sponsored = "AdHolder" in classes or any(
            t.strip() == "Sponsored" for t in r.find_all(string=re.compile(r"^\s*Sponsored\s*$"))
        )
        h2 = r.select_one("h2")
        title = (h2.get("aria-label") if h2 else "") or _text(h2)
        title = re.sub(r"^Sponsored Ad\s*[-–]\s*", "", title)
        rating = parse_rating(_text(r.select_one("span.a-icon-alt")))
        rev_el = r.select_one("a[aria-label$='ratings'], a[aria-label$='rating'], span[aria-label$='ratings']")
        reviews = parse_count(rev_el.get("aria-label")) if rev_el else 0
        if not reviews:
            reviews = parse_count(_text(r.select_one("span.s-underline-text")))
        bought = None
        for el in r.select("span.a-size-base.a-color-secondary, span.a-color-secondary"):
            bought = parse_bought(_text(el))
            if bought:
                break
        badges = [_text(b) for b in r.select(".a-badge-text, [id$='-best-seller-label']") if _text(b)]
        img = r.select_one("img.s-image")
        listings[asin] = Listing(
            asin=asin,
            title=title,
            url=canonical_url(asin),
            price=parse_price(_text(r.select_one("span.a-price:not(.a-text-price) span.a-offscreen"))),
            rating=rating,
            reviews=reviews,
            image=img.get("src", "") if img else "",
            source="search",
            list_rank=pos,
            bought_past_month=bought,
            sponsored=sponsored,
            badges=badges,
        )
    total = None
    info = _text(s.select_one("[data-component-type='s-result-info-bar']"))
    m = re.search(r"of (?:over )?([\d,]+) results", info) or re.search(r"([\d,]+) results", info)
    if m:
        total = int(m.group(1).replace(",", ""))
    elif listings:
        total = len(listings)
    return list(listings.values()), total


# -- product detail page ------------------------------------------------------


def _detail_table(s: BeautifulSoup) -> dict[str, str]:
    """Merge every 'label: value' style product-detail section into one dict."""
    rows: dict[str, str] = {}
    for tr in s.select("#prodDetails tr, #productDetails_techSpec_section_1 tr, #productDetails_detailBullets_sections1 tr, table.a-keyvalue tr, #productOverview_feature_div tr"):
        th, td = tr.select_one("th, td.a-span3"), tr.select_one("td:not(.a-span3)")
        if th and td:
            rows.setdefault(_clean(_text(th)).lower(), _clean(_text(td)))
    for li in s.select("#detailBullets_feature_div li, #detailBulletsWrapper_feature_div li"):
        bold = li.select_one("span.a-text-bold")
        if bold:
            label = _clean(_text(bold)).lower()
            value = _clean(_text(li)[len(_text(bold)):])
            rows.setdefault(label, value)
    return rows


def _lookup(rows: dict[str, str], *needles: str) -> str:
    for needle in needles:
        for k, v in rows.items():
            if needle in k:
                return v
    return ""


def parse_bsr(s: BeautifulSoup) -> list[tuple[int, str]]:
    texts: list[str] = []
    for node in s.find_all(string=re.compile("Best Sellers Rank")):
        row = node.find_parent(["tr", "li"]) or node.parent
        texts.append(_text(row))
    if not texts:
        full = _text(s.body) if s.body else ""
        m = re.search(r"Best Sellers Rank(.{0,400})", full)
        if m:
            texts.append(m.group(0))
    ranks: list[tuple[int, str]] = []
    for t in texts:
        t = re.sub(r"\(\s*See Top 100[^)]*\)", " ", t)
        for m in re.finditer(r"#?\s*([\d,]+)\s+in\s+([^#(]+?)(?=\s*(?:#|\(|$|ASIN|Customer Reviews|Date First))", t):
            name = m.group(2).strip(" .,")
            rank = int(m.group(1).replace(",", ""))
            if (rank, name) not in ranks:
                ranks.append((rank, name))
        if ranks:
            break
    return ranks


def _product_rating(s: BeautifulSoup) -> float | None:
    el = s.select_one("#acrPopover")
    if el is None:
        return None
    return parse_rating(el.get("title", "")) or parse_rating(_text(el.select_one(".a-icon-alt"))) or parse_rating(_text(el).split(" ")[0])


def parse_product_page(html: str, asin: str = "") -> ProductDetail:
    s = soup(html)
    rows = _detail_table(s)
    page_text = _text(s.select_one("#dp-container") or s.body) if s.body else ""
    asin = asin or _lookup(rows, "asin") or ""

    brand = _lookup(rows, "brand name", "brand") or ""
    byline = _text(s.select_one("#bylineInfo"))
    if not brand and byline:
        brand = re.sub(r"^(Visit the|Brand:)\s*", "", byline)
        brand = re.sub(r"\s*Store$", "", brand).strip()

    price_el = s.select_one(
        "#corePrice_feature_div .a-offscreen, #corePriceDisplay_desktop_feature_div .a-offscreen, "
        "#apex_desktop .a-offscreen, #price_inside_buybox, #priceblock_ourprice, #priceblock_dealprice, .a-price .a-offscreen"
    )
    buybox = _text(s.select_one("#buybox, #desktop_buybox, #rightCol"))

    seller = _text(s.select_one("#sellerProfileTriggerId, #merchantInfoFeatureId .offer-display-feature-text-message"))
    ships = ""
    for el in s.select("[offer-display-feature-name='desktop-merchant-info'] .offer-display-feature-text-message"):
        seller = seller or _text(el)
    for el in s.select("[offer-display-feature-name='desktop-fulfiller-info'] .offer-display-feature-text-message"):
        ships = ships or _text(el)
    if not seller:
        m = re.search(r"Sold by:?\s*(.+?)(?:\s{2,}|FREE|Returns|Payment|Dispatched|Ships|$)", buybox)
        seller = m.group(1).strip() if m else ""
    if not ships:
        m = re.search(r"(?:Dispatched|Ships) from:?\s*(.+?)(?:\s{2,}|Sold by|FREE|$)", buybox)
        ships = m.group(1).strip() if m else ""
    if "Ships from and sold by Amazon" in page_text or "Shipper / Seller Amazon.ae" in buybox:
        seller = seller or "Amazon.ae"
        ships = ships or "Amazon.ae"

    offer_count = None
    m = re.search(r"New \((\d+)\) from", page_text) or re.search(r"(\d+)\s+(?:new|New) from", page_text)
    if m:
        offer_count = int(m.group(1))
    m = re.search(r"Other Sellers on Amazon.{0,40}?\((\d+)\)", page_text)
    if m:
        offer_count = int(m.group(1)) + 1

    dims, dims_text = None, ""
    for label in ("package dimensions", "product dimensions", "item dimensions l x w x h", "item dimensions", "dimensions"):
        candidate = _lookup(rows, label)
        dims = parse_dimensions_cm(candidate)
        if dims:
            dims_text = candidate
            break
    weight = parse_weight_kg(_lookup(rows, "item weight", "weight"))
    if weight is None and ";" in dims_text:
        weight = parse_weight_kg(dims_text.split(";")[-1])

    image_count = len(set(re.findall(r'"hiRes":"(https[^"]+)"', html))) or len(s.select("#altImages li.imageThumbnail"))
    m = re.search(r'"dimensionValuesDisplayData"\s*:\s*(\{.*?\})\s*,\s*"', html)
    if m:
        variation_count = m.group(1).count('":[')
    else:
        variation_count = len(s.select("#twister li[data-defaultasin], #twister li[data-asin]"))

    return ProductDetail(
        asin=asin,
        title=_text(s.select_one("#productTitle")),
        brand=brand,
        price=parse_price(_text(price_el)),
        rating=_product_rating(s),
        reviews=parse_count(_text(s.select_one("#acrCustomerReviewText"))),
        # Only the product's own badge; carousels on the page carry other ASINs' badges.
        bought_past_month=parse_bought(_text(s.select_one(
            "#social-proofing-faceout-title-tk_bought, #socialProofingAsinFaceout_feature_div"
        ))),
        bsr=parse_bsr(s),
        breadcrumbs=[_text(a) for a in s.select("#wayfinding-breadcrumbs_feature_div li a")],
        seller=seller,
        ships_from=ships,
        sold_by_amazon=seller.lower().startswith("amazon"),
        fba=ships.lower().startswith("amazon") or "Fulfilled by Amazon" in page_text,
        offer_count=offer_count,
        weight_kg=round(weight, 3) if weight is not None else None,
        dimensions_cm=dims,
        date_first_available=_lookup(rows, "date first available", "release date"),
        image_count=image_count,
        bullet_count=len([li for li in s.select("#feature-bullets li") if _text(li)]),
        has_aplus=bool(s.select_one("#aplus .aplus-v2, #aplus_feature_div .aplus-module, #aplusBrandStory_feature_div .aplus-module")),
        has_video=bool(re.search(r'"videoCount"\s*:\s*[1-9]', html)) or bool(s.select_one("#altImages .videoThumbnail")),
        variation_count=variation_count,
        country_of_origin=_lookup(rows, "country of origin"),
        in_stock="currently unavailable" not in _text(s.select_one("#availability")).lower(),
    )
