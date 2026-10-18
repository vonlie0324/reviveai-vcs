
"""
Checks required cloud soundtrack configuration.
"""


def check(settings):
    required = [
        "GOOGLE_CLOUD_STORAGE_BUCKET",
        "FIREBASE_PROJECT_ID",
    ]

    missing = [
        key
        for key in required
        if not getattr(settings, key, None)
    ]

    return {
        "ready": len(missing) == 0,
        "missing": missing,
    }
