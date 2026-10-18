"""
Soundtrack dependency wiring for media studio jobs.
"""


def attach_soundtrack_context(
    media_studio_job_service,
    soundtrack_integration,
):
    media_studio_job_service.soundtrack_integration = (
        soundtrack_integration
    )

    return media_studio_job_service
