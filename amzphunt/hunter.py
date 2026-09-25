"""The hunting pipeline.

1. Discover  - crawl Best Sellers, New Releases and Movers & Shakers for the
               chosen categories and their sub-categories.
2. Pre-filter - cheap scoring on list data; drop big brands, hazmat, gated,
               wrong price band; keep the best N for a deep dive.
3. Enrich    - scrape each product page (BSR, "bought in past month",
               seller, weight, dimensions, listing quality).
4. Calibrate - refit the BSR->sales curve from live pairs.
5. Niche     - derive the buyer keyword and analyse page 1 of search.
6. Score     - demand, competition, profit, ease, opportunity -> verdict.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable

from .analyzer import analyze_niche, extract_brand, extract_keyword, prefilter_score, score_opportunity
from .config import NEW_SELLER_CATEGORIES, Settings
from .estimator import SalesEstimator
from .fetcher import FetchError, Fetcher
from .history import History
from .models import Listing, NicheStats, Opportunity, ProductDetail
from .parsers import parse_list_page, parse_product_page, parse_search_page, parse_subcategories

log = logging.getLogger(__name__)

LIST_SOURCES = ("bestsellers", "new-releases", "movers-and-shakers")


class Hunter:
    def __init__(
        self,
        fetcher: Fetcher,
        settings: Settings | None = None,
        history: History | None = None,
        workers: int = 3,
        progress: Callable[[str], None] | None = None,
    ):
        self.fetcher = fetcher
        self.settings = settings or Settings()
        self.history = history
        self.workers = max(1, workers)
        self.estimator = SalesEstimator()
        self.progress = progress or (lambda msg: log.info(msg))
        self._niche_cache: dict[str, NicheStats] = {}

    # -- 1. discovery ---------------------------------------------------------

    def _list_url(self, source: str, node_path: str, page: int) -> str:
        url = f"/gp/{source}/{node_path}"
        return url if page == 1 else f"{url}?ie=UTF8&pg={page}"

    def _fetch_list(self, source: str, node_path: str, page: int) -> tuple[list[Listing], str]:
        try:
            html = self.fetcher.get(self._list_url(source, node_path, page))
        except FetchError as exc:
            log.warning("%s", exc)
            return [], ""
        category = node_path.split("/")[0]
        return parse_list_page(html, source, category, node_path), html

    def discover(
        self,
        categories: Iterable[str] | None = None,
        depth: int = 1,
        pages: int = 2,
        sources: Iterable[str] = LIST_SOURCES,
        max_subcategories: int = 25,
    ) -> dict[str, tuple[Listing, list[str]]]:
        """Return {asin: (best listing, [sources seen])}."""
        categories = list(categories or NEW_SELLER_CATEGORIES)
        sources = list(sources)
        found: dict[str, tuple[Listing, list[str]]] = {}

        def add(items: list[Listing]) -> None:
            for it in items:
                if it.asin in found:
                    prev, srcs = found[it.asin]
                    if it.source not in srcs:
                        srcs.append(it.source)
                    # Keep the deepest (most specific) node's listing.
                    if it.node.count("/") > prev.node.count("/"):
                        it.bought_past_month = it.bought_past_month or prev.bought_past_month
                        found[it.asin] = (it, srcs)
                else:
                    found[it.asin] = (it, [it.source])

        frontier = [(c, 0) for c in categories]
        visited: set[str] = set()
        while frontier:
            node, level = frontier.pop(0)
            if node in visited:
                continue
            visited.add(node)
            self.progress(f"discover: {node} (level {level})")
            html_first = ""
            for source in sources:
                for page in range(1, pages + 1):
                    items, html = self._fetch_list(source, node, page)
                    if source == "bestsellers" and page == 1:
                        html_first = html
                    add(items)
                    if not items:
                        break
            if level < depth and html_first:
                subs = parse_subcategories(html_first, node)[:max_subcategories]
                frontier.extend((path, level + 1) for path, _ in subs)
        self.progress(f"discover: {len(found)} unique products across {len(visited)} category nodes")
        return found

    # -- 3. enrichment --------------------------------------------------------

    def product(self, asin: str) -> ProductDetail | None:
        try:
            html = self.fetcher.get(f"/dp/{asin}")
        except FetchError as exc:
            log.warning("%s", exc)
            return None
        return parse_product_page(html, asin)

    def enrich(self, asins: list[str]) -> dict[str, ProductDetail]:
        details: dict[str, ProductDetail] = {}
        with ThreadPoolExecutor(self.workers) as pool:
            futures = {pool.submit(self.product, a): a for a in asins}
            for i, fut in enumerate(as_completed(futures), 1):
                d = fut.result()
                if d:
                    details[futures[fut]] = d
                    if d.bsr:
                        self.estimator.add_sample(d.bsr[0][1], d.bsr[0][0], d.bought_past_month)
                self.progress(f"enrich: {i}/{len(asins)} product pages")
        return details

    # -- 5. niche -------------------------------------------------------------

    def niche(self, keyword: str) -> NicheStats | None:
        keyword = keyword.strip().lower()
        if not keyword:
            return None
        if keyword in self._niche_cache:
            return self._niche_cache[keyword]
        try:
            html = self.fetcher.get(f"/s?k={keyword.replace(' ', '+')}")
        except FetchError as exc:
            log.warning("%s", exc)
            return None
        listings, total = parse_search_page(html, keyword)
        stats = analyze_niche(keyword, listings, total)
        self._niche_cache[keyword] = stats
        return stats

    def niches(self, keywords: list[str]) -> dict[str, NicheStats]:
        out: dict[str, NicheStats] = {}
        unique = list(dict.fromkeys(k for k in keywords if k))
        with ThreadPoolExecutor(self.workers) as pool:
            futures = {pool.submit(self.niche, k): k for k in unique}
            for i, fut in enumerate(as_completed(futures), 1):
                n = fut.result()
                if n:
                    out[futures[fut]] = n
                self.progress(f"niche: {i}/{len(unique)} keyword searches")
        return out

    # -- full pipeline ----------------------------------------------------------

    def hunt(
        self,
        categories: Iterable[str] | None = None,
        depth: int = 1,
        pages: int = 2,
        sources: Iterable[str] = LIST_SOURCES,
        deep: int = 40,
        max_subcategories: int = 25,
    ) -> list[Opportunity]:
        found = self.discover(categories, depth, pages, sources, max_subcategories)
        if not found:
            return []

        ranked = sorted(found.values(), key=lambda pair: prefilter_score(pair[0], self.settings), reverse=True)
        # Diversity: don't let one sub-category flood the deep-dive slots.
        per_node: dict[str, int] = {}
        shortlist: list[tuple[Listing, list[str]]] = []
        cap = max(3, deep // 6)
        for listing, srcs in ranked:
            if per_node.get(listing.node, 0) >= cap:
                continue
            per_node[listing.node] = per_node.get(listing.node, 0) + 1
            shortlist.append((listing, srcs))
            if len(shortlist) >= deep:
                break
        self.progress(f"prefilter: deep-diving {len(shortlist)} of {len(found)} products")

        details = self.enrich([l.asin for l, _ in shortlist])
        self.estimator.calibrate()
        if self.estimator.calibrated:
            self.progress(f"calibrate: refit sales curves for {', '.join(self.estimator.calibrated)}")

        keywords: dict[str, str] = {}
        for listing, _ in shortlist:
            d = details.get(listing.asin)
            title = (d.title if d and d.title else listing.title)
            brand = extract_brand(title, d.brand if d else "")
            keywords[listing.asin] = extract_keyword(title, brand, d.breadcrumbs if d else None, d.bsr if d else None)
        niches = self.niches(list(keywords.values()))

        opps = []
        for listing, srcs in shortlist:
            d = details.get(listing.asin)
            kw = keywords[listing.asin]
            trend = self.history.trend(listing.asin, d.main_bsr if d else None) if self.history else None
            opps.append(
                score_opportunity(listing, d, niches.get(kw), self.estimator, self.settings, kw, srcs, trend)
            )
        opps.sort(key=lambda o: o.score, reverse=True)
        if self.history:
            self.history.record(opps)
        return opps

    def evaluate_asin(self, asin: str, unit_cost: float | None = None, keyword: str = "") -> Opportunity | None:
        d = self.product(asin)
        if not d:
            return None
        category = _category_slug(d.breadcrumbs, d.bsr)
        listing = Listing(asin=asin, title=d.title, url=f"https://www.amazon.ae/dp/{asin}", price=d.price,
                          rating=d.rating, reviews=d.reviews, source="manual", category=category,
                          bought_past_month=d.bought_past_month)
        kw = keyword or extract_keyword(d.title, extract_brand(d.title, d.brand), d.breadcrumbs, d.bsr)
        niche = self.niche(kw)
        trend = self.history.trend(asin, d.main_bsr) if self.history else None
        opp = score_opportunity(listing, d, niche, self.estimator, self.settings, kw, ["manual"], trend, unit_cost)
        if self.history:
            self.history.record([opp])
        return opp


_BREADCRUMB_TO_SLUG = {
    "kitchen": "kitchen",
    "home": "home",
    "tools & home improvement": "home-improvement",
    "home improvement": "home-improvement",
    "sports": "sports-goods",
    "sporting goods": "sports-goods",
    "sports & outdoors": "sports-goods",
    "office products": "office-products",
    "pet supplies": "pet-products",
    "automotive": "automotive",
    "baby": "baby",
    "baby products": "baby",
    "beauty": "beauty",
    "health": "health",
    "toys": "toys",
    "toys & games": "toys",
    "fashion": "fashion",
    "electronics": "electronics",
    "grocery": "grocery",
    "appliances": "appliances",
    "computers": "computers",
}


def _category_slug(breadcrumbs: list[str], bsr: list[tuple[int, str]]) -> str:
    for name in ([bsr[0][1]] if bsr else []) + breadcrumbs[:1]:
        slug = _BREADCRUMB_TO_SLUG.get(name.strip().lower())
        if slug:
            return slug
    return ""
