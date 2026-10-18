"""
Media studio job soundtrack binding.
"""


class MediaStudioJobSoundtrackBinding:

    def __init__(self, soundtrack_integration):
        self.soundtrack_integration = soundtrack_integration

    def build_context(self, soundtrack_id):
        return self.soundtrack_integration.get_studio_context(
            soundtrack_id
        )

    def attach(self, service):
        service.soundtrack_integration = (
            self.soundtrack_integration
        )
        return service
