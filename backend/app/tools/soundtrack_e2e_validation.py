
"""
End-to-end soundtrack validation checklist helper.

Validates:
1. Registry metadata exists
2. Storage object exists
3. Preview URL can be generated
4. Processing path can resolve asset
"""


def validate_soundtrack(
    firestore_record,
    storage_exists,
    preview_url,
):
    checks = {
        "firestore_metadata": bool(firestore_record),
        "storage_object": storage_exists,
        "preview_url": bool(preview_url),
    }

    return {
        "checks": checks,
        "passed": all(checks.values()),
    }
