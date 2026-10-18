"""Conservative Gemini review reservation estimate; not actual provider billing."""
from __future__ import annotations
import math
import os


def review_cost_reservation_usd() -> float:
    """Require operator-configured maximum estimated cost for one review call.

    Must include multimodal prompt content, output, retries charged separately.
    Unconfigured rate fails closed instead of allowing unbudgeted generation.
    """
    raw = os.environ.get("REVIVEAI_GEMINI_REVIEW_RESERVATION_USD", "").strip()
    try:
        amount = float(raw)
    except ValueError as exc:
        raise ValueError("Invalid REVIVEAI_GEMINI_REVIEW_RESERVATION_USD") from exc
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("Configure REVIVEAI_GEMINI_REVIEW_RESERVATION_USD before AI reviews")
    return amount
