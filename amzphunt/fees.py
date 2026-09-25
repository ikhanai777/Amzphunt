"""UAE unit economics: referral + FBA fees, VAT, landed cost, profit, ROI."""

from __future__ import annotations

from .config import (
    CUSTOMS_DUTY_RATE,
    DEFAULT_REFERRAL_FEE,
    ENVELOPE_LIMITS,
    FBA_EXTRA_PER_KG,
    FBA_FEES,
    MIN_REFERRAL_FEE,
    MONTHLY_STORAGE_PER_CBM,
    REFERRAL_FEES,
    STANDARD_LIMITS,
    VAT_RATE,
    Settings,
)
from .models import Economics

# Rough dimensions (cm) and weight (kg) by category when a listing lacks them.
DEFAULT_DIMS = (25.0, 18.0, 8.0)
DEFAULT_WEIGHT = 0.6


def size_tier(dims: tuple[float, float, float] | None, weight: float | None) -> str:
    l, m, s = dims or DEFAULT_DIMS
    w = weight if weight is not None else DEFAULT_WEIGHT
    el, em, es, ew = ENVELOPE_LIMITS
    if l <= el and m <= em and s <= es and w <= ew:
        return "envelope"
    sl, sm, ss, sw = STANDARD_LIMITS
    if l <= sl and m <= sm and s <= ss and w <= sw:
        return "standard"
    return "oversize"


def shipping_weight(dims: tuple[float, float, float] | None, weight: float | None) -> float:
    """Greater of actual and volumetric weight (L*W*H/5000), plus packaging."""
    l, m, s = dims or DEFAULT_DIMS
    actual = (weight if weight is not None else DEFAULT_WEIGHT) + 0.05
    return max(actual, l * m * s / 5000)


def fba_fee(dims: tuple[float, float, float] | None, weight: float | None) -> tuple[float, str]:
    tier = size_tier(dims, weight)
    w = shipping_weight(dims, weight)
    steps = FBA_FEES[tier]
    for max_w, fee in steps:
        if w <= max_w:
            return fee, tier
    last_w, last_fee = steps[-1]
    extra = max(0.0, w - last_w)
    return last_fee + FBA_EXTRA_PER_KG * -(-extra // 1), tier


def referral_fee(price: float, category: str) -> float:
    rate = REFERRAL_FEES.get(category, DEFAULT_REFERRAL_FEE)
    return max(MIN_REFERRAL_FEE, price * rate)


def unit_economics(
    price: float,
    category: str = "",
    dims: tuple[float, float, float] | None = None,
    weight: float | None = None,
    settings: Settings | None = None,
    unit_cost: float | None = None,
    months_in_storage: float = 1.5,
) -> Economics:
    """Per-unit profit for an FBA private-label seller on amazon.ae.

    ``unit_cost`` is the ex-works supplier price in AED; if unknown it is
    estimated as ``settings.cogs_ratio`` of the sale price, which is a typical
    target for Chinese-sourced private label.
    """
    st = settings or Settings()
    net_price = price / (1 + VAT_RATE)  # seller remits the 5% VAT
    ref = referral_fee(price, category)
    fba, tier = fba_fee(dims, weight)
    l, m, s = dims or DEFAULT_DIMS
    storage = (l * m * s) / 1_000_000 * MONTHLY_STORAGE_PER_CBM * months_in_storage
    cogs = unit_cost if unit_cost is not None else price * st.cogs_ratio
    # Sea LCL is billed on the greater of weight and volume (W/M).
    cbm = (l * m * s) / 1_000_000
    freight = max(((weight if weight is not None else DEFAULT_WEIGHT) + 0.05) * st.freight_per_kg, cbm * st.freight_per_cbm)
    duty = (cogs + freight) * CUSTOMS_DUTY_RATE
    landed = cogs + freight + duty
    ppc = price * st.ppc_ratio
    # Referral & FBA fees carry 5% VAT that is recoverable for a VAT-registered
    # seller; we conservatively treat it as a cost for small sellers.
    fees_vat = (ref + fba + storage) * VAT_RATE
    profit = net_price - ref - fba - storage - fees_vat - landed - ppc
    return Economics(
        price=round(price, 2),
        net_price=round(net_price, 2),
        referral_fee=round(ref, 2),
        fba_fee=round(fba, 2),
        storage_fee=round(storage, 2),
        landed_cost=round(landed, 2),
        ppc_cost=round(ppc, 2),
        profit=round(profit, 2),
        margin=round(profit / price, 3) if price else 0.0,
        roi=round(profit / landed, 3) if landed else 0.0,
        size_tier=tier,
        assumptions={
            "unit_cost": round(cogs, 2),
            "unit_cost_estimated": unit_cost is None,
            "freight": round(freight, 2),
            "cbm": round(cbm, 5),
            "duty": round(duty, 2),
            "fees_vat": round(fees_vat, 2),
            "shipping_weight_kg": round(shipping_weight(dims, weight), 3),
            "dims_estimated": dims is None,
            "weight_estimated": weight is None,
        },
    )


def max_unit_cost(price: float, category: str, dims=None, weight=None, settings: Settings | None = None) -> float:
    """Highest supplier price (AED) that still hits the target ROI and margin."""
    st = settings or Settings()
    lo, hi = 0.0, price
    for _ in range(40):
        mid = (lo + hi) / 2
        e = unit_economics(price, category, dims, weight, st, unit_cost=mid)
        if e.roi >= st.min_roi and e.margin >= st.min_margin:
            lo = mid
        else:
            hi = mid
    return round(lo, 2)
