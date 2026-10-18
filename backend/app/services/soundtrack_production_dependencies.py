"""
Production dependency builder for soundtrack integration.
"""


class SoundtrackProductionDependencies:

    def __init__(
        self,
        soundtrack_integration,
    ):
        self.soundtrack_integration = (
            soundtrack_integration
        )

    def attach_media_generation(
        self,
        service,
    ):
        service.soundtrack_integration = (
            self.soundtrack_integration
        )
        return service

    def attach_media_studio_job(
        self,
        service,
    ):
        service.soundtrack_integration = (
            self.soundtrack_integration
        )
        return service

    def attach_final_assembly(
        self,
        service,
    ):
        service.soundtrack_integration = (
            self.soundtrack_integration
        )
        return service
