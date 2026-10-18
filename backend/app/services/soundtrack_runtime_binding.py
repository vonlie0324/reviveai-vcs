"""
Soundtrack runtime binding helpers.

Used to connect existing production services with the
cloud-backed soundtrack runtime without changing UI flows.
"""


def bind_soundtrack_runtime(service, soundtrack_integration):
    service.soundtrack_integration = soundtrack_integration
    return service


def resolve_soundtrack(service, soundtrack_id):
    if not getattr(service, "soundtrack_integration", None):
        raise RuntimeError(
            "Soundtrack integration is not configured"
        )

    return service.soundtrack_integration.get_generation_soundtrack(
        soundtrack_id
    )
