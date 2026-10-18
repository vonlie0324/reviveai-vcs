"""
Execution loop abstraction for scheduled recovery runs.
"""


class SoundtrackRecoveryExecutionLoop:

    def __init__(self, runner):
        self.runner = runner

    async def execute(self, job_ids):
        return await self.runner.run(job_ids)
