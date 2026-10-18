"""
Integration helper for production services.

Used by:
- media_generation_service
- media_studio_job_service
- final_assembly_service

Keeps soundtrack resolution centralized.
"""


class SoundtrackServiceIntegration:

    def __init__(
        self,
        media_provider,
        studio_context,
        assembly_adapter,
    ):
        self.media_provider = media_provider
        self.studio_context = studio_context
        self.assembly_adapter = assembly_adapter

    def get_generation_soundtrack(self, soundtrack_id):
        return self.media_provider.prepare_soundtrack(
            soundtrack_id
        )

    def get_studio_context(self, soundtrack_id):
        return self.studio_context.build_context(
            soundtrack_id
        )

    def get_assembly_audio(self, soundtrack_id):
        return self.assembly_adapter.prepare_audio_asset(
            soundtrack_id
        )
