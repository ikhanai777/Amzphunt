from pathlib import Path

import pytest

from amzphunt import parsers as P
from amzphunt.analyzer import analyze_niche, extract_keyword, score_opportunity
from amzphunt.config import FetchSettings, Settings
from amzphunt.estimator import SalesEstimator
from amzphunt.fees import fba_fee, max_unit_cost, size_tier, unit_economics
from amzphunt.fetcher import FetchError, Fetcher, is_blocked
from amzphunt.history import History
from amzphunt.hunter import Hunter
from amzphunt.models import Listing, ProductDetail
from amzphunt.report import console_table, write_all

FIX = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


# -- value parsers ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [("AED 59.00", 59.0), ("AED\xa01,299.50", 1299.5), ("AED8.6", 8.6), ("", None), ("n/a", None)],
)
def test_parse_price(text, expected):
    assert P.parse_price(text) == expected


@pytest.mark.parametrize("text,expected", [("(1,234)", 1234), ("746", 746), ("2.1K", 2100), ("", 0)])
def test_parse_count(text, expected):
    assert P.parse_count(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [("2K+ bought in past month", 2000), ("100+ bought in past month", 100), ("1.5K+ bought in past month", 1500), ("nothing", None)],
)
def test_parse_bought(text, expected):
    assert P.parse_bought(text) == expected


def test_parse_weight_and_dims():
    assert P.parse_weight_kg("368 Grams") == pytest.approx(0.368)
    assert P.parse_weight_kg("1.2 Kilograms") == pytest.approx(1.2)
    assert P.parse_weight_kg("2 pounds") == pytest.approx(0.907, rel=1e-2)
    assert P.parse_dimensions_cm("19L x 6W x 7.5H centimeters") == (19.0, 7.5, 6.0)
    assert P.parse_dimensions_cm("18.3 x 18.3 x 23.5 cm; 368 g") == (23.5, 18.3, 18.3)
    assert P.parse_dimensions_cm("10 x 5 x 2 inches") == (25.4, 12.7, 5.08)
    assert P.parse_dimensions_cm("18.3W x 23.5H centimeters") is None


def test_is_blocked():
    assert is_blocked("<html>Enter the characters you see below</html>")
    assert not is_blocked("<html>normal page</html>")


# -- page parsers ------------------------------------------------------------------


def test_parse_list_page():
    items = P.parse_list_page(fixture("bestsellers.html"), "bestsellers", "kitchen", "kitchen/12134077031")
    assert [i.asin for i in items] == ["B0TESTAAA1", "B0TESTAAA2"]
    a, b = items
    assert a.title.startswith("Kitcho Silicone Spatula")
    assert a.price == 59.0 and a.rating == 4.2 and a.reviews == 1234 and a.list_rank == 1
    assert a.url == "https://www.amazon.ae/Silicone-Spatula/dp/B0TESTAAA1"
    assert a.node_name == "Tools & Gadgets"
    assert b.price == 1299.5 and b.rank_change_pct == 250.0


def test_parse_subcategories_only_children():
    subs = P.parse_subcategories(fixture("bestsellers.html"), "kitchen/12134077031")
    assert subs == [("kitchen/12134235031", "Spoons, Spatulas & Turners"), ("kitchen/12134243031", "Whisks")]


def test_parse_search_page():
    listings, total = P.parse_search_page(fixture("search.html"))
    assert total == 4000
    assert [l.asin for l in listings] == ["B0SRCH0001", "B0SRCH0002", "B0SRCH0003"]
    ad, kitcho, homey = listings
    assert ad.sponsored and ad.title == "BigCo Silicone Spatula Pro" and ad.reviews == 5210
    assert not kitcho.sponsored and kitcho.bought_past_month == 200 and kitcho.rating == 3.8
    assert "Best Seller" in kitcho.badges
    assert homey.bought_past_month == 1000 and homey.price == 39.5


def test_parse_product_page():
    d = P.parse_product_page(fixture("product.html"), "B0TESTAAA1")
    assert d.title.startswith("Kitcho Silicone Spatula")
    assert d.brand == "Kitcho"
    assert d.price == 59.0 and d.rating == 4.2 and d.reviews == 1234
    assert d.bought_past_month == 500
    assert d.bsr == [(1245, "Kitchen"), (12, "Spoons, Spatulas & Turners")]
    assert d.main_bsr == 1245
    assert d.breadcrumbs[-1] == "Spoons, Spatulas & Turners"
    assert d.seller == "Kitcho Trading" and not d.sold_by_amazon and d.fba
    assert d.weight_kg == pytest.approx(0.32)
    assert d.dimensions_cm == (30.0, 8.0, 4.0)
    assert d.date_first_available == "12 March 2025"
    assert d.image_count == 3 and d.bullet_count == 3 and d.variation_count == 2
    assert d.country_of_origin == "China"


# -- estimator -------------------------------------------------------------------------


def test_estimator_monotonic_and_calibrates():
    est = SalesEstimator()
    assert est.from_bsr(1, "Kitchen") > est.from_bsr(100, "Kitchen") > est.from_bsr(10000, "Kitchen")
    assert est.from_bsr(None) is None
    # Feed a market twice as strong as the default curve.
    a, b = est.curves["kitchen"]
    for rank in (10, 50, 200, 800, 3000, 9000):
        est.add_sample("Kitchen", rank, int(2 * a * rank ** -b / 1.35))
    est.calibrate()
    assert "kitchen" in est.calibrated
    # Blended with the prior, so it moves toward (not all the way to) 2x.
    assert 1.2 * a * 200 ** -b < est.from_bsr(200, "Kitchen") < 2.0 * a * 200 ** -b


def test_estimator_prefers_published_bought_badge():
    est = SalesEstimator()
    only_badge = est.estimate(None, 1000)
    assert only_badge == 1350
    blended = est.estimate([(50000, "Kitchen")], 1000)
    assert 300 < blended < 1350


# -- fees -----------------------------------------------------------------------------------


def test_size_tiers_and_fees():
    assert size_tier((20, 15, 2), 0.2) == "envelope"
    assert size_tier((30, 20, 10), 1.0) == "standard"
    assert size_tier((120, 40, 30), 8.0) == "oversize"
    small, _ = fba_fee((20, 15, 2), 0.2)
    big, _ = fba_fee((40, 30, 20), 4.0)
    assert small < big


def test_unit_economics_math():
    e = unit_economics(100.0, "kitchen", (25, 15, 5), 0.4, Settings(), unit_cost=20.0)
    assert e.net_price == pytest.approx(95.24, abs=0.01)
    assert e.referral_fee == pytest.approx(12.0)
    assert e.profit < e.net_price
    assert 0 < e.margin < 1
    cap = max_unit_cost(100.0, "kitchen", (25, 15, 5), 0.4, Settings())
    at_cap = unit_economics(100.0, "kitchen", (25, 15, 5), 0.4, Settings(), unit_cost=cap)
    assert at_cap.roi >= Settings().min_roi - 0.01


# -- analysis ---------------------------------------------------------------------------------


def test_extract_keyword_uses_category_head_noun():
    assert extract_keyword(
        "Owala FreeSip Insulated Stainless Steel Water Bottle with Straw", "Owala", ["Drink Flasks"],
        [(998, "Kitchen"), (28, "Insulated Bottles")],
    ) == "steel water bottle"
    assert extract_keyword("Nikai 1.2L, 2200W Cordless Kettle", "Nikai", ["Electric Kettles"]) == "electric kettles"
    assert extract_keyword("Fun Zipper Bags 18x23cm, Clear", "Fun", ["Food & Sandwich Bags"]) == "zipper bags"


def _niche():
    listings, total = P.parse_search_page(fixture("search.html"))
    return analyze_niche("silicone spatula", listings, total)


def test_analyze_niche():
    n = _niche()
    assert n.sponsored_count == 1 and n.organic_count == 2
    assert n.median_reviews == pytest.approx(82.5)
    assert n.demand_bought_month == 1200
    assert n.relevance == 1.0
    assert n.low_rated_share == 0.5


def _detail(**kw):
    base = dict(asin="B0TESTAAA1", title="Kitcho Silicone Spatula Set", brand="Kitcho", price=69.0, rating=4.1,
                reviews=90, bought_past_month=400, bsr=[(900, "Kitchen"), (5, "Spatulas")], seller="Kitcho",
                ships_from="Amazon.ae", fba=True, weight_kg=0.3, dimensions_cm=(30, 8, 4), image_count=4)
    base.update(kw)
    return ProductDetail(**base)


def test_score_good_product_beats_bad_one():
    st = Settings()
    listing = Listing(asin="B0TESTAAA1", title="Kitcho Silicone Spatula Set", price=69.0, category="kitchen",
                      source="bestsellers", list_rank=3)
    good = score_opportunity(listing, _detail(), _niche(), SalesEstimator(), st, "silicone spatula")
    bad_detail = _detail(title="Lithium Battery Pack Spray", price=12.0, bought_past_month=None,
                         bsr=[(90000, "Kitchen")], weight_kg=5.0, sold_by_amazon=True, seller="Amazon.ae")
    bad = score_opportunity(listing, bad_detail, _niche(), SalesEstimator(), st, "battery pack")
    assert good.score > bad.score
    assert good.verdict in ("WINNER", "PROMISING")
    assert bad.verdict == "AVOID"
    assert any("hazmat" in r for r in bad.risks)
    assert good.economics and good.economics.profit > 0


# -- pipeline -------------------------------------------------------------------------------


class FakeFetcher(Fetcher):
    """Serves fixtures by URL pattern instead of hitting amazon.ae."""

    def __init__(self, tmp_path):
        super().__init__(FetchSettings(cache_dir=str(tmp_path / "cache"), min_delay=0, max_delay=0))

    def get(self, url, use_cache=True):
        if "/gp/bestsellers/kitchen" in url and "pg=" not in url:
            return fixture("bestsellers.html")
        if "/dp/" in url:
            return fixture("product.html").replace("B0TESTAAA1", url.rsplit("/", 1)[-1])
        if "/s?k=" in url:
            return fixture("search.html")
        raise FetchError(f"no fixture for {url}")


def test_hunt_pipeline_end_to_end(tmp_path):
    history = History(tmp_path / "h.db")
    hunter = Hunter(FakeFetcher(tmp_path), Settings(), history, workers=2, progress=lambda m: None)
    opps = hunter.hunt(["kitchen"], depth=0, pages=1, sources=["bestsellers"], deep=10)
    assert {o.asin for o in opps} == {"B0TESTAAA1", "B0TESTAAA2"}
    assert opps == sorted(opps, key=lambda o: o.score, reverse=True)
    assert all(o.keyword for o in opps)
    paths = write_all(opps, tmp_path / "out", {"categories": ["kitchen"]})
    assert all(p.exists() and p.stat().st_size > 0 for p in paths.values())
    assert "B0TESTAAA1" in paths["html"].read_text(encoding="utf-8")
    assert "Verdict" in console_table(opps)
    rows = history.conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    assert rows == 2


def test_offline_mode_uses_cache_only(tmp_path):
    f = Fetcher(FetchSettings(cache_dir=str(tmp_path), offline=True))
    with pytest.raises(FetchError):
        f.get("/dp/B000000000")
    f._write_cache("https://www.amazon.ae/dp/B000000000", "<html>cached</html>")
    assert f.get("/dp/B000000000") == "<html>cached</html>"
