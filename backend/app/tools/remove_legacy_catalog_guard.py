
"""
Legacy catalog removal guard.

Used before deleting local soundtrack catalog files.
"""


def validate_no_legacy_catalog(path):
    forbidden = [
        "audio_youtube_library_catalog.json",
        "youtube_audio_library_catalog.json",
    ]

    return not any(
        item in str(path)
        for item in forbidden
    )
