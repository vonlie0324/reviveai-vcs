"""Gemini usage metering for successful provider responses.

Prices are operator-supplied USD per million tokens for the exact deployed
model and modality. Do not confuse token usage with an invoice amount.
"""
from __future__ import annotations

import math
import os
from typing import Any


def _get(metadata: Any, key: str, default: Any = None) -> Any:
    if isinstance(metadata, dict):
        return metadata.get(key, default)
    return getattr(metadata, key, default)


def _nonnegative_int(value: Any, name: str) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        raise ValueError(f"Invalid {name}")
    result = int(value)
    if result < 0 or result != float(value):
        raise ValueError(f"Invalid {name}")
    return result


def _rate(name: str) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        raise ValueError(f"Missing {name}: cannot determine metered Gemini cost")
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid {name}") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"Invalid {name}")
    return value


def gemini_token_cost(response: Any) -> tuple[float, dict[str, int]]:
    """Return estimated dollars and recorded usage; never fabricate missing usage.

    Cached-token discounts and separate image/video/audio pricing are NOT
    inferred. If modality pricing differs, do not use this for final billing.
    """
    usage = _get(response, "usage_metadata")
    if usage is None:
        raise ValueError("Gemini response has no usage_metadata")
    prompt = _get(usage, "prompt_token_count")
    output = _get(usage, "candidates_token_count")
    thoughts = _get(usage, "thoughts_token_count")
    if prompt is None or output is None:
        raise ValueError("Gemini usage metadata lacks token counts")
    input_tokens = _nonnegative_int(prompt, "prompt_token_count")
    output_tokens = _nonnegative_int(output, "candidates_token_count")
    thoughts_tokens = _nonnegative_int(thoughts, "thoughts_token_count")
    input_rate = _rate("REVIVEAI_GEMINI_INPUT_USD_PER_MILLION_TOKENS")
    output_rate = _rate("REVIVEAI_GEMINI_OUTPUT_USD_PER_MILLION_TOKENS")
    amount = (input_tokens * input_rate + (output_tokens + thoughts_tokens) * output_rate) / 1_000_000
    return amount, {"input_tokens": input_tokens, "output_tokens": output_tokens, "thinking_tokens": thoughts_tokens}
