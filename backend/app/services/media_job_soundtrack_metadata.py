"""
Utilities for persisting soundtrack metadata into jobs.
"""


def add_soundtrack_metadata(
    detail: dict,
    soundtrack,
):
    if not soundtrack:
        return detail

    return {
        **detail,
        "soundtrack": {
            "id": soundtrack.get("track_id"),
            "storage_path": soundtrack.get(
                "storage_path"
            ),
        },
    }
