"""
Smart categorization + spending-shape helpers.

Deterministic and dependency-free by design: `categorize()` runs on every
expense synchronously, so the app behaves identically offline, in tests,
and in prod. Natural-language *generation* (tips, recaps, chat) lives in
`app/ai.py`, which layers an optional Claude call on top of rule-based
fallbacks.
"""

from collections import defaultdict
from datetime import datetime, timezone

CATEGORIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "food": ("🍔", (
        "food", "dinner", "lunch", "breakfast", "restaurant", "cafe", "coffee",
        "pizza", "snack", "brunch", "burger", "dine", "meal", "eat", "brewery",
        "bar", "drinks", "buffet",
    )),
    "groceries": ("🛒", (
        "grocery", "groceries", "supermarket", "vegetables", "mart", "kirana",
    )),
    "travel": ("✈️", (
        "flight", "airbnb", "hotel", "stay", "resort", "hostel", "booking",
        "train", "airport", "visa", "trip",
    )),
    "transport": ("🚕", (
        "cab", "taxi", "uber", "ola", "fuel", "petrol", "diesel", "toll",
        "parking", "bus", "metro", "rickshaw", "rental car", "car rental",
    )),
    "shopping": ("🛍️", (
        "shopping", "clothes", "clothing", "souvenir", "gift", "mall", "store",
    )),
    "entertainment": ("🎉", (
        "movie", "party", "club", "ticket", "concert", "game", "bowling",
        "karaoke", "museum", "show",
    )),
    "utilities": ("💡", (
        "electricity", "wifi", "internet", "water bill", "rent", "recharge",
        "sim",
    )),
}

DEFAULT_CATEGORY = "other"
DEFAULT_EMOJI = "💸"


def categorize(description: str) -> str:
    text = description.lower()
    for category, (_emoji, keywords) in CATEGORIES.items():
        if any(kw in text for kw in keywords):
            return category
    return DEFAULT_CATEGORY


def emoji_for(category: str) -> str:
    return CATEGORIES.get(category, (DEFAULT_EMOJI, ()))[0]


def category_breakdown(expenses) -> list[dict]:
    totals: dict[str, int] = defaultdict(int)
    for e in expenses:
        totals[e.category] += e.amount

    grand_total = sum(totals.values()) or 1
    rows = [
        {
            "category": cat,
            "emoji": emoji_for(cat),
            "amount_minor": amt,
            "pct": round(amt / grand_total * 100),
        }
        for cat, amt in totals.items()
    ]
    rows.sort(key=lambda r: r["amount_minor"], reverse=True)
    return rows


def weekly_trend(expenses, weeks: int = 8) -> list[dict]:
    """Bucket spending into the last N ISO weeks for a sparkline/bar trend chart."""
    if not expenses:
        return []
    buckets: dict[str, int] = defaultdict(int)
    for e in expenses:
        dt = e.created_at or datetime.now(timezone.utc)
        iso_year, iso_week, _ = dt.isocalendar()
        key = f"{iso_year}-W{iso_week:02d}"
        buckets[key] += e.amount

    ordered_keys = sorted(buckets.keys())[-weeks:]
    return [{"label": k.split("-W")[1] and f"W{k.split('-W')[1]}", "amount_minor": buckets[k]} for k in ordered_keys]
