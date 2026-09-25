"""SQLite history of every scan, so repeated runs reveal trends.

Run the hunter daily or weekly: products whose BSR keeps improving are
rising niches; products that fade are fads.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .models import Opportunity

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    asin TEXT NOT NULL,
    ts REAL NOT NULL,
    bsr INTEGER,
    price REAL,
    reviews INTEGER,
    rating REAL,
    bought_past_month INTEGER,
    est_monthly_sales INTEGER,
    score REAL,
    verdict TEXT,
    keyword TEXT,
    title TEXT
);
CREATE INDEX IF NOT EXISTS idx_snap_asin ON snapshots(asin, ts);
"""


class History:
    def __init__(self, path: str | Path = "amzphunt_history.db"):
        self.conn = sqlite3.connect(str(path))
        self.conn.executescript(SCHEMA)

    def previous_bsr(self, asin: str, older_than_hours: float = 12) -> int | None:
        row = self.conn.execute(
            "SELECT bsr FROM snapshots WHERE asin=? AND bsr IS NOT NULL AND ts < ? ORDER BY ts DESC LIMIT 1",
            (asin, time.time() - older_than_hours * 3600),
        ).fetchone()
        return row[0] if row else None

    def trend(self, asin: str, current_bsr: int | None) -> float | None:
        """Relative BSR improvement vs. the last scan (+0.3 = rank 30% better)."""
        prev = self.previous_bsr(asin)
        if not prev or not current_bsr:
            return None
        return (prev - current_bsr) / prev

    def record(self, opps: list[Opportunity]) -> None:
        now = time.time()
        rows = []
        for o in opps:
            d = o.detail
            rows.append(
                (
                    o.asin,
                    now,
                    d.main_bsr if d else None,
                    o.price,
                    (d.reviews if d else None) or (o.listing.reviews if o.listing else None),
                    (d.rating if d else None) or (o.listing.rating if o.listing else None),
                    (d.bought_past_month if d else None) or (o.listing.bought_past_month if o.listing else None),
                    o.est_monthly_sales,
                    o.score,
                    o.verdict,
                    o.keyword,
                    o.title[:300],
                )
            )
        self.conn.executemany("INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
