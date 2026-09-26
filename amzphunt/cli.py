"""Command line interface.

    amzphunt hunt                       # scan new-seller-friendly categories
    amzphunt hunt -c kitchen home --depth 2 --deep 60
    amzphunt niche "car sun shade" "silicone spatula"
    amzphunt product B07Q6JD5D1 --cost 6
    amzphunt profit --price 79 --weight 0.4 --dims 25x15x5 --category kitchen --cost 12
    amzphunt categories
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import AVOID_CATEGORIES, CATEGORIES, NEW_SELLER_CATEGORIES, FetchSettings, Settings
from .fees import max_unit_cost, unit_economics
from .fetcher import Fetcher
from .history import History
from .hunter import LIST_SOURCES, Hunter
from .parsers import parse_dimensions_cm
from .report import console_table, summarize_latest, write_all


def _progress(quiet: bool):
    def emit(msg: str) -> None:
        if not quiet:
            print(f"  · {msg}", file=sys.stderr, flush=True)

    return emit


def _build(args) -> Hunter:
    fs = FetchSettings(
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        cache_dir=args.cache_dir,
        cache_ttl_hours=args.cache_ttl,
        offline=args.offline,
        proxies=[p for p in (args.proxy or []) if p],
        use_browser_fallback=args.browser,
    )
    history = None if args.no_history else History(args.history_db)
    return Hunter(Fetcher(fs), Settings.load(args.settings), history, args.workers, _progress(args.quiet))


def cmd_hunt(args) -> int:
    unknown = [c for c in args.categories or [] if c not in CATEGORIES]
    if unknown:
        print(f"unknown categories: {', '.join(unknown)} (see `amzphunt categories`)", file=sys.stderr)
        return 2
    hunter = _build(args)
    opps = hunter.hunt(args.categories, args.depth, args.pages, args.sources, args.deep, args.max_subcategories)
    if not opps:
        print(f"No products discovered - amazon.ae is probably blocking this IP. Requests: {hunter.fetcher.stats}",
              file=sys.stderr)
        return 4
    if args.only:
        opps = [o for o in opps if o.verdict in args.only]
    print(console_table(opps, args.top))
    meta = {"categories": args.categories or NEW_SELLER_CATEGORIES, "depth": args.depth, "deep": args.deep,
            "settings": hunter.settings.to_dict(), "fetch_stats": hunter.fetcher.stats,
            "calibrated_categories": hunter.estimator.calibrated}
    paths = write_all(opps, args.out, meta)
    print(f"\nReports: {paths['html']}\n         {paths['csv']}\n         {paths['json']}")
    print(f"Requests: {hunter.fetcher.stats}")
    return 0


def cmd_niche(args) -> int:
    hunter = _build(args)
    failures = 0
    for kw in args.keywords:
        n = hunter.niche(kw)
        if not n:
            print(f"{kw}: no data (request failed or blocked)")
            failures += 1
            continue
        verdict = "OPEN" if (n.median_reviews or 0) <= hunter.settings.max_median_reviews and n.share_over_1000_reviews < 0.3 else "CROWDED"
        print(f"\n== {kw} ==  [{verdict}]")
        print(f"  results: {n.total_results}  organic: {n.organic_count}  sponsored: {n.sponsored_count}")
        print(f"  median price: AED {n.median_price}   median reviews: {n.median_reviews}   top-10 median: {n.top10_median_reviews}")
        print(f"  mean rating: {n.mean_rating}   <4 stars: {n.low_rated_share:.0%}   >1000 reviews: {n.share_over_1000_reviews:.0%}")
        print(f"  brands: {n.distinct_brands}   top brand share: {n.top_brand_share:.0%}")
        print(f"  page-1 demand: {n.demand_bought_month}+ bought/month across {n.listings_with_demand} listings")
        if n.median_price:
            e = unit_economics(n.median_price, args.category or "", settings=hunter.settings)
            print(f"  at median price: profit AED {e.profit:.2f}/unit, margin {e.margin:.0%}, ROI {e.roi:.0%} "
                  f"(max supplier price for target ROI: AED {max_unit_cost(n.median_price, args.category or '', settings=hunter.settings)})")
    return 1 if failures == len(args.keywords) else 0


def cmd_product(args) -> int:
    hunter = _build(args)
    failures = 0
    for asin in args.asins:
        o = hunter.evaluate_asin(asin.strip().upper(), args.cost, args.keyword or "")
        if not o:
            print(f"{asin}: could not fetch (request failed or blocked)")
            failures += 1
            continue
        d = o.detail
        print(f"\n== {o.asin} :: {o.verdict} ({o.score:.0f}/100) ==")
        print(f"  {o.title[:120]}")
        print(f"  price AED {o.price}  BSR {d.bsr if d else '-'}  bought/mo {d.bought_past_month if d else '-'}  "
              f"est. sales ~{o.est_monthly_sales}/mo")
        print(f"  seller: {d.seller or '-'}  ships from: {d.ships_from or '-'}  weight: {d.weight_kg} kg  dims: {d.dimensions_cm}")
        print(f"  keyword: {o.keyword}   components: {o.component_scores}")
        if o.economics:
            e = o.economics
            print(f"  economics: profit AED {e.profit:.2f}/unit  margin {e.margin:.0%}  ROI {e.roi:.0%}  "
                  f"(fees: referral {e.referral_fee}, FBA {e.fba_fee} [{e.size_tier}], landed {e.landed_cost})")
        for r in o.reasons:
            print(f"  + {r}")
        for r in o.risks:
            print(f"  - {r}")
    return 1 if failures == len(args.asins) else 0


def cmd_profit(args) -> int:
    dims = parse_dimensions_cm(args.dims) if args.dims else None
    st = Settings.load(args.settings)
    e = unit_economics(args.price, args.category or "", dims, args.weight, st, args.cost)
    print(f"Sale price (incl. 5% VAT): AED {e.price:.2f}")
    print(f"  net of VAT            : AED {e.net_price:.2f}")
    print(f"  referral fee          : AED {e.referral_fee:.2f}")
    print(f"  FBA fee ({e.size_tier:<8})    : AED {e.fba_fee:.2f}")
    print(f"  storage               : AED {e.storage_fee:.2f}")
    print(f"  VAT on Amazon fees    : AED {e.assumptions['fees_vat']:.2f}")
    print(f"  landed cost           : AED {e.landed_cost:.2f}  (unit {e.assumptions['unit_cost']:.2f}"
          f"{' est.' if e.assumptions['unit_cost_estimated'] else ''}, freight {e.assumptions['freight']:.2f}, duty {e.assumptions['duty']:.2f})")
    print(f"  PPC allowance         : AED {e.ppc_cost:.2f}")
    print(f"Profit / unit           : AED {e.profit:.2f}   margin {e.margin:.0%}   ROI {e.roi:.0%}")
    print(f"Max supplier price for {st.min_roi:.0%} ROI & {st.min_margin:.0%} margin: "
          f"AED {max_unit_cost(args.price, args.category or '', dims, args.weight, st)}")
    return 0


def cmd_latest(args) -> int:
    print(summarize_latest(args.out, args.top, args.only, args.format))
    return 0


def cmd_categories(args) -> int:
    for slug, name in CATEGORIES.items():
        tag = "recommended" if slug in NEW_SELLER_CATEGORIES else f"avoid: {AVOID_CATEGORIES[slug]}" if slug in AVOID_CATEGORIES else ""
        print(f"  {slug:<18} {name:<42} {tag}")
    return 0


def _fetch_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("fetching")
    g.add_argument("--min-delay", type=float, default=2.0, help="min seconds between requests (default 2)")
    g.add_argument("--max-delay", type=float, default=5.0, help="max seconds between requests (default 5)")
    g.add_argument("--workers", type=int, default=3, help="parallel fetch workers (default 3)")
    g.add_argument("--cache-dir", default=".amzphunt_cache")
    g.add_argument("--cache-ttl", type=float, default=12.0, help="hours before cached pages are refetched")
    g.add_argument("--offline", action="store_true", help="use cached pages only, no network")
    g.add_argument("--proxy", action="append", help="proxy URL, repeatable (rotated on blocks)")
    g.add_argument("--browser", action="store_true", help="Playwright fallback when captcha'd")
    g.add_argument("--settings", help="JSON file overriding scoring thresholds (see settings.example.json)")
    g.add_argument("--history-db", default="amzphunt_history.db")
    g.add_argument("--no-history", action="store_true")
    g.add_argument("-q", "--quiet", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="amzphunt", description="Find winning products for new sellers on Amazon UAE (amazon.ae).")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("hunt", help="discover and rank winning products")
    h.add_argument("-c", "--categories", nargs="+", help="category slugs (default: new-seller friendly set)")
    h.add_argument("--depth", type=int, default=1, help="sub-category levels to crawl (default 1)")
    h.add_argument("--pages", type=int, default=2, choices=[1, 2], help="list pages per node (default 2)")
    h.add_argument("--sources", nargs="+", default=list(LIST_SOURCES), choices=LIST_SOURCES)
    h.add_argument("--max-subcategories", type=int, default=25)
    h.add_argument("--deep", type=int, default=40, help="products to deep-dive (product page + niche search)")
    h.add_argument("--top", type=int, default=25, help="rows to print")
    h.add_argument("--only", nargs="+", choices=["WINNER", "PROMISING", "RISKY", "AVOID"])
    h.add_argument("-o", "--out", default="reports")
    _fetch_args(h)
    h.set_defaults(func=cmd_hunt)

    n = sub.add_parser("niche", help="analyse keyword niches (page 1 competition & demand)")
    n.add_argument("keywords", nargs="+")
    n.add_argument("--category", help="category slug for fee calculation")
    _fetch_args(n)
    n.set_defaults(func=cmd_niche)

    p = sub.add_parser("product", help="deep-evaluate specific ASINs")
    p.add_argument("asins", nargs="+")
    p.add_argument("--cost", type=float, help="your supplier unit cost in AED")
    p.add_argument("--keyword", help="override the niche keyword")
    _fetch_args(p)
    p.set_defaults(func=cmd_product)

    f = sub.add_parser("profit", help="UAE FBA profit calculator")
    f.add_argument("--price", type=float, required=True, help="sale price in AED incl. VAT")
    f.add_argument("--cost", type=float, help="supplier unit cost in AED")
    f.add_argument("--weight", type=float, help="kg")
    f.add_argument("--dims", help="e.g. 25x15x5 (cm)")
    f.add_argument("--category", default="")
    f.add_argument("--settings")
    f.set_defaults(func=cmd_profit)

    l = sub.add_parser("latest", help="print a digest of the newest hunt report (for agents/chat)")
    l.add_argument("-o", "--out", default="reports")
    l.add_argument("--top", type=int, default=10)
    l.add_argument("--only", nargs="+", choices=["WINNER", "PROMISING", "RISKY", "AVOID"])
    l.add_argument("--format", choices=["md", "json"], default="md")
    l.set_defaults(func=cmd_latest)

    c = sub.add_parser("categories", help="list amazon.ae categories and recommendations")
    c.set_defaults(func=cmd_categories)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
