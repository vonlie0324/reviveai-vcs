"""Transparent channel production cost estimates; not a billing authority."""
from __future__ import annotations
from decimal import Decimal, ROUND_UP
from math import ceil
from app.core.config import get_settings


def estimate_channel_production(duration_seconds: int, max_keyframe_attempts: int = 2) -> dict:
    """Planning estimates use configured unit price and explicit unpriced allowances.

    This endpoint is advisory. Actual budget enforcement must reserve every billable
    provider operation atomically before dispatch and reconcile provider invoices.
    """
    seconds = max(6, min(3600, int(duration_seconds)))
    attempts = max(1, min(5, int(max_keyframe_attempts)))
    settings = get_settings()
    unit_rate = Decimal(str(settings.video_estimated_cost_per_unit_usd))
    units_per_second = Decimal(str(settings.video_estimated_units_per_generated_second))
    # Veo requests commonly generate fixed-length clips. A four-second segment
    # is a planning assumption, NOT a claim about the active model's clip length.
    segment_seconds = 4
    generated_seconds = ceil(seconds / segment_seconds) * segment_seconds
    one_pass = Decimal(generated_seconds) * units_per_second * unit_rate
    # Reserve capacity for one targeted retry, bounded by selected attempt limit;
    # this is NOT the worst-case cost of retrying every shot.
    retry_allowance = one_pass * (Decimal('0.25') if attempts > 1 else Decimal('0'))
    # These are planning allowances, not measured/current provider prices.
    voice_allowance = Decimal('0.20')
    music_allowance = Decimal('0.25')
    analysis_allowance = Decimal('0.25')
    render_allowance = Decimal('0.15')
    publishing_allowance = Decimal('0.05')
    subtotal = one_pass + retry_allowance + voice_allowance + music_allowance + analysis_allowance + render_allowance + publishing_allowance
    contingency = subtotal * Decimal('0.20')
    rounding = lambda n: float(n.quantize(Decimal('0.01'), rounding=ROUND_UP))
    return {
        'duration_seconds': seconds,
        'estimated_generated_video_seconds': generated_seconds,
        'max_keyframe_attempts': attempts,
        'currency': 'USD',
        'components': [
            {'label': 'Video generation (first pass)', 'usd': rounding(one_pass), 'basis': 'Configured Veo unit rate'},
            {'label': 'Targeted video retries', 'usd': rounding(retry_allowance), 'basis': '25% of one pass if attempts > 1'},
            {'label': 'Narration / TTS', 'usd': rounding(voice_allowance), 'basis': 'Planning allowance, not a live price'},
            {'label': 'Soundtrack / sound effects', 'usd': rounding(music_allowance), 'basis': 'Planning allowance; licensing varies'},
            {'label': 'AI analysis and quality reviews', 'usd': rounding(analysis_allowance), 'basis': 'Planning allowance, not a live price'},
            {'label': 'Assembly, storage and delivery', 'usd': rounding(render_allowance), 'basis': 'Planning allowance, not measured'},
            {'label': 'Publishing and monitoring', 'usd': rounding(publishing_allowance), 'basis': 'Planning allowance; API usage typically not priced per upload'},
            {'label': 'Contingency', 'usd': rounding(contingency), 'basis': '20% of estimate'},
        ],
        'recommended_budget_usd': rounding(subtotal + contingency),
        'estimated_one_pass_video_usd': rounding(one_pass),
        'worst_case_video_only_usd': rounding(one_pass * attempts),
        'notes': [
            'Estimates are illustrative and use configured unit conversion; confirm your current provider pricing and actual clip lengths.',
            'This is not a full guaranteed cost ceiling; all external billable operations require atomic reservations to enforce a cap.',
            'Maximum cost remains user-configurable. Actual generated seconds can exceed final edited duration.',
        ],
    }
