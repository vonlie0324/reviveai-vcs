
from pathlib import Path

SEARCH_TERMS = [
    "audio_youtube_library_catalog",
    "catalog_path",
    "youtube_audio_library_catalog",
    ".json",
    "local_path",
]


def find_usage(root="app"):
    results = []

    for file in Path(root).rglob("*.py"):
        text = file.read_text(
            encoding="utf-8",
            errors="ignore",
        )

        for term in SEARCH_TERMS:
            if term in text:
                results.append({
                    "file": str(file),
                    "match": term,
                })

    return results


if __name__ == "__main__":
    print(find_usage())
