"""
Soundtrack dependency wiring for final assembly.
"""


def attach_soundtrack_adapter(
    final_assembly_service,
    soundtrack_integration,
):
    final_assembly_service.soundtrack_integration = (
        soundtrack_integration
    )

    return final_assembly_service
