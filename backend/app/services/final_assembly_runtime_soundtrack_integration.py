"""
Final assembly runtime soundtrack integration.

Connects final assembly jobs with cloud-backed soundtrack assets.
"""


class FinalAssemblyRuntimeSoundtrackIntegration:

    def __init__(
        self,
        soundtrack_integration,
    ):
        self.soundtrack_integration = soundtrack_integration

    def resolve_audio_asset(self, soundtrack_id):
        return self.soundtrack_integration.get_assembly_audio(
            soundtrack_id
        )

    def attach_to_job_service(self, service):
        service.soundtrack_integration = (
            self.soundtrack_integration
        )
        return service
