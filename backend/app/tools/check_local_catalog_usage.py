
"""
Find remaining local catalog dependencies.

Use during migration cleanup.
"""

from pathlib import Path


PATTERNS = [
    "audio_youtube_library_catalog",
    "catalog_path",
    "local_path",
]


def scan(root):
    matches = []

    for file in Path(root).rglob("*.py"):
        content = file.read_text(
            encoding="utf-8",
            errors="ignore",
        )

        for pattern in PATTERNS:
            if pattern in content:
                matches.append({
                    "file": str(file),
                    "pattern": pattern,
                })

    return matches


if __name__ == "__main__":
    print(scan("app"))
