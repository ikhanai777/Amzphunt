# amzphunt — Amazon UAE Product Hunter

A command-line product-research tool for people starting to sell on **amazon.ae**.
It crawls the UAE marketplace, estimates how much each product sells, checks how
hard its niche is to break into, works out the profit after UAE fees, and gives
each product a score and a verdict (**WINNER / PROMISING / RISKY / AVOID**) along
with the reasons behind it.

```
$ amzphunt hunt --depth 1 --max-subcategories 6 --deep 45     # live run, Sep 2026

#   Verdict    Score  ASIN        AED  Sales/mo  Reviews  Niche med.rev  Profit  Keyword
--  ---------  -----  ----------  ---  --------  -------  -------------  ------  ----------------------------
1   WINNER     84     B0GHLX75X3  125  765       212      479            48      wide leg pants
2   WINNER     80     B0HJ591HV9  90   452       35       35             30      carplay wireless adapter
3   WINNER     76     B0BJ9MDJK3  60   195       60       18             15      magnetic whiteboard planners
...
Reports: reports/hunt-20260925-2124.html   (visual dashboard)
         reports/hunt-20260925-2124.csv    (spreadsheet)
         reports/hunt-20260925-2124.json   (full data)
```

## How it finds a winner

| Stage | What happens |
|---|---|
| **1. Discover** | Crawls **Best Sellers**, **New Releases** and **Movers & Shakers** for each category and its sub-categories (breadth-first, `--depth`). |
| **2. Pre-filter** | Scores every product using only the list-page data. Big brands, hazmat and gated items, and prices outside the target range are dropped. The best `--deep` products go forward, with a cap per sub-category so one node can't fill the list. |
| **3. Enrich** | Scrapes each product page for BSR, Amazon's own *"X+ bought in past month"* badge, seller and fulfilment, weight, dimensions, variations, image count, A+ content, video and launch date. |
| **4. Self-calibrate** | Fits the BSR → monthly-sales power law separately for each category, using the (BSR, bought-in-past-month) pairs seen during this run. Estimates follow the live UAE market, not fixed US-based figures. |
| **5. Niche analysis** | Works out the search term buyers would type, using the title and the product's narrowest category (e.g. *"steel water bottle"*). It then reads page 1 of the search results: result count, median and top-10 reviews, share of listings with more than 1000 reviews, brand concentration, sponsored density, low-rated share and total "bought in past month" demand. A relevance check flags vague keywords. |
| **6. Score** | Five components (0–100) → weighted total → verdict. Hard-stop risks cap the score: hazmat, MOHAP/food registration, IP, loss-making products and dead demand. |
| **7. History** | Every scan is saved to SQLite. Later runs compare BSR against the previous scan to spot rising products and fading fads. |

### Score components

| Component | Weight | Signals |
|---|---|---|
| Demand | 27% | Estimated monthly units (BSR model + bought badge), total demand on the niche's page 1 |
| Competition | 27% | Median reviews on page 1, top-10 median, share with >1000 reviews, share with <100 reviews, top brand share, ads density, result count |
| Profit | 20% | Margin and ROI after referral fee, FBA fee, storage, VAT, freight, customs duty and PPC; AED 50–180 sweet spot |
| Ease | 14% | Weight and size tier; gated, hazmat or certification flags; Amazon.ae holding the buy box; number of variations |
| Opportunity | 12% | Low-rated competitors, weak listings (few images, no A+ content or video), high sales with few reviews, recent launch already selling, Movers & Shakers or New Releases presence, BSR trend, UAE seasonality (Ramadan, summer, back-to-school, National Day and others) |

### UAE-specific knowledge built in

- **Fees**: referral fee by category, FBA fees by size tier and weight (envelope, standard, oversize) using dimensional weight, monthly storage per CBM, 5% VAT on the sale price and on Amazon's fees.
- **Landed cost**: sea LCL freight from China to Jebel Ali, charged on weight or volume (whichever is higher), plus 5% GCC customs duty on the CIF value.
- **Compliance flags**: batteries and aerosols (hazmat), fragrance and oud (gated), supplements (MOHAP), cosmetics and food (municipality registration), electricals (ECAS / G-mark), drones (GCAA), vapes (prohibited), and licensed IP.
- **Categories**: recommended starting categories, plus categories to avoid and why (`amzphunt categories`).
- **Seasonality**: a UAE retail calendar that shows upcoming demand peaks so you can launch 6–8 weeks ahead.

## Install

```bash
pip install -e .            # or: pip install -r requirements.txt
pip install -e ".[browser]" && playwright install chromium   # optional captcha fallback
```

## Usage

```bash
# Full hunt over the new-seller-friendly categories
amzphunt hunt

# Targeted, deeper hunt; only show the good ones
amzphunt hunt -c kitchen pet-products --depth 2 --max-subcategories 15 --deep 80 --only WINNER PROMISING

# Validate niche ideas you already have
amzphunt niche "car sun shade" "prayer mat" "lunch box" --category automotive

# Evaluate a specific competitor ASIN (optionally with your supplier quote in AED)
amzphunt product B0CQM4ZNPZ --cost 14

# Profit calculator
amzphunt profit --price 79 --weight 0.4 --dims 25x15x5 --category kitchen --cost 12

# List categories with recommendations
amzphunt categories
```

Useful flags (all commands that scrape):

| Flag | Purpose |
|---|---|
| `--min-delay / --max-delay` | Random delay between requests (default 2–5 s). Keep it polite. |
| `--workers` | Number of parallel fetch workers (default 3). All workers share one rate limiter. |
| `--proxy URL` | Can be repeated. Proxies rotate after a block. |
| `--browser` | Headless-Chromium fallback when Amazon shows a captcha (needs Playwright). |
| `--offline` | Rebuild reports from cached pages only, with no network requests. |
| `--cache-ttl` | How many hours cached pages stay fresh (default 12). |
| `--settings file.json` | Override the thresholds that define a winner (see `settings.example.json`). |

Run it on a schedule (e.g. daily cron). The history database then turns single snapshots into
trend data, so products whose BSR keeps improving rise in the rankings.

## Reading the verdicts

- **WINNER (≥72)**: proven demand, page 1 is beatable, healthy margins and easy logistics. Order samples.
- **PROMISING (58–71)**: good overall with one weak area. Read the risks list before acting.
- **RISKY (45–57)**: possible, but only with a clear edge such as a better product, a bundle or an Arabic-market angle.
- **AVOID (<45)**: loses money, has no demand, or is blocked by gating or compliance.

The HTML report shows every product's component bars, full fee breakdown, niche statistics,
*"why it can win"* and *"risks"*.

## Local deployment with an agent (Hermes)

To run this unattended on your own machine with the [Hermes Agent](https://hermes-agent.nousresearch.com),
give Hermes **[HERMES_DEPLOY.md](HERMES_DEPLOY.md)**. It covers installing the tool, checking that
live access works, installing the bundled skill (`.hermes/skills/amzphunt/SKILL.md`), running a first
hunt, and scheduling a daily hunt whose digest is sent to Telegram or another chat.

Helper scripts that also work without Hermes:

```bash
bash scripts/setup_local.sh          # venv + install + tests + live smoke test
bash scripts/run_hunt.sh daily       # locked, logged hunt (presets: quick | daily | deep), then prints digest
amzphunt latest --top 5              # digest of the newest report; [NEW] marks products not in the previous one
amzphunt latest --format json        # the same digest as JSON, for agents
```

Exit codes: `0` ok · `1` every fetch failed · `2` bad input or setup · `3` a hunt is already running · `4` nothing found (probably blocked).

## Scraping notes

- Uses UAE locale and AED currency cookies, rotating browser headers, and random jittered delays.
  When blocked it backs off exponentially, pausing all workers, and switches to a new identity or proxy.
- Parsers rely on stable hooks such as ids, `data-*` attributes, aria labels and visible text,
  rather than Amazon's hashed CSS classes. Every field falls back to a default instead of crashing the run.
- Pages are cached on disk, so re-runs and `--offline` report generation make no requests.
- Respect Amazon's terms of service and keep request rates low. This tool is for personal market research.

## Caveats

Sales and profit figures are **estimates**. Fee tables follow amazon.ae's public schedules but Amazon
changes them, so check them in Seller Central. Replace the estimated cost of goods (`cogs_ratio`) with
real supplier quotes (`--cost`) before placing an order.

## Development

```bash
pip install -e ".[dev]"
pytest
```
