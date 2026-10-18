ReviveAI: TTS fail-safe replacement (2026-10-09)

Replace: backend/app/services/audio_finishing_job_service.py

MANDATORY: Add to your CURRENT backend/requirements.txt (do not replace your file or lose Pillow):
    google-cloud-texttospeech>=2.20.0,<3.0.0

Then run:
    python -m compileall -q app
    python -m pip install -r requirements.txt
    gcloud run deploy reviveai-api --source . --region asia-southeast1 --project ai-projects-250716

What changed:
- Raises an actionable error instead of substituting silence for required speech.
- Retries transient Google TTS failures up to three times, with brief backoff.
- Records the failing shot and provider error in job.detail and Cloud Run logs.
- Rejects approval of a COMPLETED audio master if any required narration cue is missing.
- Leaves previously DELIVERED historical jobs untouched; does not repair them automatically.
- Preserves existing visual/creative assets. Regenerating voice/audio still requires an explicit safely-orchestrated audio-only retry.

CAUTION: Diagnose service account permission, quota, or unsupported voice if TTS still fails after dependency install. No Cloud Run integration test was performed.
