"""Marketplace constants and tunable thresholds for amazon.ae.

Fee tables are estimates based on public amazon.ae fee schedules. Amazon
revises them regularly, so verify against Seller Central before committing
capital. Every value can be overridden through a JSON settings file
(see ``Settings.load``).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

BASE_URL = "https://www.amazon.ae"
CURRENCY = "AED"
VAT_RATE = 0.05  # UAE VAT, included in consumer prices
CUSTOMS_DUTY_RATE = 0.05  # GCC common external tariff on CIF value

# Top-level best seller categories on amazon.ae (slug -> display name).
CATEGORIES: dict[str, str] = {
    "amazon-devices": "Amazon Devices & Accessories",
    "appliances": "Appliances",
    "automotive": "Automotive",
    "baby": "Baby Products",
    "beauty": "Beauty",
    "books": "Books",
    "computers": "Computers",
    "electronics": "Electronics",
    "fashion": "Fashion",
    "gift-cards": "Gift Cards",
    "grocery": "Grocery",
    "health": "Health",
    "home": "Home",
    "kitchen": "Kitchen",
    "mobile-phones": "Mobile Phones & Communication Products",
    "office-products": "Office Products",
    "pet-products": "Pet Supplies",
    "sports-goods": "Sporting Goods",
    "home-improvement": "Tools & Home Improvement",
    "toys": "Toys",
    "videogames": "Videogames",
}

# Categories that are ungated, private-label friendly and forgiving for a
# first product in the UAE. Used when the user does not pick categories.
NEW_SELLER_CATEGORIES = [
    "kitchen",
    "home",
    "home-improvement",
    "sports-goods",
    "office-products",
    "pet-products",
    "automotive",
    "baby",
]

# Categories a new seller should normally stay away from: gated, need
# regulatory registration (MOHAP / Dubai Municipality / ECAS), dominated by
# brands/Amazon, or low margin.
AVOID_CATEGORIES = {
    "amazon-devices": "Amazon's own products",
    "books": "Low margin, dominated by publishers",
    "gift-cards": "Not sellable by third parties",
    "grocery": "Gated; food requires municipality registration",
    "health": "Supplements/medical need MOHAP approval",
    "mobile-phones": "Brand dominated, TDRA approvals, high returns",
    "videogames": "Brand dominated, licensing",
    "computers": "Brand dominated, thin margins",
    "electronics": "ECAS/ESMA certification, high returns",
}

# Referral fee (% of VAT-inclusive sale price) per top-level category.
REFERRAL_FEES: dict[str, float] = {
    "amazon-devices": 0.15,
    "appliances": 0.10,
    "automotive": 0.12,
    "baby": 0.10,
    "beauty": 0.10,
    "books": 0.15,
    "computers": 0.08,
    "electronics": 0.08,
    "fashion": 0.15,
    "grocery": 0.08,
    "health": 0.10,
    "home": 0.13,
    "kitchen": 0.12,
    "mobile-phones": 0.06,
    "office-products": 0.12,
    "pet-products": 0.12,
    "sports-goods": 0.13,
    "home-improvement": 0.12,
    "toys": 0.12,
    "videogames": 0.10,
}
DEFAULT_REFERRAL_FEE = 0.13
MIN_REFERRAL_FEE = 1.0  # AED

# FBA fulfilment fee (AED per unit) by size tier and shipping weight (kg).
# Each tier is a list of (max_weight_kg, fee). Weight above the last step
# pays the last fee plus ``FBA_EXTRA_PER_KG`` for every extra kg.
FBA_FEES: dict[str, list[tuple[float, float]]] = {
    "envelope": [(0.1, 6.5), (0.25, 7.0), (0.5, 7.5)],
    "standard": [(0.25, 8.0), (0.5, 8.5), (1.0, 9.5), (1.5, 10.5), (2.0, 11.5), (3.0, 13.0), (5.0, 15.5), (12.0, 21.0)],
    "oversize": [(1.0, 16.0), (5.0, 22.0), (10.0, 28.0), (20.0, 36.0), (30.0, 46.0)],
}
FBA_EXTRA_PER_KG = 1.5
MONTHLY_STORAGE_PER_CBM = 70.0  # AED per cubic metre per month

# Size tier limits in cm (longest, median, shortest) and kg.
ENVELOPE_LIMITS = (33.0, 23.0, 2.5, 0.5)
STANDARD_LIMITS = (45.0, 34.0, 26.0, 12.0)

# Keywords that indicate gated, hazmat, regulated, fragile or IP-risky goods.
RISK_KEYWORDS: dict[str, str] = {
    "battery": "hazmat (batteries)",
    "lithium": "hazmat (batteries)",
    "rechargeable": "hazmat (batteries)",
    "power bank": "hazmat (batteries)",
    "aerosol": "hazmat",
    "perfume": "hazmat + gated (fragrance)",
    "eau de": "hazmat + gated (fragrance)",
    "oud": "gated (fragrance)",
    "bakhoor": "gated (fragrance)",
    "spray": "possible hazmat",
    "flammable": "hazmat",
    "lighter": "hazmat",
    "supplement": "MOHAP registration",
    "vitamin": "MOHAP registration",
    "capsule": "MOHAP registration",
    "medical": "MOHAP registration",
    "cream": "cosmetic registration",
    "serum": "cosmetic registration",
    "shampoo": "cosmetic registration",
    "lotion": "cosmetic registration",
    "snack": "food registration",
    "baby food": "food registration",
    "pet food": "food registration",
    "dog food": "food registration",
    "cat food": "food registration",
    "bird food": "food registration",
    "parrot food": "food registration",
    "fish food": "food registration",
    "probiotic": "MOHAP/MOCCAE registration",
    "probiotics": "MOHAP/MOCCAE registration",
    "incense": "gated (fragrance)",
    "sourdough": "food registration",
    "baguette french": "food registration",
    "mince": "food registration",
    "grassfed": "food registration",
    "coffee beans": "food registration",
    "tea bags": "food registration",
    "glass": "fragile",
    "ceramic": "fragile",
    "mirror": "fragile",
    "knife": "restricted (blades)",
    "sword": "restricted (blades)",
    "drone": "restricted (GCAA)",
    "laser": "restricted",
    "e-cigarette": "prohibited",
    "vape": "prohibited",
    "shisha": "restricted",
    "hookah": "restricted",
    "disney": "IP / licensed brand",
    "marvel": "IP / licensed brand",
    "pokemon": "IP / licensed brand",
    "lego": "IP / licensed brand",
    "iphone": "IP / brand accessory, saturated",
    "samsung": "IP / brand accessory, saturated",
    "apple": "IP / brand accessory, saturated",
    "baby formula": "gated",
    "car seat": "safety certification",
    "helmet": "safety certification",
    "electric": "ECAS/G-mark certification",
    "charger": "ECAS/G-mark certification",
    "adapter": "ECAS/G-mark certification",
}

# Brands that dominate their niches; competing head-on is a poor first move.
BIG_BRANDS = {
    "amazon", "amazon basics", "amazonbasics", "apple", "samsung", "xiaomi", "anker",
    "philips", "tefal", "braun", "dyson", "sony", "lg", "bosch", "black+decker",
    "black & decker", "nike", "adidas", "puma", "under armour", "lego", "mattel",
    "hasbro", "pampers", "huggies", "johnson's", "nivea", "loreal", "l'oreal",
    "maybelline", "gillette", "oral-b", "colgate", "dettol", "fine", "tupperware",
    "stanley", "logitech", "hp", "canon", "epson", "ninja", "kenwood", "tefal",
    "royal canin", "whiskas", "pedigree", "purina", "castrol", "mobil", "bic",
    "sharpie", "pilot", "faber-castell", "3m", "scotch", "tp-link", "jbl",
    "nescafe", "lipton", "nestle", "garnier", "dove", "vaseline", "karcher",
}

# UAE retail calendar: month -> keywords whose demand spikes around then.
SEASONAL_KEYWORDS: dict[int, list[str]] = {
    1: ["fitness", "gym", "yoga", "planner", "organizer", "camping", "tent", "bbq"],
    2: ["ramadan", "lantern", "iftar", "prayer", "dates", "camping", "bbq", "tent"],
    3: ["ramadan", "eid", "lantern", "prayer mat", "iftar", "serving", "abaya", "kaftan", "gift"],
    4: ["eid", "gift", "kids", "serving", "summer", "cooling"],
    5: ["summer", "sunshade", "cooling", "fan", "sun", "swim", "water bottle"],
    6: ["summer", "sunshade", "cooling", "fan", "swim", "travel", "luggage", "eid al adha"],
    7: ["summer", "cooling", "fan", "sunshade", "swim", "travel", "luggage", "car shade"],
    8: ["back to school", "school", "lunch box", "backpack", "stationery", "water bottle", "pencil"],
    9: ["school", "lunch box", "stationery", "desk", "organizer", "planner"],
    10: ["diwali", "halloween", "camping", "outdoor", "bbq", "decor", "lights"],
    11: ["white friday", "national day", "camping", "tent", "outdoor", "gift", "christmas", "bbq"],
    12: ["christmas", "gift", "new year", "camping", "tent", "bbq", "fitness", "outdoor"],
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:129.0) Gecko/20100101 Firefox/129.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.5; rv:129.0) Gecko/20100101 Firefox/129.0",
]


@dataclass
class Settings:
    """Thresholds that define a 'winning' product for a new UAE seller."""

    # Price sweet spot (AED, VAT inclusive). Below it FBA fees eat the margin,
    # above it inventory and PPC get expensive for a first launch.
    min_price: float = 35.0
    max_price: float = 250.0
    ideal_price_low: float = 50.0
    ideal_price_high: float = 180.0

    # Demand: estimated monthly unit sales of the product itself.
    min_monthly_sales: int = 60
    ideal_monthly_sales: int = 300

    # Competition on page 1 of the niche search.
    max_median_reviews: int = 400
    ideal_median_reviews: int = 80
    max_single_listing_reviews: int = 3000

    # Logistics.
    max_weight_kg: float = 2.0
    ideal_weight_kg: float = 0.8

    # Unit economics.
    cogs_ratio: float = 0.22  # sourcing cost as share of sale price when unknown
    # China -> Jebel Ali sea LCL, door to FBA incl. clearance; billed on the
    # greater of weight and volume.
    freight_per_kg: float = 6.0  # AED/kg
    freight_per_cbm: float = 650.0  # AED per cubic metre
    ppc_ratio: float = 0.10  # share of revenue spent on ads in the launch phase
    min_margin: float = 0.20
    min_roi: float = 0.60

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def load(cls, path: str | Path | None) -> "Settings":
        if not path:
            return cls()
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class FetchSettings:
    min_delay: float = 2.0
    max_delay: float = 5.0
    retries: int = 4
    timeout: float = 25.0
    cache_dir: str = ".amzphunt_cache"
    cache_ttl_hours: float = 12.0
    offline: bool = False  # only read from cache, never hit the network
    proxies: list[str] = field(default_factory=list)
    use_browser_fallback: bool = False  # Playwright when blocked by captcha
