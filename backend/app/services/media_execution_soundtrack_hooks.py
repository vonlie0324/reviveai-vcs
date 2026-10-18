"""
Execution hooks for production workflows.
"""


def prepare_media_execution_soundtrack(
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


def prepare_assembly_execution_soundtrack(
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
