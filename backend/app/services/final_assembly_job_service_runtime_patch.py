"""
Runtime patch helper for final assembly jobs.
"""


def resolve_final_audio_asset(
    service,
    soundtrack_id,
):
    integration = getattr(
        service,
        "soundtrack_integration",
        None,
    )

    if not integration:
        return None

    return integration.get_assembly_audio(
        soundtrack_id
    )
