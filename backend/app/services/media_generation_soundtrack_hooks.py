"""
Hooks used by media generation workflow.

Replace existing direct local soundtrack resolution
with these calls.
"""


def resolve_generation_soundtrack(
    integration,
    soundtrack_id,
):
    return integration.get_generation_soundtrack(
        soundtrack_id
    )
