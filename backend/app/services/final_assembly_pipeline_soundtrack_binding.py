"""
Final assembly soundtrack binding.

Keeps FFmpeg processing isolated from storage details.
"""


class FinalAssemblyPipelineSoundtrackBinding:

    def __init__(self, soundtrack_integration):
        self.soundtrack_integration = soundtrack_integration

    def resolve_audio(self, soundtrack_id):
        return self.soundtrack_integration.get_assembly_audio(
            soundtrack_id
        )

    def attach(self, service):
        service.soundtrack_integration = (
            self.soundtrack_integration
        )
        return service
