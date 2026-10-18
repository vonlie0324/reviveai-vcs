"""
Application lifespan integration wrapper for soundtrack recovery runtime.
"""


class SoundtrackRecoveryLifespanApp:

    def __init__(
        self,
        factory,
    ):
        self.factory = factory
        self.runtime = None

    async def startup(self, app):
        self.runtime = self.factory.create()

        app.state.soundtrack_recovery_runtime = (
            self.runtime
        )

    async def shutdown(self, app):
        self.runtime = None

        app.state.soundtrack_recovery_runtime = None
