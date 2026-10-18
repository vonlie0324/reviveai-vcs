"""
Execution-time soundtrack context.

Used by generation and assembly execution paths to avoid
re-resolving soundtrack metadata repeatedly.
"""


class SoundtrackExecutionContext:

    def __init__(self, asset=None):
        self.asset = asset or {}

    @property
    def soundtrack_id(self):
        return self.asset.get("track_id")

    @property
    def storage_path(self):
        return self.asset.get("storage_path")

    def to_dict(self):
        return {
            "soundtrack_id": self.soundtrack_id,
            "storage_path": self.storage_path,
        }


def build_soundtrack_execution_context(
    soundtrack_integration,
    soundtrack_id,
):
    if not soundtrack_id:
        return SoundtrackExecutionContext()

    asset = soundtrack_integration.get_generation_soundtrack(
        soundtrack_id
    )

    return SoundtrackExecutionContext(asset)
