
from pathlib import Path

PATTERNS = [
    "audio_youtube_library_catalog",
    "YouTubeAudioLibraryService",
    "local_path",
]


def scan(root="app"):
    result = []

    for file in Path(root).rglob("*.py"):
        text = file.read_text(
            encoding="utf-8",
            errors="ignore",
        )

        for pattern in PATTERNS:
            if pattern in text:
                result.append(
                    {
                        "file": str(file),
                        "pattern": pattern,
                    }
                )

    return result


if __name__ == "__main__":
    print(scan())
