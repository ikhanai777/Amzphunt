"""Export results: console table, CSV, JSON and a self-contained HTML report."""

from __future__ import annotations

import csv
import datetime as dt
import html
import json
from dataclasses import asdict
from pathlib import Path

from .models import Opportunity

VERDICT_COLORS = {"WINNER": "#1a7f37", "PROMISING": "#2f6fdb", "RISKY": "#b7791f", "AVOID": "#c53030"}


def console_table(opps: list[Opportunity], limit: int = 25) -> str:
    rows = [("#", "Verdict", "Score", "ASIN", "AED", "Sales/mo", "Reviews", "Niche med.rev", "Profit", "Keyword")]
    for i, o in enumerate(opps[:limit], 1):
        f = o.flat()
        rows.append(
            (
                str(i),
                o.verdict,
                f"{o.score:.0f}",
                o.asin,
                f"{o.price:.0f}" if o.price else "-",
                str(o.est_monthly_sales or "-"),
                str(f["reviews"] or 0),
                str(int(o.niche.median_reviews)) if o.niche and o.niche.median_reviews is not None else "-",
                f"{o.economics.profit:.0f}" if o.economics else "-",
                o.keyword[:32],
            )
        )
    widths = [max(len(r[c]) for r in rows) for c in range(len(rows[0]))]
    lines = ["  ".join(cell.ljust(widths[c]) for c, cell in enumerate(r)) for r in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def write_csv(opps: list[Opportunity], path: Path) -> None:
    rows = []
    for i, o in enumerate(opps, 1):
        r = o.flat()
        r["rank"] = i
        rows.append(r)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as fh:  # BOM so Excel reads Arabic brand names
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _serialise(o: Opportunity) -> dict:
    d = asdict(o)
    if d.get("niche"):
        d["niche"]["listings"] = [
            {k: l[k] for k in ("asin", "title", "price", "rating", "reviews", "bought_past_month", "sponsored")}
            for l in d["niche"]["listings"][:20]
        ]
    return d


def write_json(opps: list[Opportunity], path: Path, meta: dict | None = None) -> None:
    payload = {"generated_at": dt.datetime.now().isoformat(timespec="seconds"), "meta": meta or {},
               "results": [_serialise(o) for o in opps]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _bar(label: str, value: float) -> str:
    return (
        f'<div class="bar"><span>{label}</span><div class="track"><div class="fill" '
        f'style="width:{value:.0f}%"></div></div><b>{value:.0f}</b></div>'
    )


def write_html(opps: list[Opportunity], path: Path, meta: dict | None = None, top_cards: int = 12) -> None:
    e = html.escape
    meta = meta or {}
    counts = {v: sum(o.verdict == v for o in opps) for v in VERDICT_COLORS}
    cards = []
    for i, o in enumerate(opps[:top_cards], 1):
        f = o.flat()
        econ = o.economics
        n = o.niche
        img = o.listing.image if o.listing else ""
        comps = "".join(_bar(k.title(), v) for k, v in o.component_scores.items())
        reasons = "".join(f"<li>{e(r)}</li>" for r in o.reasons) or "<li>-</li>"
        risks = "".join(f"<li>{e(r)}</li>" for r in o.risks) or "<li>none detected</li>"
        econ_html = (
            f"<table class='kv'><tr><td>Price</td><td>AED {econ.price:.2f}</td></tr>"
            f"<tr><td>Referral fee</td><td>AED {econ.referral_fee:.2f}</td></tr>"
            f"<tr><td>FBA fee ({e(econ.size_tier)})</td><td>AED {econ.fba_fee:.2f}</td></tr>"
            f"<tr><td>Landed cost{' (est.)' if econ.assumptions.get('unit_cost_estimated') else ''}</td><td>AED {econ.landed_cost:.2f}</td></tr>"
            f"<tr><td>PPC</td><td>AED {econ.ppc_cost:.2f}</td></tr>"
            f"<tr><th>Profit / unit</th><th>AED {econ.profit:.2f} &middot; {econ.margin:.0%} margin &middot; {econ.roi:.0%} ROI</th></tr></table>"
            if econ else "<p>Price unknown</p>"
        )
        niche_html = (
            f"<table class='kv'><tr><td>Search results</td><td>{n.total_results or '-'}</td></tr>"
            f"<tr><td>Median price</td><td>AED {n.median_price or 0:.0f}</td></tr>"
            f"<tr><td>Median reviews (page 1)</td><td>{n.median_reviews if n.median_reviews is not None else '-'}</td></tr>"
            f"<tr><td>Listings &gt;1000 reviews</td><td>{n.share_over_1000_reviews:.0%}</td></tr>"
            f"<tr><td>Top brand share</td><td>{n.top_brand_share:.0%}</td></tr>"
            f"<tr><td>Page-1 bought/month</td><td>{n.demand_bought_month}+</td></tr></table>"
            if n else "<p>No niche data</p>"
        )
        cards.append(
            f"""<article class="card">
  <header><span class="rank">#{i}</span><span class="verdict" style="background:{VERDICT_COLORS[o.verdict]}">{o.verdict}</span>
  <span class="score">{o.score:.0f}<small>/100</small></span></header>
  <div class="top">{f'<img src="{e(img)}" alt="">' if img else ''}<div>
  <a href="{e(o.url)}" target="_blank" rel="noopener"><h3>{e(o.title[:140])}</h3></a>
  <p class="muted">{e(o.asin)} &middot; {e(o.category)} &middot; keyword: <b>{e(o.keyword)}</b></p>
  <p class="big">AED {o.price or 0:.2f} &middot; ~{o.est_monthly_sales or '?'} sales/mo &middot; ~AED {f['est_monthly_revenue_aed'] or 0:,} revenue/mo</p>
  </div></div>
  <div class="grid"><div>{comps}</div><div>{econ_html}</div><div>{niche_html}</div></div>
  <div class="grid2"><div><h4>Why it can win</h4><ul>{reasons}</ul></div><div><h4>Risks</h4><ul class="risk">{risks}</ul></div></div>
</article>"""
        )

    rows = []
    for i, o in enumerate(opps, 1):
        f = o.flat()
        rows.append(
            "<tr>"
            f"<td>{i}</td><td><span class='pill' style='background:{VERDICT_COLORS[o.verdict]}'>{o.verdict}</span></td>"
            f"<td>{o.score:.0f}</td><td><a href='{e(o.url)}' target='_blank' rel='noopener'>{e(o.asin)}</a></td>"
            f"<td class='t'>{e(o.title[:90])}</td><td>{e(o.keyword)}</td><td>{o.price or ''}</td>"
            f"<td>{o.est_monthly_sales or ''}</td><td>{f['reviews'] or 0}</td><td>{f['niche_median_reviews'] if f['niche_median_reviews'] is not None else ''}</td>"
            f"<td>{f['profit_per_unit_aed'] if f['profit_per_unit_aed'] is not None else ''}</td><td>{f['roi'] if f['roi'] is not None else ''}</td>"
            f"<td>{f['weight_kg'] or ''}</td></tr>"
        )

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Amazon UAE Product Hunt</title>
<style>
:root {{ --bg:#f6f7f9; --card:#fff; --text:#1c2024; --muted:#5f6b7a; --line:#e3e6ea; --accent:#ff9900; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#111418; --card:#1a1f25; --text:#e6e9ed; --muted:#9aa5b1; --line:#2a313a; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; background:var(--bg); color:var(--text) }}
main {{ max-width:1200px; margin:0 auto; padding:24px 16px }}
h1 {{ margin:0 0 4px; font-size:26px }} h3 {{ margin:0 0 4px; font-size:16px; color:var(--text) }}
a {{ color:inherit }} .muted {{ color:var(--muted); margin:2px 0 }}
.summary {{ display:flex; gap:12px; flex-wrap:wrap; margin:16px 0 24px }}
.stat {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 16px; min-width:120px }}
.stat b {{ display:block; font-size:22px }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; margin-bottom:16px }}
.card header {{ display:flex; align-items:center; gap:10px; margin-bottom:10px }}
.rank {{ font-weight:700; color:var(--muted) }} .score {{ margin-left:auto; font-size:24px; font-weight:700 }}
.score small {{ font-size:12px; color:var(--muted) }}
.verdict,.pill {{ color:#fff; border-radius:999px; padding:2px 10px; font-size:12px; font-weight:600 }}
.top {{ display:flex; gap:14px }} .top img {{ width:96px; height:96px; object-fit:contain; background:#fff; border-radius:8px }}
.big {{ font-weight:600 }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:16px; margin-top:12px }}
.grid2 {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px }}
.bar {{ display:flex; align-items:center; gap:8px; margin:4px 0 }} .bar span {{ width:92px; color:var(--muted) }}
.track {{ flex:1; height:8px; background:var(--line); border-radius:4px; overflow:hidden }}
.fill {{ height:100%; background:var(--accent) }}
.kv {{ width:100%; border-collapse:collapse }} .kv td,.kv th {{ padding:3px 0; border-bottom:1px solid var(--line); text-align:left }}
.kv td:last-child,.kv th:last-child {{ text-align:right }}
h4 {{ margin:12px 0 4px }} ul {{ margin:0; padding-left:18px }} .risk li {{ color:#c53030 }}
@media (prefers-color-scheme: dark) {{ .risk li {{ color:#fc8181 }} }}
.tablewrap {{ overflow-x:auto; background:var(--card); border:1px solid var(--line); border-radius:12px }}
table.all {{ border-collapse:collapse; width:100%; font-size:13px }}
table.all th,table.all td {{ padding:6px 8px; border-bottom:1px solid var(--line); white-space:nowrap; text-align:left }}
table.all th {{ cursor:pointer; position:sticky; top:0; background:var(--card) }}
td.t {{ white-space:normal; min-width:260px }}
</style></head><body><main>
<h1>Amazon UAE Product Hunt</h1>
<p class="muted">Generated {dt.datetime.now():%Y-%m-%d %H:%M} &middot; amazon.ae &middot; categories: {e(', '.join(meta.get('categories', [])))} &middot; {len(opps)} products scored</p>
<div class="summary">
<div class="stat"><b style="color:{VERDICT_COLORS['WINNER']}">{counts['WINNER']}</b>Winners</div>
<div class="stat"><b style="color:{VERDICT_COLORS['PROMISING']}">{counts['PROMISING']}</b>Promising</div>
<div class="stat"><b style="color:{VERDICT_COLORS['RISKY']}">{counts['RISKY']}</b>Risky</div>
<div class="stat"><b style="color:{VERDICT_COLORS['AVOID']}">{counts['AVOID']}</b>Avoid</div>
</div>
<h2>Top picks</h2>
{''.join(cards) or '<p>No products scored.</p>'}
<h2>All scored products</h2>
<div class="tablewrap"><table class="all" id="all"><thead><tr>
<th>#</th><th>Verdict</th><th>Score</th><th>ASIN</th><th>Title</th><th>Keyword</th><th>AED</th><th>Sales/mo</th><th>Reviews</th><th>Niche med. reviews</th><th>Profit/unit</th><th>ROI</th><th>kg</th>
</tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p class="muted">Estimates only. Sales are modelled from BSR and Amazon's "bought in past month" badges; fees use approximate amazon.ae
schedules. Verify fees in Seller Central and get real supplier quotes before ordering.</p>
</main>
<script>
document.querySelectorAll('#all th').forEach((th, i) => th.addEventListener('click', () => {{
  const body = th.closest('table').tBodies[0];
  const rows = [...body.rows];
  const dir = th.dataset.dir = th.dataset.dir === 'asc' ? 'desc' : 'asc';
  const val = r => {{ const t = r.cells[i].innerText.trim(); const n = parseFloat(t.replace(/,/g, '')); return isNaN(n) ? t : n; }};
  rows.sort((a, b) => {{ const x = val(a), y = val(b); return (x > y ? 1 : x < y ? -1 : 0) * (dir === 'asc' ? 1 : -1); }});
  rows.forEach(r => body.appendChild(r));
}}));
</script></body></html>"""
    path.write_text(doc, encoding="utf-8")


def write_all(opps: list[Opportunity], out_dir: str | Path, meta: dict | None = None, stem: str = "hunt") -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    paths = {
        "csv": out / f"{stem}-{stamp}.csv",
        "json": out / f"{stem}-{stamp}.json",
        "html": out / f"{stem}-{stamp}.html",
    }
    write_csv(opps, paths["csv"])
    write_json(opps, paths["json"], meta)
    write_html(opps, paths["html"], meta)
    return paths


def _report_files(out_dir: str | Path) -> list[Path]:
    return sorted(Path(out_dir).glob("hunt-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def summarize_latest(out_dir: str | Path, top: int = 10, verdicts: list[str] | None = None, fmt: str = "md") -> str:
    """Compact digest of the newest hunt report, for agents and chat delivery.

    Marks products that were not in the previous report as NEW, so a daily
    message highlights what changed rather than repeating yesterday's list.
    """
    files = _report_files(out_dir)
    if not files:
        return "No reports found. Run `amzphunt hunt` first."
    latest = json.loads(files[0].read_text(encoding="utf-8"))
    previous = {r["asin"] for r in json.loads(files[1].read_text(encoding="utf-8"))["results"]} if len(files) > 1 else set()
    verdicts = verdicts or ["WINNER", "PROMISING"]
    rows = [r for r in latest["results"] if r["verdict"] in verdicts][:top]
    items = []
    for r in rows:
        econ = r.get("economics") or {}
        niche = r.get("niche") or {}
        items.append(
            {
                "asin": r["asin"],
                "new": bool(previous) and r["asin"] not in previous,
                "verdict": r["verdict"],
                "score": r["score"],
                "title": r["title"][:100],
                "keyword": r["keyword"],
                "price_aed": r["price"],
                "est_monthly_sales": r["est_monthly_sales"],
                "profit_per_unit_aed": econ.get("profit"),
                "roi": econ.get("roi"),
                "niche_median_reviews": niche.get("median_reviews"),
                "reasons": r["reasons"][:3],
                "risks": r["risks"][:3],
                "url": r["url"],
            }
        )
    counts = {v: sum(r["verdict"] == v for r in latest["results"]) for v in VERDICT_COLORS}
    if fmt == "json":
        return json.dumps({"report": str(files[0]), "html": str(files[0].with_suffix(".html")),
                           "generated_at": latest["generated_at"], "counts": counts, "top": items},
                          indent=2, ensure_ascii=False)
    lines = [
        f"# Amazon UAE hunt - {latest['generated_at'][:16].replace('T', ' ')}",
        f"{counts['WINNER']} winners, {counts['PROMISING']} promising, {counts['RISKY']} risky, {counts['AVOID']} avoid "
        f"(of {len(latest['results'])} analysed)",
        "",
    ]
    for i, it in enumerate(items, 1):
        profit = f"AED {it['profit_per_unit_aed']:.0f}/unit" if it["profit_per_unit_aed"] is not None else "profit ?"
        lines.append(
            f"{i}. {'[NEW] ' if it['new'] else ''}{it['verdict']} {it['score']:.0f} - {it['keyword']} - "
            f"AED {it['price_aed'] or 0:.0f}, ~{it['est_monthly_sales'] or '?'}/mo, {profit}"
        )
        lines.append(f"   {it['title']}")
        if it["reasons"]:
            lines.append(f"   + {'; '.join(it['reasons'])}")
        if it["risks"]:
            lines.append(f"   - {'; '.join(it['risks'])}")
        lines.append(f"   {it['url']}")
    if not items:
        lines.append("No products matched the requested verdicts this run.")
    lines += ["", f"Full report: {files[0].with_suffix('.html')}"]
    return "\n".join(lines)
