"""
Runtime loop adapter connecting scheduler execution
with the recovery cycle service.
"""


class SoundtrackRecoveryRuntimeLoop:

    def __init__(
        self,
        recovery_cycle_service,
    ):
        self.recovery_cycle_service = recovery_cycle_service

    async def execute(self):
        return await self.recovery_cycle_service.run_cycle()
