"""
Hooks used by final assembly workflow.
"""


def resolve_audio_asset(
    integration,
    soundtrack_id,
):
    return integration.get_assembly_audio(
        soundtrack_id
    )
