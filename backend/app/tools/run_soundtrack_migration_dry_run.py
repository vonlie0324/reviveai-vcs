
"""
Dry run migration report.

Does not modify assets.
"""


def build_dry_run(local_tracks, firestore_tracks, storage_objects):
    return {
        "local_tracks": local_tracks,
        "firestore_tracks": firestore_tracks,
        "storage_objects": storage_objects,
        "missing_firestore": max(
            local_tracks - firestore_tracks,
            0,
        ),
        "missing_storage": max(
            firestore_tracks - storage_objects,
            0,
        ),
    }


if __name__ == "__main__":
    print(
        "Inject real inventory counts before running."
    )
