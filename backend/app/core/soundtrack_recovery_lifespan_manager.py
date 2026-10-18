"""
Lifespan manager wrapper for soundtrack recovery.
"""


class SoundtrackRecoveryLifespanManager:

    def __init__(self, runner):
        self.runner = runner

    async def startup(self, app):
        app.state.soundtrack_recovery_runner = self.runner

    async def shutdown(self, app):
        app.state.soundtrack_recovery_runner = None
