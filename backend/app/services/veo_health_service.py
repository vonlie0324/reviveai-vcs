from app.services.veo_runtime_health_service import (
    VeoRuntimeHealthService,
)


class VeoHealthService:
    """
    Exposes Veo worker health information.
    """

    def __init__(self):
        self.runtime = VeoRuntimeHealthService()

    def get_health(self):
        return self.runtime.health()
