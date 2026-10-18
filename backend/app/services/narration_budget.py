"""Conservative *estimated* Google TTS accounting; not invoice reconciliation.

Amounts intentionally include potential SDK retries because the provider does
not return billable USD. Configure the price for the selected voice family.
"""
from __future__ import annotations

import math
import os


def estimated_tts_usd(text: str, *, max_attempts: int = 3) -> float:
    """Reserve an upper-bound estimate per utterance; never silently use zero.

    REVIVEAI_TTS_USD_PER_MILLION_CHARS must reflect the real contracted rate.
    If it is unset, voice synthesis is blocked until an administrator configures it.
    """
    raw = os.environ.get("REVIVEAI_TTS_USD_PER_MILLION_CHARS", "").strip()
    try:
        rate = float(raw)
    except ValueError as exc:
        raise ValueError("Invalid REVIVEAI_TTS_USD_PER_MILLION_CHARS") from exc
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("Set REVIVEAI_TTS_USD_PER_MILLION_CHARS to the contracted TTS rate before autonomous narration")
    if max_attempts < 1 or max_attempts > 5:
        raise ValueError("Invalid TTS retry allowance")
    return max(0.000001, len(text.encode('utf-8')) * rate * max_attempts / 1_000_000)
