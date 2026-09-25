"""Monthly unit-sales estimation for amazon.ae.

Sales follow a power law of Best Sellers Rank: ``sales = a * rank ** -b``.
Defaults are anchored on amazon.ae observations (the #1 product in Kitchen shows
"2K+ bought in past month", rank ~170 shows "200+", rank ~1000 "100+"). During a run
the estimator collects (BSR, "bought in past month") pairs that Amazon
publishes on product pages and refits ``a`` and ``b`` per category with a
log-log least-squares regression, so estimates self-calibrate to the live
market instead of relying on stale constants.
"""

from __future__ import annotations

import math
from collections import defaultdict

# (a, b) per amazon.ae top-level category name as shown in BSR text.
DEFAULT_CURVES: dict[str, tuple[float, float]] = {
    "kitchen": (3000.0, 0.50),
    "home": (2600.0, 0.50),
    "tools & home improvement": (1800.0, 0.50),
    "home improvement": (1800.0, 0.50),
    "sporting goods": (1800.0, 0.50),
    "sports": (1800.0, 0.50),
    "office products": (1600.0, 0.50),
    "pet supplies": (1700.0, 0.50),
    "automotive": (1500.0, 0.50),
    "baby products": (2200.0, 0.52),
    "baby": (2200.0, 0.52),
    "beauty": (4000.0, 0.55),
    "health": (3500.0, 0.55),
    "health & personal care": (3500.0, 0.55),
    "toys": (2000.0, 0.52),
    "toys & games": (2000.0, 0.52),
    "fashion": (2500.0, 0.50),
    "electronics": (3000.0, 0.55),
    "grocery": (4000.0, 0.55),
    "appliances": (1200.0, 0.50),
    "computers": (1500.0, 0.52),
    "mobile phones & communication products": (2500.0, 0.55),
    "books": (1500.0, 0.52),
    "videogames": (1000.0, 0.50),
}
FALLBACK_CURVE = (2000.0, 0.50)
# Sub-category ranks are much "shallower" than top-level ranks.
SUBCATEGORY_CURVE = (800.0, 0.60)


def _key(category: str) -> str:
    return category.strip().lower().replace("&amp;", "&")


class SalesEstimator:
    def __init__(self) -> None:
        self.curves: dict[str, tuple[float, float]] = dict(DEFAULT_CURVES)
        self.samples: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.calibrated: dict[str, int] = {}

    def add_sample(self, category: str, bsr: int | None, bought_past_month: int | None) -> None:
        """Record an observed (rank, monthly units) pair for calibration.

        Amazon rounds "bought in past month" down to buckets (50+, 100+,
        1K+...), so the midpoint of the bucket is a better estimate.
        """
        if not bsr or not bought_past_month or bsr <= 0:
            return
        self.samples[_key(category)].append((bsr, int(bought_past_month * 1.35)))

    def calibrate(self, min_samples: int = 4) -> dict[str, tuple[float, float]]:
        """Refit curves for categories with enough observations."""
        for cat, pts in self.samples.items():
            pts = [(r, u) for r, u in pts if r > 0 and u > 0]
            if len(pts) < min_samples or len({r for r, _ in pts}) < 3:
                continue
            xs = [math.log(r) for r, _ in pts]
            ys = [math.log(u) for _, u in pts]
            n = len(xs)
            mx, my = sum(xs) / n, sum(ys) / n
            sxx = sum((x - mx) ** 2 for x in xs)
            if sxx == 0:
                continue
            slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
            b = -slope
            if not 0.2 <= b <= 1.2:  # reject nonsensical fits
                continue
            a = math.exp(my + b * mx)
            prior_a, prior_b = self.curves.get(cat, FALLBACK_CURVE)
            # Blend with the prior; trust data more as samples grow.
            w = min(0.85, n / (n + 8))
            self.curves[cat] = (
                math.exp(w * math.log(a) + (1 - w) * math.log(prior_a)),
                w * b + (1 - w) * prior_b,
            )
            self.calibrated[cat] = n
        return self.curves

    def from_bsr(self, rank: int | None, category: str = "", subcategory: bool = False) -> int | None:
        if not rank or rank <= 0:
            return None
        a, b = SUBCATEGORY_CURVE if subcategory else self.curves.get(_key(category), FALLBACK_CURVE)
        return max(0, int(round(a * rank ** -b)))

    def estimate(
        self,
        bsr: list[tuple[int, str]] | None = None,
        bought_past_month: int | None = None,
        list_rank: int | None = None,
    ) -> int | None:
        """Best available estimate, combining every signal we have."""
        estimates: list[tuple[float, float]] = []  # (value, weight)
        if bsr:
            main_rank, main_cat = bsr[0]
            v = self.from_bsr(main_rank, main_cat)
            if v is not None:
                estimates.append((v, 2.0 if _key(main_cat) in self.calibrated else 1.2))
            for rank, cat in bsr[1:2]:
                v = self.from_bsr(rank, cat, subcategory=True)
                if v is not None:
                    estimates.append((v, 0.4))
        if bought_past_month:
            # Published by Amazon; the floor of a bucket, so scale to midpoint.
            estimates.append((bought_past_month * 1.35, 3.0))
        if not estimates and list_rank:
            v = self.from_bsr(list_rank, subcategory=True)
            if v is not None:
                estimates.append((v, 0.5))
        if not estimates:
            return None
        total_w = sum(w for _, w in estimates)
        # Weighted geometric mean: robust to one wildly off signal.
        log_mean = sum(math.log(max(v, 1)) * w for v, w in estimates) / total_w
        return int(round(math.exp(log_mean)))
