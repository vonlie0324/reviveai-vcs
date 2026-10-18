
"""
Final cutover checklist.

Used before removing legacy soundtrack storage.
"""


def check_cutover(
    legacy_catalog_count,
    firestore_count,
    storage_count,
):
    return {
        "legacy_empty": legacy_catalog_count == 0,
        "firestore_matches_storage": (
            firestore_count == storage_count
        ),
        "ready_for_cutover": (
            legacy_catalog_count == 0
            and firestore_count == storage_count
        ),
    }
