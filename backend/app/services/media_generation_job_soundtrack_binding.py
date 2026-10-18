"""
Binding layer for media generation jobs.
"""


from app.services.media_job_soundtrack_persistence import (
    persist_job_soundtrack,
)


class MediaGenerationJobSoundtrackBinding:

    def enrich_generation_request(
        self,
        request: dict,
        soundtrack_asset: dict | None,
    ):
        return persist_job_soundtrack(
            request,
            soundtrack_asset,
        )
