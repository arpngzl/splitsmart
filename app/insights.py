"""
Smart categorization + spending insights.

Two layers, on purpose:

1. `categorize()` is a fast, deterministic keyword classifier. It runs on
   every expense, synchronously, with zero external dependencies — so the
   app works exactly the same offline, in tests, and in prod.

2. `build_insights()` produces the natural-language "tips" panel. It always
   has a solid rule-based fallback (`_rule_based_tips`). If the deployment
   sets an ANTHROPIC_API_KEY env var, it *additionally* asks Claude to turn
   the same numbers into sharper, more specific observations. If that call
   fails or isn't configured, callers silently get the rule-based tips —
   nothing about the app depends on the AI call succeeding.
"""

import os
from collections import defaultdict

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
    """Return a category key for a free-text expense description."""
    text = description.lower()
    for category, (_emoji, keywords) in CATEGORIES.items():
        if any(kw in text for kw in keywords):
            return category
    return DEFAULT_CATEGORY


def emoji_for(category: str) -> str:
    return CATEGORIES.get(category, (DEFAULT_EMOJI, ()))[0]


def category_breakdown(expenses) -> list[dict]:
    """expenses: iterable of objects with .category and .amount (minor units)."""
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


def _rule_based_tips(group_name, members_by_id, paid, owed, transactions, breakdown) -> list[str]:
    tips: list[str] = []

    if not any(paid.values()):
        return ["Add your first expense to see spending insights here."]

    # Biggest spender (paid the most out of pocket)
    top_payer_id = max(paid, key=paid.get)
    if paid[top_payer_id] > 0:
        tips.append(
            f"{members_by_id[top_payer_id].name} has fronted the most money so far — "
            f"₹{paid[top_payer_id] / 100:.2f} across the group's expenses."
        )

    # Top category
    if breakdown:
        top = breakdown[0]
        tips.append(
            f"{top['emoji']} {top['category'].capitalize()} is the biggest chunk of spending "
            f"at {top['pct']}% of the total."
        )

    # Biggest single owed gap
    if owed:
        top_ower_id = max(owed, key=owed.get)
        net = paid.get(top_ower_id, 0) - owed[top_ower_id]
        if net < 0:
            tips.append(
                f"{members_by_id[top_ower_id].name} has the largest outstanding share right now "
                f"(₹{abs(net) / 100:.2f} owed to the group)."
            )

    # Settlement efficiency
    if transactions:
        tips.append(
            f"Settling up only needs {len(transactions)} payment"
            f"{'s' if len(transactions) != 1 else ''} — SplitSmart already found the minimum path."
        )
    else:
        tips.append("Everyone's balanced out — no payments needed right now. 🎉")

    return tips


def _ai_tips(group_name, members_by_id, paid, owed, transactions, breakdown) -> list[str] | None:
    """Best-effort: ask Claude for sharper observations. Returns None on any
    failure so the caller falls back to rule-based tips without surfacing
    an error to the user."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import anthropic
    except ImportError:
        return None

    facts = {
        "group": group_name,
        "members": [
            {
                "name": m.name,
                "paid_rupees": round(paid.get(mid, 0) / 100, 2),
                "fair_share_rupees": round(owed.get(mid, 0) / 100, 2),
            }
            for mid, m in members_by_id.items()
        ],
        "category_breakdown": [
            {"category": r["category"], "pct": r["pct"], "amount_rupees": round(r["amount_minor"] / 100, 2)}
            for r in breakdown
        ],
        "settlement_transaction_count": len(transactions),
    }

    prompt = (
        "You are a spending-insights assistant inside a bill-splitting app called SplitSmart. "
        "Given this JSON of a group's expenses, write 2-4 short, specific, friendly insights "
        "(max ~20 words each) a member would find genuinely useful. No generic advice, no "
        "markdown, no numbering — just plain sentences, one per line.\n\n"
        f"{facts}"
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        lines = [line.strip("-• ").strip() for line in text.strip().splitlines() if line.strip()]
        return lines or None
    except Exception:
        return None


def build_insights(group_name, members_by_id, paid, owed, transactions, expenses) -> dict:
    breakdown = category_breakdown(expenses)
    ai_tips = _ai_tips(group_name, members_by_id, paid, owed, transactions, breakdown)
    tips = ai_tips if ai_tips else _rule_based_tips(group_name, members_by_id, paid, owed, transactions, breakdown)

    return {
        "category_breakdown": breakdown,
        "tips": tips,
        "ai_powered": ai_tips is not None,
    }
