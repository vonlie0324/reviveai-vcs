
"""
Cloud soundtrack validation report.

Validates migration consistency between:
- legacy local tracks
- Firestore registry
- Cloud Storage objects
"""


def build_report(local_tracks, firestore_tracks, storage_objects):
    return {
        "legacy_local_tracks": local_tracks,
        "firestore_registry_tracks": firestore_tracks,
        "cloud_storage_objects": storage_objects,
        "registry_matches_storage": (
            firestore_tracks == storage_objects
        ),
        "migration_complete": (
            local_tracks == firestore_tracks == storage_objects
        ),
    }
