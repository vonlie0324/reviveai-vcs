"""
Shared soundtrack context propagated through generation jobs.
"""


class SoundtrackJobContext:

    def __init__(
        self,
        soundtrack_integration=None,
    ):
        self.soundtrack_integration = soundtrack_integration

    def resolve(self, soundtrack_id):
        if not soundtrack_id:
            return None

        if not self.soundtrack_integration:
            return None

        return {
            "soundtrack_id": soundtrack_id,
            "asset": (
                self.soundtrack_integration
                .get_generation_soundtrack(soundtrack_id)
            ),
        }

    def attach(self, job):
        job.soundtrack_context = self
        return job
