"""Opt-in live alignment smoke test. Skipped before import-time cloud calls by default."""
import os
import pytest
if os.environ.get("REVIVEAI_RUN_LIVE_ALIGNMENT_TEST") != "1":
    pytest.skip("Live alignment requires explicit opt-in; never run in offline unit suite", allow_module_level=True)

import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

from app.services.remote_forced_alignment import force_align_voice_wav

url = "https://reviveai-aligner-872000338860.asia-southeast1.run.app"
os.environ["REVIVEAI_FORCED_ALIGN_URL"] = url

gcloud = shutil.which("gcloud.cmd") or shutil.which("gcloud")

if not gcloud:
    raise RuntimeError(
        "Cannot find gcloud.cmd. Run 'where.exe gcloud' to locate it."
    )

result = subprocess.run(
    [
        gcloud,
        "auth",
        "print-identity-token",
        "--impersonate-service-account=reviveai-runtime@ai-projects-250716.iam.gserviceaccount.com",
        f"--audiences={url}",
    ],
    capture_output=True,
    text=True,
)

if result.returncode != 0:
    raise RuntimeError(result.stderr.strip())

token = result.stdout.strip()

if not token:
    raise RuntimeError("Identity token was not generated")

with patch(
    "google.oauth2.id_token.fetch_id_token",
    return_value=token,
):
    cues, report = force_align_voice_wav(
        Path("narration-shot-01-pcm16.wav"),
        "Meet Buster, the most meticulous tailor in the canine fashion world.",
    )

print("ALIGNMENT REPORT:", report)
print("SUBTITLE CUES:", cues)

assert report["method"] == "WHISPERX_FORCED_ALIGNMENT"
assert report["recognized_words"] == 11
assert report["timestamps_valid"] is True

print("BACKEND INTEGRATION TEST: PASSED")