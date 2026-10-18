"""
Persistence integration helpers for media jobs.

Keeps soundtrack references available during retries and resume flows.
"""


from app.models.soundtrack_job_schema import SoundtrackReference


def persist_job_soundtrack(
    job_data: dict,
    soundtrack_asset: dict | None,
):
    if not soundtrack_asset:
        return job_data

    reference = SoundtrackReference(
        soundtrack_id=soundtrack_asset.get("track_id"),
        storage_path=soundtrack_asset.get("storage_path"),
        source="CLOUD_STORAGE",
    )

    return {
        **job_data,
        "soundtrack": reference.to_dict(),
    }


def restore_job_soundtrack(
    job_data: dict,
):
    soundtrack = job_data.get("soundtrack")

    if not soundtrack:
        return None

    return SoundtrackReference.from_dict(
        soundtrack
    )
