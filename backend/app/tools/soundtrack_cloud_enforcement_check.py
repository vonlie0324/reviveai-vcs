
"""
Ensures new soundtrack flows do not depend on local storage.
"""


def validate_track(track):
    required = [
        "track_id",
        "storage_path",
    ]

    return all(
        field in track and track[field]
        for field in required
    )
