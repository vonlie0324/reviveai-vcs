"""
Runtime patch helper for media generation service.

Adds soundtrack resolution through injected integration.
"""


def resolve_generation_audio(
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

    return integration.get_generation_soundtrack(
        soundtrack_id
    )
