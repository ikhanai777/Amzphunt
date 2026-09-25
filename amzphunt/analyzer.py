"""Niche analysis and opportunity scoring.

A product is only a good bet for a *new* seller when the demand is proven,
page 1 of its niche can be cracked without thousands of reviews, the unit
economics survive UAE fees, and it is simple to source, ship and list.
Each of these becomes a 0-100 component score; the weighted total and a set
of hard-stop risks produce the final verdict.
"""

from __future__ import annotations

import datetime as dt
import math
import re
import statistics
from collections import Counter

from .config import AVOID_CATEGORIES, BIG_BRANDS, RISK_KEYWORDS, SEASONAL_KEYWORDS, Settings
from .estimator import SalesEstimator
from .fees import unit_economics
from .models import Listing, NicheStats, Opportunity, ProductDetail

WEIGHTS = {
    "demand": 0.27,
    "competition": 0.27,
    "profit": 0.20,
    "ease": 0.14,
    "opportunity": 0.12,
}

VERDICTS = [(72, "WINNER"), (58, "PROMISING"), (45, "RISKY"), (0, "AVOID")]

HARD_STOP_RISKS = ("prohibited", "hazmat", "MOHAP", "food registration", "IP / licensed")

_STOP = {
    "a", "an", "and", "the", "of", "with", "for", "in", "on", "to", "by", "from", "pack", "pcs",
    "piece", "pieces", "pc", "new", "best", "premium", "upgraded", "upgrade", "original", "professional",
    "high", "quality", "durable", "portable", "multipurpose", "multi", "purpose", "large", "small",
    "medium", "mini", "big", "black", "white", "grey", "gray", "blue", "red", "green", "pink", "clear",
    "silver", "gold", "brown", "beige", "yellow", "purple", "orange", "transparent", "heavy", "duty",
    "extra", "super", "ultra", "perfect", "ideal", "easy", "free", "bpa", "non", "stick", "reusable",
    "adjustable", "compact", "lightweight", "strong", "sturdy", "home", "kitchen", "uae", "dubai", "&",
    "x", "cm", "mm", "ml", "l", "kg", "g", "inch", "inches", "count", "plus", "pro", "max", "edition",
    "version", "model", "style", "type", "design", "brand", "genuine", "authentic", "official",
}


def extract_brand(title: str, detail_brand: str = "") -> str:
    if detail_brand:
        return detail_brand.strip()
    first = re.split(r"[\s,\-|:(]+", title.strip(), maxsplit=1)[0] if title else ""
    return first


def _stem(word: str) -> str:
    """Tiny plural stemmer: bottles->bottle, boxes->box, batteries->battery."""
    w = word.lower()
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith(("ches", "shes", "sses", "xes", "zes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _title_phrase(title: str, brand: str) -> list[str]:
    t = re.split(r"\s[-–|,(:]\s?|[,(|]|\s-\s|\bfor\b|\bwith\b", title or "", maxsplit=1)[0]
    for part in [brand] + (brand.split() if brand else []):
        if part:
            t = re.sub(r"^\s*" + re.escape(part) + r"\b", "", t, flags=re.I)
    words = re.findall(r"[A-Za-z][A-Za-z'\-]+", t)
    return [w.lower() for w in words if w.lower() not in _STOP and not re.search(r"\d", w)]


def _category_phrase(leaf: str, title_words: list[str]) -> str:
    """'Food & Sandwich Bags' -> 'sandwich bags' (segment sharing a title word, else the longest)."""
    segments = [seg.strip().lower() for seg in re.split(r"[,&/]| and ", leaf) if seg.strip()]
    if not segments:
        return ""
    stems = {_stem(w) for w in title_words}
    for seg in segments:
        if any(_stem(w) in stems for w in seg.split()):
            return seg
    return max(segments, key=lambda seg: len(seg.split()))


def extract_keyword(
    title: str,
    brand: str = "",
    breadcrumbs: list[str] | None = None,
    bsr: list[tuple[int, str]] | None = None,
) -> str:
    """Turn a product into the 2-4 word search phrase buyers actually type.

    Titles are noisy (brands, sizes, marketing words), while the product's
    leaf categories (narrowest BSR nodes and breadcrumb) name what it *is*.
    If the title contains a category head noun ('bottle' for 'Insulated
    Bottles') we keep that noun plus up to two modifiers before it; otherwise
    we search the category name itself.
    """
    words = _title_phrase(title, brand)
    leaves = [name for _, name in (bsr or [])[1:]] + (breadcrumbs or [])[-1:]
    heads = set()
    for leaf in leaves:
        for seg in re.split(r"[,&/]| and ", leaf):
            seg_words = re.findall(r"[A-Za-z]+", seg)
            if seg_words:
                heads.add(_stem(seg_words[-1]))
    hits = [i for i, w in enumerate(words) if _stem(w) in heads]
    if hits:
        end = hits[0]
        return " ".join(words[max(0, end - 2): end + 1])
    if leaves:
        return _category_phrase(leaves[0], words)
    return " ".join(words[-3:])


def _median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def _relevance(keyword: str, listings: list[Listing]) -> float:
    """Share of page-1 titles that contain the keyword's head noun. Low values
    mean the keyword is ambiguous and the niche stats describe other products."""
    words = keyword.split()
    if not words or not listings:
        return 0.0
    head = _stem(words[-1])
    hits = sum(any(_stem(w) == head for w in re.findall(r"[A-Za-z]+", l.title)) for l in listings)
    return round(hits / len(listings), 3)


def analyze_niche(keyword: str, listings: list[Listing], total_results: int | None) -> NicheStats:
    organic = [l for l in listings if not l.sponsored]
    pool = organic or listings
    reviews = [l.reviews or 0 for l in pool]
    brands = [extract_brand(l.title).lower() for l in pool if l.title]
    brand_counts = Counter(brands)
    top10 = pool[:10]
    rated = [l for l in pool if l.rating]
    demand = [l.bought_past_month for l in listings if l.bought_past_month]
    return NicheStats(
        keyword=keyword,
        total_results=total_results,
        organic_count=len(organic),
        sponsored_count=len(listings) - len(organic),
        median_price=_median([l.price for l in pool]),
        median_reviews=_median(reviews),
        mean_rating=round(statistics.mean(l.rating for l in rated), 2) if rated else None,
        top10_median_reviews=_median([l.reviews or 0 for l in top10]),
        share_over_1000_reviews=round(sum(r >= 1000 for r in reviews) / len(reviews), 3) if reviews else 0.0,
        share_under_100_reviews=round(sum(r < 100 for r in reviews) / len(reviews), 3) if reviews else 0.0,
        distinct_brands=len(brand_counts),
        top_brand_share=round(brand_counts.most_common(1)[0][1] / len(brands), 3) if brands else 0.0,
        amazon_listing_share=round(sum(b.startswith("amazon") for b in brands) / len(brands), 3) if brands else 0.0,
        demand_bought_month=sum(demand),
        listings_with_demand=len(demand),
        low_rated_share=round(sum(l.rating < 4.0 for l in rated) / len(rated), 3) if rated else 0.0,
        relevance=_relevance(keyword, pool),
        listings=listings,
    )


# -- scoring helpers ------------------------------------------------------------


def _scale(value: float | None, bad: float, good: float) -> float:
    """Linear 0-100 between ``bad`` and ``good`` (either direction)."""
    if value is None:
        return 50.0
    if good == bad:
        return 100.0
    x = (value - bad) / (good - bad)
    return max(0.0, min(100.0, x * 100))


def _log_scale(value: float | None, bad: float, good: float) -> float:
    if value is None or value <= 0:
        return 0.0 if value is not None else 50.0
    return _scale(math.log10(value), math.log10(bad), math.log10(good))


def risk_flags(text: str, category: str, detail: ProductDetail | None, brand: str) -> list[str]:
    flags = []
    low = f" {text.lower()} "
    for kw, why in RISK_KEYWORDS.items():
        if re.search(r"\b" + re.escape(kw) + r"\b", low):
            flags.append(f"{why} ('{kw}')")
    if category in AVOID_CATEGORIES:
        flags.append(f"category: {AVOID_CATEGORIES[category]}")
    if brand and brand.lower() in BIG_BRANDS:
        flags.append(f"big brand ({brand})")
    if detail and detail.sold_by_amazon:
        flags.append("Amazon.ae holds the buy box (sells it directly)")
    return sorted(set(flags))


def seasonal_hint(text: str, today: dt.date | None = None) -> str | None:
    today = today or dt.date.today()
    low = text.lower()
    upcoming = [(today.month + i - 1) % 12 + 1 for i in range(0, 4)]
    for offset, month in enumerate(upcoming):
        for kw in SEASONAL_KEYWORDS.get(month, []):
            if re.search(r"\b" + re.escape(kw) + r"\b", low):
                when = "now" if offset == 0 else f"in {offset} month(s)"
                return f"seasonal demand peak {when} ({kw}, {dt.date(2000, month, 1):%B}) - time the launch 6-8 weeks ahead"
    return None


def _age_months(date_text: str) -> float | None:
    if not date_text:
        return None
    for fmt in ("%d %B %Y", "%d %b. %Y", "%d %b %Y", "%B %d, %Y", "%d %B, %Y", "%d/%m/%Y"):
        try:
            d = dt.datetime.strptime(date_text.strip(), fmt).date()
            return max(0.5, (dt.date.today() - d).days / 30.4)
        except ValueError:
            continue
    return None


# -- main scoring ---------------------------------------------------------------


def score_opportunity(
    listing: Listing,
    detail: ProductDetail | None,
    niche: NicheStats | None,
    estimator: SalesEstimator,
    settings: Settings,
    keyword: str = "",
    sources: list[str] | None = None,
    history_trend: float | None = None,
    unit_cost: float | None = None,
) -> Opportunity:
    st = settings
    title = (detail.title if detail and detail.title else listing.title) or ""
    price = (detail.price if detail and detail.price else listing.price) or (niche.median_price if niche else None)
    reviews = (detail.reviews if detail and detail.reviews else listing.reviews) or 0
    rating = (detail.rating if detail and detail.rating else listing.rating)
    bought = (detail.bought_past_month if detail else None) or listing.bought_past_month
    brand = extract_brand(title, detail.brand if detail else "")
    category = listing.category
    reasons: list[str] = []
    risks: list[str] = []

    est_sales = estimator.estimate(detail.bsr if detail else None, bought, listing.list_rank)

    # ---- demand ----
    demand = _log_scale(est_sales, st.min_monthly_sales / 2, st.ideal_monthly_sales * 2)
    if niche and niche.demand_bought_month:
        niche_demand = _log_scale(niche.demand_bought_month, 300, 6000)
        demand = 0.65 * demand + 0.35 * niche_demand
    if est_sales:
        if est_sales >= st.ideal_monthly_sales:
            reasons.append(f"strong demand: ~{est_sales} units/month")
        elif est_sales < st.min_monthly_sales:
            risks.append(f"low demand: ~{est_sales} units/month")

    # ---- competition ----
    if niche:
        comp_parts = [
            (_scale(niche.median_reviews, st.max_median_reviews * 2, st.ideal_median_reviews / 2), 0.30),
            (_scale(niche.top10_median_reviews, st.max_median_reviews * 3, st.ideal_median_reviews), 0.20),
            (_scale(niche.share_over_1000_reviews, 0.5, 0.0), 0.15),
            (_scale(niche.share_under_100_reviews, 0.0, 0.5), 0.10),
            (_scale(niche.top_brand_share, 0.5, 0.1), 0.10),
            (_scale(niche.sponsored_count / max(1, niche.organic_count + niche.sponsored_count), 0.35, 0.05), 0.08),
            (_log_scale(niche.total_results, 100000, 1000) if niche.total_results else 50.0, 0.07),
        ]
        competition = sum(v * w for v, w in comp_parts) / sum(w for _, w in comp_parts)
        if niche.relevance < 0.4 or niche.organic_count < 8:
            # Page 1 is mostly other products: trust these stats less.
            competition = 0.5 * competition + 0.5 * 45.0
            risks.append(f"niche keyword '{keyword}' is ambiguous ({niche.relevance:.0%} relevant) - validate manually")
        if niche.median_reviews is not None and niche.median_reviews <= st.ideal_median_reviews:
            reasons.append(f"beatable page 1: median {int(niche.median_reviews)} reviews")
        if niche.median_reviews is not None and niche.median_reviews > st.max_median_reviews:
            risks.append(f"entrenched competitors: median {int(niche.median_reviews)} reviews on page 1")
        if niche.top_brand_share >= 0.35:
            risks.append(f"one brand holds {int(niche.top_brand_share * 100)}% of page 1")
    else:
        competition = _scale(reviews, st.max_single_listing_reviews, st.ideal_median_reviews)
    if reviews > st.max_single_listing_reviews:
        competition *= 0.8

    # ---- profitability ----
    economics = None
    if price:
        economics = unit_economics(
            price, category, detail.dimensions_cm if detail else None, detail.weight_kg if detail else None, st, unit_cost
        )
        profit_score = 0.5 * _scale(economics.margin, 0.0, 0.35) + 0.5 * _scale(economics.roi, 0.0, 1.5)
        if st.ideal_price_low <= price <= st.ideal_price_high:
            price_score = 100.0
        elif st.min_price <= price <= st.max_price:
            price_score = 65.0
        else:
            price_score = 15.0
            risks.append(f"price AED {price:.0f} outside the AED {st.min_price:.0f}-{st.max_price:.0f} sweet spot")
        profit = 0.7 * profit_score + 0.3 * price_score
        if economics.profit <= 0:
            risks.append(f"loses AED {-economics.profit:.2f}/unit after fees, freight and ads")
        elif economics.margin >= st.min_margin and economics.roi >= st.min_roi:
            reasons.append(f"healthy economics: AED {economics.profit:.0f} profit/unit, {economics.margin:.0%} margin, {economics.roi:.0%} ROI")
    else:
        profit = 40.0
        risks.append("price unknown")

    # ---- ease of entry ----
    flags = risk_flags(f"{title} {' '.join(detail.breadcrumbs) if detail else ''}", category, detail, brand)
    risks.extend(flags)
    ease = 100.0
    weight = detail.weight_kg if detail else None
    if weight is not None:
        ease -= 0 if weight <= st.ideal_weight_kg else 20 if weight <= st.max_weight_kg else 45
        if weight <= st.ideal_weight_kg:
            reasons.append(f"light ({weight:.2f} kg) - cheap to ship and store")
        elif weight > st.max_weight_kg:
            risks.append(f"heavy ({weight:.1f} kg) - freight and FBA fees bite")
    if economics and economics.size_tier == "oversize":
        ease -= 25
    ease -= 18 * len([f for f in flags if not f.startswith("Amazon.ae")])
    if detail and detail.sold_by_amazon:
        ease -= 25
    if detail and detail.variation_count >= 8:
        ease -= 10
        risks.append(f"{detail.variation_count} variations - more capital to launch")
    ease = max(0.0, ease)

    # ---- opportunity / differentiation ----
    opp = 50.0
    if niche and niche.low_rated_share >= 0.2:
        opp += 15
        reasons.append(f"{int(niche.low_rated_share * 100)}% of page 1 is under 4 stars - room for a better product")
    if rating is not None and rating < 4.1:
        opp += 10
        reasons.append(f"this listing rates {rating} - customers want a better version")
    if detail:
        weak = []
        if detail.image_count and detail.image_count < 6:
            weak.append(f"{detail.image_count} images")
        if not detail.has_aplus:
            weak.append("no A+ content")
        if not detail.has_video:
            weak.append("no video")
        if weak:
            opp += 5 * len(weak)
            reasons.append("weak listing to outshine: " + ", ".join(weak))
    if est_sales and est_sales >= st.min_monthly_sales and est_sales / max(reviews, 1) >= 0.5:
        # Sells a lot relative to its social proof: buyers are not review-driven.
        opp += 12
        reasons.append(f"sells ~{est_sales}/mo with only {reviews} reviews - reviews are not a moat here")
    age = _age_months(detail.date_first_available) if detail else None
    if age is not None and age <= 12 and est_sales and est_sales >= st.min_monthly_sales:
        opp += 10
        reasons.append(f"listed {age:.0f} months ago and already selling - niche is open to newcomers")
    srcs = set(sources or [listing.source])
    if "movers-and-shakers" in srcs:
        opp += 12
        reasons.append("trending: on Movers & Shakers")
    if "new-releases" in srcs:
        opp += 8
        reasons.append("hot new release in its category")
    if history_trend is not None:
        if history_trend > 0.15:
            opp += 10
            reasons.append(f"BSR improved {history_trend:.0%} since last scan")
        elif history_trend < -0.3:
            opp -= 10
            risks.append(f"BSR worsened {-history_trend:.0%} since last scan")
    season = seasonal_hint(f"{title} {keyword}")
    if season:
        opp += 6
        reasons.append(season)
    opp = max(0.0, min(100.0, opp))

    components = {
        "demand": round(demand, 1),
        "competition": round(competition, 1),
        "profit": round(profit, 1),
        "ease": round(ease, 1),
        "opportunity": round(opp, 1),
    }
    total = sum(components[k] * w for k, w in WEIGHTS.items())

    # Hard stops cap the score: a great-looking product you cannot sell is not a winner.
    if any(any(h in f for h in HARD_STOP_RISKS) for f in flags):
        total = min(total, 44.0)
    if economics and economics.profit <= 0:
        total = min(total, 40.0)
    if est_sales is not None and est_sales < st.min_monthly_sales / 2:
        total = min(total, 50.0)
    if category in AVOID_CATEGORIES:
        total = min(total, 50.0)

    verdict = next(v for threshold, v in VERDICTS if total >= threshold)
    return Opportunity(
        asin=listing.asin,
        title=title,
        url=listing.url,
        category=category,
        price=price,
        score=round(total, 1),
        verdict=verdict,
        est_monthly_sales=est_sales,
        est_monthly_revenue=(est_sales * price) if est_sales and price else None,
        keyword=keyword,
        component_scores=components,
        reasons=reasons,
        risks=sorted(set(risks)),
        listing=listing,
        detail=detail,
        niche=niche,
        economics=economics,
        sources=sorted(srcs),
    )


def prefilter_score(listing: Listing, settings: Settings) -> float:
    """Cheap score from list-page data only, used to pick which products get
    the expensive deep dive (product page + niche search).

    Proven demand comes first: a best-seller rank inside a narrow
    sub-category is the strongest free signal. New releases and movers earn
    a bonus for momentum but need at least some traction (reviews) to rank.
    """
    st = settings
    s = 50.0
    if listing.price is not None:
        if st.ideal_price_low <= listing.price <= st.ideal_price_high:
            s += 20
        elif st.min_price <= listing.price <= st.max_price:
            s += 8
        else:
            s -= 30
    reviews = listing.reviews or 0
    if reviews < 5:
        s -= 8  # unproven
    elif reviews <= 300:
        s += 15
    elif reviews <= 1500:
        s += 5
    else:
        s -= 15
    if listing.list_rank:
        weight = 1.0 if listing.source == "bestsellers" else 0.5
        # Deeper nodes (narrow sub-categories) are where a newcomer can rank.
        node_bonus = 1.0 + 0.25 * listing.node.count("/")
        s += weight * node_bonus * max(0.0, 20 - listing.list_rank * 0.35)
    if listing.bought_past_month:
        s += min(15, math.log10(listing.bought_past_month) * 5)
    if listing.source == "movers-and-shakers":
        s += 10
    if listing.source == "new-releases" and reviews >= 5:
        s += 6
    brand = extract_brand(listing.title).lower()
    if brand in BIG_BRANDS:
        s -= 25
    low = listing.title.lower()
    if any(re.search(r"\b" + re.escape(k) + r"\b", low) for k, why in RISK_KEYWORDS.items() if any(h in why for h in HARD_STOP_RISKS)):
        s -= 30
    return s
