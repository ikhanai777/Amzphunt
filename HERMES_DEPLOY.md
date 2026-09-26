# Deploying amzphunt with Hermes Agent

**Audience: the Hermes Agent (Nous Research) running on the user's machine.**
Follow the phases in order. Each phase ends with a **Check**: do not continue until it passes.
If a check fails, use the Troubleshooting table at the end, and if that does not fix it, stop
and report the exact error output to the user.

**Goal:** install amzphunt locally, confirm it can read live data from amazon.ae, install its
Hermes skill, run a first real hunt, and schedule a daily hunt that sends a digest to the user's
chat (e.g. Telegram).

**Where it should run:** a Linux or macOS machine (Windows via WSL2) on a home or office
connection, preferably in the UAE. Datacenter and VPS IPs are blocked by Amazon much more
often, so avoid them unless the user supplies residential proxies (see Phase 7).

---

## Phase 0 - Prerequisites

Run:

```bash
python3 --version        # needs 3.9 or newer
git --version
df -h ~ | tail -1        # needs ~1 GB free
curl -sS -o /dev/null -w "%{http_code}\n" -A "Mozilla/5.0" https://www.amazon.ae/
```

- Python missing or too old: Ubuntu/Debian `sudo apt-get install -y python3 python3-venv python3-pip git`;
  macOS `brew install python git`. **Ask the user before running sudo.**
- Debian/Ubuntu also need `python3-venv` for the virtualenv step.

**Check:** Python is 3.9 or newer, git exists, and the curl command prints `200`. A `503` means this IP is
already being throttled: tell the user and continue, because setup still works.

## Phase 1 - Get the code

The code is on branch `claude/amazon-product-hunter-uae-y4onyp` of `ikhanai777/Amzphunt`.

```bash
git clone -b claude/amazon-product-hunter-uae-y4onyp https://github.com/ikhanai777/Amzphunt.git ~/Amzphunt
cd ~/Amzphunt
```

If the repo is private and cloning asks for credentials, ask the user to either run `gh auth login`
(GitHub CLI) or give you a GitHub personal access token with `repo:read`, then clone with
`https://<TOKEN>@github.com/ikhanai777/Amzphunt.git`. **Never print the token or write it to a file.**
If the branch has since been merged, clone `main` instead (drop `-b ...`).

**Check:** `ls ~/Amzphunt` shows `amzphunt/ scripts/ README.md HERMES_DEPLOY.md`.

## Phase 2 - Install and verify

```bash
cd ~/Amzphunt
bash scripts/setup_local.sh
```

This creates `.venv`, installs the package, runs the test suite (29 tests), creates `settings.json`,
and makes one live search request to amazon.ae.

| Exit | Meaning | Action |
|---|---|---|
| 0 | Everything works, including live access | continue |
| 1 | Install or tests failed | read the output, fix it (usually a missing `python3-venv` or no internet), re-run |
| 2 | Installed fine, but the live request was blocked | wait 60 min and run `bash scripts/setup_local.sh`. If it is still blocked, see Phase 7 |

**Check:** the output ends with `==> live access OK` and `Setup complete.`

## Phase 3 - Install the Hermes skill

The skill (`.hermes/skills/amzphunt/SKILL.md`) tells you how to operate the tool, the safety rules and
the reporting format. Install it globally so scheduled jobs can load it from any directory:

```bash
mkdir -p ~/.hermes/skills/research
cp -r ~/Amzphunt/.hermes/skills/amzphunt ~/.hermes/skills/research/amzphunt
```

The repo also ships it as a project-local skill. Inside `~/Amzphunt` you can instead run
`hermes skills trust`. The global copy is still needed for cron jobs.

If the install path is not `~/Amzphunt`, edit the path in
`~/.hermes/skills/research/amzphunt/SKILL.md` to match.

**Check:** start a new session and ask "What skills do you have?", or run
`hermes chat --toolsets skills -q "What skills do you have?"`. `amzphunt` must be listed.
Hermes also needs the **terminal** toolset enabled (`hermes tools`).

## Phase 4 - First real hunt

Run the quick preset first (about 5 minutes, roughly 60 requests):

```bash
cd ~/Amzphunt && bash scripts/run_hunt.sh quick
```

Then the standard daily preset in the background (20-30 minutes, roughly 220 requests):

```bash
cd ~/Amzphunt && nohup bash scripts/run_hunt.sh daily > logs/first-daily.out 2>&1 &
```

Do not check on it more often than every 5 minutes (`tail -3 logs/first-daily.out`). When it finishes:

```bash
source .venv/bin/activate && amzphunt latest --top 5
```

Send the user the digest in the format the skill defines, plus the HTML report path
(`reports/hunt-*.html`) as a document.

**Check:** `ls reports/` shows `hunt-*.html/.csv/.json`, and the log line `Requests: {...}` shows
`'blocked'` well below `'network'`.

## Phase 5 - Schedule the daily hunt

Scheduled jobs are run by the Hermes gateway, so it must be running as a service:

```bash
hermes gateway setup      # only if messaging (e.g. Telegram) is not configured yet; the user must supply the bot token
hermes gateway install    # run the gateway as a background service
hermes cron status        # confirm the scheduler is ticking
```

Create the job. Use an off-peak local time and add a few minutes of offset, so requests do not land
exactly on the hour:

```bash
hermes cron create "every day at 6:40am" "Run the amzphunt daily hunt: cd ~/Amzphunt && bash scripts/run_hunt.sh daily. When it finishes, send me the digest from 'amzphunt latest --top 5' in the amzphunt skill's reporting format, NEW products first, and attach the newest reports/hunt-*.html as a document. If the hunt exits with code 3 or 4, do not retry: send one line explaining it (already running / blocked by Amazon)." --skill amzphunt
```

The job delivers to wherever it was created (`origin`) by default. To deliver to Telegram, create it
from the user's Telegram chat, or ask in natural language:
*"Every day at 6:40am run the amzphunt daily hunt and send me the digest on Telegram."*
Telegram delivery uses `TELEGRAM_HOME_CHANNEL`.

Optional, a weekly deep hunt on a different day:

```bash
hermes cron create "every friday at 5:20am" "Run the amzphunt deep hunt: cd ~/Amzphunt && bash scripts/run_hunt.sh deep. Send the top 10 from 'amzphunt latest --top 10' in the skill's reporting format with the HTML report attached." --skill amzphunt
```

Never schedule two hunts close together. A deep hunt takes up to 90 minutes, and the lock will refuse
the second one (exit 3).

**Check:** `hermes cron list` shows the job(s). Trigger one run now with `hermes cron run <job_id>` and
confirm the digest arrives in the user's chat.

## Phase 6 - Answering the user day to day

Use the skill's intent table. Common requests:

- *"Is a car sun shade a good product?"* → `amzphunt niche "car sun shade" --category automotive`
- *"Check this competitor: B0CQM4ZNPZ, my supplier quotes AED 14"* → `amzphunt product B0CQM4ZNPZ --cost 14`
- *"Profit if I sell at 79 and buy at 12?"* → `amzphunt profit --price 79 --cost 12 --category kitchen` (add `--weight`/`--dims` if known)
- *"Hunt pet and office products"* → `bash scripts/run_hunt.sh daily -c pet-products office-products`
- *"Only show strict winners"* / tune criteria → edit `~/Amzphunt/settings.json` **only when the user asks**
  (fields: price band, minimum monthly sales, maximum competitor reviews, weight, target margin/ROI,
  estimated cost-of-goods ratio, freight rates, PPC share).

Always state that sales and profit are estimates, and that fees should be checked in Seller Central.

## Phase 7 - If Amazon blocks this machine

Signs: exit code 4, `HTTP 503`, `captcha page`, or `no data (request failed or blocked)`.

1. Stop all scraping for at least 60 minutes. Never retry in a loop.
2. Meanwhile, `--offline` re-scores cached pages without any requests.
3. If blocks come back every day:
   - Slow down: add `--min-delay 4 --max-delay 9 --workers 1` to the hunt command (or to the cron prompt).
   - Browser fallback: `source .venv/bin/activate && pip install -e ".[browser]" && playwright install chromium`,
     then add `--browser`.
   - Residential proxies (the user must supply them): add `--proxy http://user:pass@host:port`, repeatable.
     **Never print proxy credentials in chat.**

## Updating

```bash
cd ~/Amzphunt && git pull && bash scripts/setup_local.sh --no-live
cp -r ~/Amzphunt/.hermes/skills/amzphunt ~/.hermes/skills/research/   # refresh the skill
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ensurepip is not available` / venv fails | `sudo apt-get install -y python3-venv` (ask the user first), delete `.venv`, re-run setup |
| `lxml` build fails | `pip install --upgrade pip wheel` inside `.venv`. On old distros: `sudo apt-get install -y libxml2-dev libxslt1-dev` |
| `amzphunt: command not found` | You forgot `source ~/Amzphunt/.venv/bin/activate` |
| Exit 3 "Another hunt is already running" | Wait. If you are sure nothing is running: `rm -rf ~/Amzphunt/.hunt.lock*` |
| Exit 4 / 503 / captcha | Phase 7 |
| Cron job never fires | `hermes gateway` is not running: `hermes gateway install`, then `hermes cron status` |
| Digest says "No reports found" | No hunt has completed yet. Check `ls ~/Amzphunt/logs` and the newest log |
| Disk filling up | `find ~/Amzphunt/.amzphunt_cache -mtime +7 -delete` and delete old `reports/`/`logs/` |
| Numbers look off after an Amazon redesign | Run `source .venv/bin/activate && pytest -q` (tests use fixtures and should still pass), then `amzphunt product <known ASIN>`. If fields come back empty, tell the user the parsers need an update. Do not patch them blindly |

## Success criteria (report these to the user when done)

- [ ] `scripts/setup_local.sh` exits 0 (29 tests pass, live access OK)
- [ ] `amzphunt` skill is listed in Hermes
- [ ] The first daily hunt produced `reports/hunt-*.html` and the digest was delivered
- [ ] The daily cron job exists and one manual `hermes cron run` delivered successfully
- [ ] The user was told: estimates only, check fees in Seller Central, get supplier quotes before ordering
