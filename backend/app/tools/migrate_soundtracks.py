
from pathlib import Path


def migrate_directory(directory: str, soundtrack_service):
    """
    Migrate existing local soundtrack files.
    """

    root = Path(directory)

    results = []

    for file in root.rglob("*"):
        if file.is_file():
            results.append(
                soundtrack_service.import_track_to_cloud(
                    file,
                    {
                        "title": file.stem,
                        "filename": file.name,
                    },
                )
            )

    return results


if __name__ == "__main__":
    print(
        "Use migrate_directory() with configured services."
    )
