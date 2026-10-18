"""
Adapter used by media generation services to resolve
cloud-backed soundtrack assets.
"""


class MediaGenerationSoundtrackAdapter:

    def __init__(self, soundtrack_provider):
        self.provider = soundtrack_provider

    def prepare_soundtrack(self, soundtrack_id):
        return self.provider.resolve_for_generation(
            soundtrack_id
        )
