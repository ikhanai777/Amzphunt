"""Polite, resilient HTTP fetcher for amazon.ae.

Features: rotating browser fingerprints, UAE locale headers, jittered rate
limiting, exponential backoff, captcha/block detection, proxy rotation, an
on-disk cache (so re-runs and offline analysis are free) and an optional
headless-browser fallback when Amazon serves a captcha.
"""

from __future__ import annotations

import hashlib
import logging
import random
import threading
import time
from pathlib import Path
from urllib.parse import urljoin

import requests

from .config import BASE_URL, USER_AGENTS, FetchSettings

log = logging.getLogger(__name__)

BLOCK_MARKERS = (
    "Enter the characters you see below",
    "/errors/validateCaptcha",
    "api-services-support@amazon.com",
    "Sorry, we just need to make sure you're not a robot",
    "To discuss automated access to Amazon data please contact",
)


class BlockedError(RuntimeError):
    """Amazon returned a captcha or robot check."""


class FetchError(RuntimeError):
    pass


def is_blocked(html: str) -> bool:
    head = html[:20000]
    return any(marker in head for marker in BLOCK_MARKERS)


class Fetcher:
    def __init__(self, settings: FetchSettings | None = None):
        self.settings = settings or FetchSettings()
        self.cache_dir = Path(self.settings.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._cooldown_until = 0.0  # shared by all workers after a block
        self._session = self._new_session()
        self._proxy_index = 0
        self.stats = {"network": 0, "cache": 0, "blocked": 0, "errors": 0}

    # -- session / identity -------------------------------------------------

    def _new_session(self) -> requests.Session:
        s = requests.Session()
        ua = random.choice(USER_AGENTS)
        s.headers.update(
            {
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-AE,en-GB;q=0.9,en;q=0.8,ar;q=0.6",
                "Accept-Encoding": "gzip, deflate",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Connection": "keep-alive",
            }
        )
        # English UI + AED currency; Dubai delivery location for accurate offers.
        s.cookies.set("i18n-prefs", "AED", domain=".amazon.ae")
        s.cookies.set("lc-acbae", "en_AE", domain=".amazon.ae")
        return s

    def _rotate_identity(self) -> None:
        self._session = self._new_session()
        if self.settings.proxies:
            self._proxy_index = (self._proxy_index + 1) % len(self.settings.proxies)

    def _proxy(self) -> dict | None:
        if not self.settings.proxies:
            return None
        p = self.settings.proxies[self._proxy_index]
        return {"http": p, "https": p}

    # -- cache --------------------------------------------------------------

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".html")

    def _read_cache(self, url: str, ignore_ttl: bool = False) -> str | None:
        path = self._cache_path(url)
        if not path.exists():
            return None
        age_h = (time.time() - path.stat().st_mtime) / 3600
        if not ignore_ttl and age_h > self.settings.cache_ttl_hours:
            return None
        return path.read_text(encoding="utf-8", errors="replace")

    def _write_cache(self, url: str, html: str) -> None:
        self._cache_path(url).write_text(html, encoding="utf-8")

    # -- fetching -----------------------------------------------------------

    def _throttle(self) -> None:
        with self._lock:
            now = time.time()
            if now < self._cooldown_until:
                time.sleep(self._cooldown_until - now)
            wait = random.uniform(self.settings.min_delay, self.settings.max_delay)
            elapsed = time.time() - self._last_request
            if elapsed < wait:
                time.sleep(wait - elapsed)
            self._last_request = time.time()

    def _cool_down(self, seconds: float) -> None:
        """Pause every worker, not just this one: Amazon blocks per client."""
        with self._lock:
            self._cooldown_until = max(self._cooldown_until, time.time() + seconds)

    def get(self, url: str, use_cache: bool = True) -> str:
        url = urljoin(BASE_URL, url)
        if use_cache or self.settings.offline:
            cached = self._read_cache(url, ignore_ttl=self.settings.offline)
            if cached is not None:
                self.stats["cache"] += 1
                return cached
        if self.settings.offline:
            raise FetchError(f"offline mode and no cached copy of {url}")

        last_exc: Exception | None = None
        for attempt in range(self.settings.retries):
            self._throttle()
            try:
                resp = self._session.get(url, timeout=self.settings.timeout, proxies=self._proxy())
                self.stats["network"] += 1
                if resp.status_code == 404:
                    raise FetchError(f"404 for {url}")
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise BlockedError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                html = resp.text
                if is_blocked(html):
                    raise BlockedError("captcha page")
                self._write_cache(url, html)
                return html
            except FetchError:
                raise
            except (BlockedError, requests.RequestException) as exc:
                last_exc = exc
                if isinstance(exc, BlockedError):
                    self.stats["blocked"] += 1
                else:
                    self.stats["errors"] += 1
                backoff = (2 ** attempt) * 4 + random.uniform(0, 4)
                log.info("fetch %s failed (%s); retry %d in %.0fs", url, exc, attempt + 1, backoff)
                self._rotate_identity()
                self._cool_down(backoff)

        if self.settings.use_browser_fallback:
            html = self._browser_get(url)
            if html:
                self._write_cache(url, html)
                return html
        raise FetchError(f"giving up on {url}: {last_exc}")

    def _browser_get(self, url: str) -> str | None:
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except ImportError:
            log.warning("playwright not installed; pip install playwright to enable browser fallback")
            return None
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(user_agent=random.choice(USER_AGENTS), locale="en-AE")
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(2500)
                html = page.content()
                browser.close()
            return None if is_blocked(html) else html
        except Exception as exc:  # noqa: BLE001 - fallback must never crash a run
            log.warning("browser fallback failed for %s: %s", url, exc)
            return None
