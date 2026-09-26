---
name: amzphunt
description: Hunt winning Amazon UAE products with amzphunt
version: 1.0.0
platforms: [linux, macos]
metadata:
  hermes:
    category: research
    tags: [amazon, ecommerce, uae, product-research, scraping]
    requires_toolsets: [terminal]
---

# amzphunt: Amazon UAE product hunter

You operate `amzphunt`, a local CLI that scrapes live data from amazon.ae. It finds, scores and
explains products a **new** Amazon UAE seller can win with. The install lives at
`~/Amzphunt` (if it was installed elsewhere, use that path everywhere below).

Always run commands from the install directory with the virtualenv active:

```bash
cd ~/Amzphunt && source .venv/bin/activate
```

## Pick the command from the user's intent

| User wants | Command | Time |
|---|---|---|
| "Find me products" / daily hunt | `bash scripts/run_hunt.sh daily` | 20-30 min |
| Quick look | `bash scripts/run_hunt.sh quick` | ~5 min |
| Thorough hunt | `bash scripts/run_hunt.sh deep` | 60-90 min |
| Hunt specific categories | `bash scripts/run_hunt.sh daily -c kitchen pet-products` | 10-20 min |
| "Is <idea> a good product?" | `amzphunt niche "<keyword>" [--category <slug>]` | <1 min |
| Evaluate a competitor ASIN | `amzphunt product <ASIN> [--cost <supplier AED>]` | ~1 min |
| Profit for a price/cost | `amzphunt profit --price 79 --cost 12 --weight 0.4 --dims 25x15x5 --category kitchen` | instant |
| "What did the last hunt find?" | `amzphunt latest --top 10` (add `--format json` to parse) | instant |
| Re-score without scraping | `amzphunt hunt <same args> --offline` | ~1 min |
| Valid category slugs | `amzphunt categories` | instant |

Run hunts in the background. They are slow on purpose, pausing 2-5 seconds between requests.
Tell the user roughly how long it will take, then report when it finishes. Do not keep checking in a tight loop.

## Hard rules

1. **Never run two scraping commands at the same time.** `run_hunt.sh` holds a lock. If it exits
   with code 3, a hunt is already running, so wait for it.
2. **Never pass `--min-delay` below 2 or `--workers` above 3.** Amazon blocks aggressive clients
   by IP for hours.
3. **If blocked** (exit code 4, "HTTP 503", "captcha page" or "no data (request failed or blocked)"), stop
   scraping for at least 60 minutes. Do not retry in a loop. Use `--offline` to work from the cache
   meanwhile, and tell the user.
4. **Sales and profit figures are estimates.** Always say so. Never tell the user to order stock based
   on the tool alone. They need supplier quotes (`--cost`), samples and a check of Seller Central fees.
5. Do not edit fee tables in `amzphunt/config.py` or the thresholds in `settings.json` unless the user asks.
6. Never buy, order, contact suppliers, or log in to Amazon on the user's behalf.

## Exit codes

`0` ok · `1` every requested item failed to fetch · `2` bad arguments or setup problem ·
`3` another hunt is running · `4` hunt found nothing (probably blocked).

## Reading results

Verdicts: **WINNER** (72 or more: demand is proven, page 1 is beatable, economics are healthy, no serious risks) ·
**PROMISING** (58-71: one weak area, so read the risks) · **RISKY** (45-57) · **AVOID** (below 45: loses money,
gated or hazmat, or no demand).

Each product lists *reasons* (why it can win) and *risks*. Treat these risks as serious:
"certification", "gated", "hazmat", "MOHAP", "IP /", "entrenched competitors", "ambiguous" keyword
(the niche data may describe other products, so validate it with `amzphunt niche "<better keyword>"`),
and "Amazon.ae holds the buy box".

Reports are written to `~/Amzphunt/reports/hunt-<timestamp>.{html,csv,json}`. The HTML file is the
visual dashboard. Send it as a document when the user wants the details.

## Reporting to the user (chat or Telegram)

Base the reply on `amzphunt latest --top 5`. Keep it short:

```
Amazon UAE hunt - <date>: <W> winners, <P> promising (of <N> analysed)

1. [NEW] <keyword> - AED <price>, ~<sales>/mo, ~AED <profit>/unit (<verdict> <score>)
   Why: <top reason>. Watch: <top risk>.
   <url>
...
Estimates only: validate with supplier quotes before ordering.
```

Put products marked `[NEW]` (not in the previous report) first. If there are no WINNERs, say so
plainly and show the best PROMISING products.

## Maintenance

- Update: `cd ~/Amzphunt && git pull && bash scripts/setup_local.sh --no-live`
- Health check: `bash scripts/setup_local.sh`. Exit 0 means live access works. Exit 2 means blocked or offline.
- Disk: `.amzphunt_cache/` grows by about 1 MB per page. Delete files older than 7 days if space is low:
  `find .amzphunt_cache -mtime +7 -delete`
