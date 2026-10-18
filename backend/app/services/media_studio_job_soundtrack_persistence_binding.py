"""
Binding layer for media studio job persistence.

Bridges soundtrack persistence helpers into job service flows.
"""


from app.services.media_job_soundtrack_persistence import (
    persist_job_soundtrack,
    restore_job_soundtrack,
)


class MediaStudioJobSoundtrackPersistenceBinding:

    def create_job_payload(
        self,
        payload: dict,
        soundtrack_asset: dict | None,
    ):
        return persist_job_soundtrack(
            payload,
            soundtrack_asset,
        )

    def restore_job_context(
        self,
        job_data: dict,
    ):
        return restore_job_soundtrack(
            job_data
        )
