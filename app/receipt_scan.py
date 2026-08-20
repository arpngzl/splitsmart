"""
Receipt scanning via Claude's vision.

Unlike `insights.py`, there's no rule-based fallback here — reading an
arbitrary photo of a bill genuinely needs a vision model, so if
ANTHROPIC_API_KEY isn't configured the caller gets a clear `None` and the
API layer turns that into an honest error instead of pretending to work.
"""

import json
import os

from app import insights


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.split("\n")
    lines = lines[1:]  # drop opening ``` or ```json
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def scan_receipt(image_base64: str, media_type: str) -> dict | None:
    """Best-effort: ask Claude to read a receipt photo and pull out an
    expense description + total amount. Returns None on any failure
    (no key configured, bad image, model couldn't find a total, etc.) so
    the caller can surface one clean error message."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import anthropic
    except ImportError:
        return None

    prompt = (
        "You're reading a photo of a receipt or bill for a bill-splitting app. "
        "Respond with ONLY a JSON object, no markdown fences, no preamble, with keys:\n"
        '"description": a short human-friendly name for the expense (prefer the '
        "merchant/restaurant name, e.g. \"Cafe Coffee Day\" or \"Big Bazaar\"),\n"
        '"amount_rupees": the final grand total actually paid, as a plain number '
        "with no currency symbol (use the total after tax/tip, not a subtotal),\n"
        '"merchant": the store or restaurant name if visible, else null.\n'
        "If you can't confidently find a total amount on the receipt, set "
        '"amount_rupees" to null.'
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_base64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        data = json.loads(_strip_code_fence(text))

        amount = data.get("amount_rupees")
        if amount is None:
            return None
        amount = round(float(amount), 2)
        if amount <= 0:
            return None

        merchant = data.get("merchant") or None
        description = (data.get("description") or merchant or "Scanned receipt").strip()
        if not description:
            description = "Scanned receipt"

        category = insights.categorize(description)

        return {
            "description": description,
            "amount_rupees": amount,
            "category": category,
            "merchant": merchant,
        }
    except Exception:
        return None
