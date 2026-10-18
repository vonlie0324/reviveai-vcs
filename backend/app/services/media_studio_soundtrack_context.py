"""
Provides soundtrack context for media studio jobs.
"""


class MediaStudioSoundtrackContext:

    def __init__(self, soundtrack_provider):
        self.provider = soundtrack_provider

    def build_context(self, soundtrack_id):
        soundtrack = self.provider.resolve_for_generation(
            soundtrack_id
        )

        return {
            "soundtrack_id": soundtrack["track_id"],
            "soundtrack_storage_path": soundtrack["storage_path"],
            "soundtrack_preview_url": soundtrack.get(
                "preview_url"
            ),
        }
