"""
Helpers for persisting soundtrack references in jobs.
"""


def persist_soundtrack_reference(
    detail: dict,
    soundtrack_asset: dict | None,
):
    if not soundtrack_asset:
        return detail

    return {
        **detail,
        "soundtrack_id": soundtrack_asset.get(
            "track_id"
        ),
        "soundtrack_storage_path": soundtrack_asset.get(
            "storage_path"
        ),
        "soundtrack_source": "CLOUD_STORAGE",
    }


def extract_soundtrack_reference(detail: dict):
    return {
        "track_id": detail.get(
            "soundtrack_id"
        ),
        "storage_path": detail.get(
            "soundtrack_storage_path"
        ),
        "source": detail.get(
            "soundtrack_source"
        ),
    }
