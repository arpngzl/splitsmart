"""
Central AI layer for SplitSmart.

Every AI feature here follows the same contract: try Claude if
ANTHROPIC_API_KEY is configured, and fall back to a deterministic
rule-based implementation on any failure (missing key, network error,
malformed response, timeout). Nothing in the app ever *requires* the AI
call to succeed — it only makes the experience sharper when it's there.
"""

import json
import os
import re
from datetime import datetime, timezone

MODEL = "claude-sonnet-5"


def _client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    except Exception:
        return None


def _ask(system: str, prompt: str, max_tokens: int = 400) -> str | None:
    client = _client()
    if not client:
        return None
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        return text or None
    except Exception:
        return None


# ---------------------------------------------------------------- tips ----

def spending_tips(facts: dict) -> tuple[list[str], bool]:
    text = _ask(
        "You are a spending-insights assistant inside a bill-splitting app called "
        "SplitSmart. Given JSON facts about a group's expenses, write 2-4 short, "
        "specific, friendly insights (max ~20 words each) a member would find "
        "genuinely useful. No generic advice, no markdown, no numbering — plain "
        "sentences, one per line.",
        json.dumps(facts),
        max_tokens=300,
    )
    if text:
        lines = [l.strip("-• ").strip() for l in text.splitlines() if l.strip()]
        if lines:
            return lines, True
    return _rule_based_tips(facts), False


def _rule_based_tips(facts: dict) -> list[str]:
    tips = []
    members = facts.get("members", [])
    if not any(m["paid_rupees"] > 0 for m in members):
        return ["Add your first expense to see spending insights here."]

    top_payer = max(members, key=lambda m: m["paid_rupees"])
    if top_payer["paid_rupees"] > 0:
        tips.append(f"{top_payer['name']} has fronted the most money so far — ₹{top_payer['paid_rupees']:.2f} across the group.")

    breakdown = facts.get("category_breakdown", [])
    if breakdown:
        top = breakdown[0]
        tips.append(f"{top['category'].capitalize()} is the biggest chunk of spending at {top['pct']}% of the total.")

    biggest_debtor = min(members, key=lambda m: m["paid_rupees"] - m["fair_share_rupees"], default=None)
    if biggest_debtor and biggest_debtor["paid_rupees"] - biggest_debtor["fair_share_rupees"] < -0.01:
        gap = biggest_debtor["fair_share_rupees"] - biggest_debtor["paid_rupees"]
        tips.append(f"{biggest_debtor['name']} has the largest outstanding share right now (₹{gap:.2f} owed).")

    count = facts.get("settlement_transaction_count", 0)
    if count:
        tips.append(f"Settling up only needs {count} payment{'s' if count != 1 else ''} — the minimum possible path.")
    else:
        tips.append("Everyone's balanced out — no payments needed right now. 🎉")
    return tips


# ------------------------------------------------------------- recap -----

def group_recap(facts: dict) -> tuple[str, bool]:
    text = _ask(
        "You write short, warm, slightly playful 'monthly recap' summaries for a "
        "bill-splitting app called SplitSmart. Given JSON facts about a group, write "
        "one punchy paragraph (max 60 words) recapping the group's spending like a "
        "friendly narrator. No markdown, no headers, just the paragraph.",
        json.dumps(facts),
        max_tokens=200,
    )
    if text:
        return text.strip(), True
    return _rule_based_recap(facts), False


def _rule_based_recap(facts: dict) -> str:
    total = facts.get("total_spent_rupees", 0)
    members = facts.get("members", [])
    breakdown = facts.get("category_breakdown", [])
    if total <= 0:
        return "No expenses logged yet — add one to kick off the story of this group's spending."
    top_payer = max(members, key=lambda m: m["paid_rupees"], default=None)
    top_cat = breakdown[0]["category"] if breakdown else "misc"
    txns = facts.get("settlement_transaction_count", 0)
    piece = f"{top_payer['name']} carried the group this round" if top_payer else "The group"
    settle_piece = "everyone's already square" if txns == 0 else f"it'll take just {txns} payment{'s' if txns != 1 else ''} to settle up"
    return f"₹{total:.0f} spent so far, mostly on {top_cat}. {piece}, and {settle_piece}. 🎉"


# ------------------------------------------------------------ chat -------

def chat_answer(question: str, facts: dict) -> tuple[str, bool]:
    text = _ask(
        "You are SplitSmart's in-app assistant. Answer the member's question about "
        "their group's shared expenses using ONLY the JSON facts provided. Be concise "
        "(max 3 sentences), friendly, and concrete with numbers in ₹. If the facts "
        "don't contain the answer, say so briefly. No markdown.",
        f"Facts: {json.dumps(facts)}\n\nQuestion: {question}",
        max_tokens=250,
    )
    if text:
        return text.strip(), True
    return _rule_based_chat(question, facts), False


def _rule_based_chat(question: str, facts: dict) -> str:
    q = question.lower()
    members = facts.get("members", [])
    if not members:
        return "Add some members and expenses first, then ask me anything about the group!"

    if "owe" in q or "debt" in q:
        debtor = min(members, key=lambda m: m["paid_rupees"] - m["fair_share_rupees"])
        gap = debtor["fair_share_rupees"] - debtor["paid_rupees"]
        if gap <= 0.01:
            return "Nobody owes anything right now — the group is fully settled up!"
        return f"{debtor['name']} currently owes the most, about ₹{gap:.2f} to the group."

    if "spend" in q and ("most" in q or "top" in q):
        top_payer = max(members, key=lambda m: m["paid_rupees"])
        return f"{top_payer['name']} has paid the most overall — ₹{top_payer['paid_rupees']:.2f} so far."

    if "total" in q:
        return f"The group has spent ₹{facts.get('total_spent_rupees', 0):.2f} in total."

    if "categor" in q:
        breakdown = facts.get("category_breakdown", [])
        if breakdown:
            top = breakdown[0]
            return f"{top['category'].capitalize()} leads at {top['pct']}% of total spending."
        return "No category data yet."

    if "transaction" in q or "settle" in q:
        n = facts.get("settlement_transaction_count", 0)
        return f"Just {n} payment{'s' if n != 1 else ''} needed to settle everyone up." if n else "Everyone's already settled — no payments needed."

    top_payer = max(members, key=lambda m: m["paid_rupees"])
    return f"Here's a quick snapshot: ₹{facts.get('total_spent_rupees', 0):.2f} spent total, {top_payer['name']} leading the payments."


# --------------------------------------------------------- smart parse ---

AMOUNT_RE = re.compile(r"(?:rs\.?|inr|₹)?\s*([0-9]+(?:[.,][0-9]{1,2})?)", re.IGNORECASE)


def smart_parse_expense(text: str, member_names: list[str]) -> tuple[dict, bool]:
    """Parse free text like 'Dinner 1200, I paid, split with Asha and Ravi'
    into a draft expense. Returns (draft, ai_powered)."""
    ai_draft = _ai_parse(text, member_names)
    if ai_draft:
        return ai_draft, True
    return _rule_parse(text, member_names), False


def _ai_parse(text: str, member_names: list[str]) -> dict | None:
    result = _ask(
        "Extract a structured expense from the member's free-text message for a "
        "bill-splitting app. Group members are: " + ", ".join(member_names) + ". "
        "Respond with ONLY raw JSON (no markdown fences) matching exactly: "
        '{"description": str, "amount_rupees": number, "paid_by": str or null, '
        '"split_among": [str] or null, "category": one of '
        '["food","groceries","travel","transport","shopping","entertainment","utilities","other"]}. '
        "paid_by and split_among must be names from the member list, or null if unclear.",
        text,
        max_tokens=250,
    )
    if not result:
        return None
    try:
        cleaned = result.strip().strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        data = json.loads(cleaned)
        if "amount_rupees" not in data or not data.get("description"):
            return None
        return data
    except Exception:
        return None


def _rule_parse(text: str, member_names: list[str]) -> dict:
    lowered = text.lower()
    amounts = AMOUNT_RE.findall(text)
    amount = 0.0
    if amounts:
        amount = float(max(amounts, key=lambda a: float(a.replace(",", ""))).replace(",", ""))

    paid_by = None
    for name in member_names:
        if re.search(rf"\b{re.escape(name.lower())}\b.{{0,15}}\bpaid\b", lowered) or \
           re.search(rf"\bpaid by\b.{{0,15}}\b{re.escape(name.lower())}\b", lowered):
            paid_by = name
            break
    if not paid_by and ("i paid" in lowered or lowered.startswith("i ")):
        paid_by = member_names[0] if member_names else None

    split_among = None
    split_match = re.search(r"split (?:between|among|with)\s+([a-z, &]+)", lowered)
    if split_match:
        chunk = split_match.group(1)
        found = [n for n in member_names if n.lower() in chunk]
        if found:
            split_among = found

    description = text
    if amounts:
        description = AMOUNT_RE.sub("", text, count=1).strip(" ,.-") or "Expense"
    description = re.sub(r"\b(paid by|split (between|among|with))\b.*", "", description, flags=re.IGNORECASE).strip(" ,.-")
    if not description:
        description = "Expense"

    return {
        "description": description[:80],
        "amount_rupees": amount,
        "paid_by": paid_by,
        "split_among": split_among,
        "category": None,
    }


# ------------------------------------------------------------ budget -----

def budget_alert(facts: dict) -> tuple[str, bool]:
    text = _ask(
        "You are a friendly budget-nudge assistant for a bill-splitting app. Given "
        "JSON facts about a group's monthly budget usage, write ONE short sentence "
        "(max 25 words) — encouraging if under budget, gently urgent if close to or "
        "over. No markdown.",
        json.dumps(facts),
        max_tokens=100,
    )
    if text:
        return text.strip(), True
    return _rule_budget_alert(facts), False


def _rule_budget_alert(facts: dict) -> str:
    pct = facts.get("pct_used", 0)
    if pct >= 100:
        return f"Whoa — the group has blown past its monthly budget ({pct}% used). Time to slow down!"
    if pct >= 80:
        return f"Heads up, {pct}% of the monthly budget is already used."
    if pct >= 50:
        return f"Halfway through — {pct}% of the monthly budget used so far."
    return f"Looking healthy — only {pct}% of the monthly budget used."
