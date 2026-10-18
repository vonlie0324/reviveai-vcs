"""
Manages soundtrack state attached to long-running jobs.
"""


class JobSoundtrackStateManager:

    def attach_soundtrack(
        self,
        job_data: dict,
        soundtrack_reference: dict,
    ):
        return {
            **job_data,
            "soundtrack": soundtrack_reference,
        }

    def get_soundtrack(
        self,
        job_data: dict,
    ):
        return job_data.get(
            "soundtrack"
        )
