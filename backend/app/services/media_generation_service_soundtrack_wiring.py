"""
Soundtrack dependency wiring for media generation service.
"""


def attach_soundtrack_integration(
    media_generation_service,
    soundtrack_integration,
):
    media_generation_service.soundtrack_integration = (
        soundtrack_integration
    )

    return media_generation_service
