
"""
Final soundtrack migration runner.

Migration phases:
1. Discover local soundtrack assets
2. Upload to Cloud Storage
3. Register Firestore metadata
4. Validate counts
"""

from pathlib import Path


def migrate_soundtracks(
    source_directory,
    migration_service,
):
    results = []

    for file in Path(source_directory).rglob("*"):
        if file.is_file():
            results.append(
                migration_service.migrate_local_track(
                    file
                )
            )

    return results


if __name__ == "__main__":
    print(
        "Configure storage and Firestore services before execution."
    )
