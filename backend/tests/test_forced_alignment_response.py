from pathlib import Path
from unittest.mock import patch

from app.services.remote_forced_alignment import force_align_voice_wav

WORDS = [
    {"word": "Meet", "start": 0.462, "end": 0.682},
    {"word": "Buster,", "start": 0.803, "end": 1.264},
    {"word": "the", "start": 1.605, "end": 1.706},
    {"word": "most", "start": 1.746, "end": 1.946},
    {"word": "meticulous", "start": 2.007, "end": 2.649},
    {"word": "tailor", "start": 2.709, "end": 3.110},
    {"word": "in", "start": 3.231, "end": 3.311},
    {"word": "the", "start": 3.331, "end": 3.431},
    {"word": "canine", "start": 3.472, "end": 3.993},
    {"word": "fashion", "start": 4.054, "end": 4.495},
    {"word": "world.", "start": 4.515, "end": 4.816},
]


class MockResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {
            "words": WORDS,
            "model": "whisperx-align-en-cpu",
        }


def test_forced_alignment():
    with (
        patch.dict(
            "os.environ",
            {
                "REVIVEAI_FORCED_ALIGN_URL":
                "https://reviveai-aligner-872000338860.asia-southeast1.run.app"
            },
        ),
        patch(
            "google.oauth2.id_token.fetch_id_token",
            return_value="test-token",
        ),
        patch(
            "requests.post",
            return_value=MockResponse(),
        ),
    ):
        cues, report = force_align_voice_wav(
            Path("narration-shot-01-pcm16.wav"),
            "Meet Buster, the most meticulous tailor in the canine fashion world.",
        )

    assert report["method"] == "WHISPERX_FORCED_ALIGNMENT"
    assert report["recognized_words"] == 11
    assert report["timestamps_valid"] is True
    assert report["transcript_match_ratio"] >= 0.90

    print("BACKEND RESPONSE VALIDATION: PASSED")
    print("REPORT:", report)
    print("CUES:", cues)


if __name__ == "__main__":
    test_forced_alignment()