"""
Media generation pipeline soundtrack binding.

Provides a single integration point for Veo/media generation
services to resolve cloud-backed soundtrack assets.
"""


class MediaGenerationPipelineSoundtrackBinding:

    def __init__(self, soundtrack_integration):
        self.soundtrack_integration = soundtrack_integration

    def resolve(self, soundtrack_id):
        return self.soundtrack_integration.get_generation_soundtrack(
            soundtrack_id
        )

    def attach(self, service):
        service.soundtrack_integration = (
            self.soundtrack_integration
        )
        return service
