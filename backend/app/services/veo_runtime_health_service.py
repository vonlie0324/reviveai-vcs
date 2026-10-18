class VeoRuntimeHealthService:
    """
    Provides runtime health information for Veo workers.
    """

    def __init__(self):
        self.status = "INITIALIZED"

    def mark_running(self):
        self.status = "RUNNING"

    def mark_stopped(self):
        self.status = "STOPPED"

    def health(self):
        return {
            "service": "veo_recovery_worker",
            "status": self.status,
        }
