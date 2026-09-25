"""Data structures shared across the pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Listing:
    """A product as seen on a list page (best sellers, new releases, search)."""

    asin: str
    title: str = ""
    url: str = ""
    price: float | None = None
    rating: float | None = None
    reviews: int = 0
    image: str = ""
    source: str = ""  # bestsellers / new-releases / movers-and-shakers / search
    category: str = ""  # top-level slug
    node: str = ""  # sub-category node path, e.g. kitchen/12134077031
    node_name: str = ""
    list_rank: int | None = None  # position on the list page
    bought_past_month: int | None = None
    sponsored: bool = False
    badges: list[str] = field(default_factory=list)
    rank_change_pct: float | None = None  # movers & shakers only

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProductDetail:
    """Fields scraped from a product (/dp/) page."""

    asin: str
    title: str = ""
    brand: str = ""
    price: float | None = None
    rating: float | None = None
    reviews: int = 0
    bought_past_month: int | None = None
    bsr: list[tuple[int, str]] = field(default_factory=list)  # [(rank, category name)]
    breadcrumbs: list[str] = field(default_factory=list)
    seller: str = ""
    ships_from: str = ""
    sold_by_amazon: bool = False
    fba: bool = False
    offer_count: int | None = None
    weight_kg: float | None = None
    dimensions_cm: tuple[float, float, float] | None = None
    date_first_available: str = ""
    image_count: int = 0
    bullet_count: int = 0
    has_aplus: bool = False
    has_video: bool = False
    variation_count: int = 0
    country_of_origin: str = ""
    in_stock: bool = True

    @property
    def main_bsr(self) -> int | None:
        return self.bsr[0][0] if self.bsr else None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NicheStats:
    """Competitive landscape for a keyword, computed from page 1 of search."""

    keyword: str
    total_results: int | None = None
    organic_count: int = 0
    sponsored_count: int = 0
    median_price: float | None = None
    median_reviews: float | None = None
    mean_rating: float | None = None
    top10_median_reviews: float | None = None
    share_over_1000_reviews: float = 0.0
    share_under_100_reviews: float = 0.0
    distinct_brands: int = 0
    top_brand_share: float = 0.0
    amazon_listing_share: float = 0.0
    demand_bought_month: int = 0  # sum of "bought in past month" on page 1
    listings_with_demand: int = 0
    low_rated_share: float = 0.0  # share of listings below 4.0 stars
    relevance: float = 0.0  # share of page-1 titles matching the keyword's head noun
    listings: list[Listing] = field(default_factory=list)

    def to_dict(self, with_listings: bool = False) -> dict:
        d = asdict(self)
        if not with_listings:
            d.pop("listings")
        return d


@dataclass
class Economics:
    price: float
    net_price: float  # after VAT
    referral_fee: float
    fba_fee: float
    storage_fee: float
    landed_cost: float  # COGS + freight + duty
    ppc_cost: float
    profit: float
    margin: float
    roi: float
    size_tier: str
    assumptions: dict = field(default_factory=dict)


@dataclass
class Opportunity:
    """A fully scored candidate."""

    asin: str
    title: str
    url: str
    category: str
    price: float | None
    score: float
    verdict: str
    est_monthly_sales: int | None = None
    est_monthly_revenue: float | None = None
    keyword: str = ""
    component_scores: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    listing: Listing | None = None
    detail: ProductDetail | None = None
    niche: NicheStats | None = None
    economics: Economics | None = None
    sources: list[str] = field(default_factory=list)

    def flat(self) -> dict:
        """One-row summary for CSV export."""
        d = self.detail
        n = self.niche
        e = self.economics
        return {
            "rank": None,
            "verdict": self.verdict,
            "score": round(self.score, 1),
            "asin": self.asin,
            "title": self.title[:150],
            "category": self.category,
            "keyword": self.keyword,
            "price_aed": self.price,
            "est_monthly_sales": self.est_monthly_sales,
            "est_monthly_revenue_aed": round(self.est_monthly_revenue) if self.est_monthly_revenue else None,
            "bsr": d.main_bsr if d else None,
            "bought_past_month": (d.bought_past_month if d else None)
            or (self.listing.bought_past_month if self.listing else None),
            "rating": (d.rating if d else None) or (self.listing.rating if self.listing else None),
            "reviews": (d.reviews if d else None) or (self.listing.reviews if self.listing else None),
            "brand": d.brand if d else "",
            "seller": d.seller if d else "",
            "weight_kg": d.weight_kg if d else None,
            "niche_results": n.total_results if n else None,
            "niche_median_reviews": n.median_reviews if n else None,
            "niche_median_price": n.median_price if n else None,
            "niche_demand_bought_month": n.demand_bought_month if n else None,
            "niche_top_brand_share": round(n.top_brand_share, 2) if n else None,
            "profit_per_unit_aed": round(e.profit, 2) if e else None,
            "margin": round(e.margin, 2) if e else None,
            "roi": round(e.roi, 2) if e else None,
            "sources": ",".join(self.sources),
            "reasons": " | ".join(self.reasons),
            "risks": " | ".join(self.risks),
            "url": self.url,
        }
