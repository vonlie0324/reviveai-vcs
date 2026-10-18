"""
Runtime patch helper for media studio jobs.
"""


def resolve_job_soundtrack_context(
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

    return integration.get_studio_context(
        soundtrack_id
    )
