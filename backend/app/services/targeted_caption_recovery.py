"""Reuse durable narration stems to create a NEW subtitles-only audio version.

The existing approved master is never altered. Any unverified shot fails closed.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.models.audio_finishing import AudioFinishingJobStage, AudioFinishingReviewStatus
from app.models.final_assembly import AssemblyAsset, AssemblyAssetKind
from app.services.audio_finishing_job_service import audio_finishing_job_store
from app.services.narration_alignment import write_srt
from app.services.speech_verified_alignment import align_voice_wav


class TargetedCaptionRecoveryError(ValueError):
    def __init__(self, message: str, reports: dict | None = None):
        super().__init__(message)
        self.reports = reports or {}


def _diagnostic(exc: Exception) -> dict:
    try:
        report = json.loads(str(exc))
        return report if isinstance(report, dict) else {'error': str(exc)[:450]}
    except (TypeError, ValueError):
        return {'error': str(exc)[:450]}


def build_caption_only_version(source_job_id: str):
    store = audio_finishing_job_store
    source = store.get(source_job_id)
    if source.stage != AudioFinishingJobStage.DELIVERED or source.result is None:
        raise TargetedCaptionRecoveryError('Source audio job must be delivered')
    stems = (source.detail or {}).get('narration_stems') or []
    required = [c for c in source.result.voiceover_cues if c.text.strip()]
    stem_map = {int(stem['shot_number']): stem for stem in stems}
    if not required or set(stem_map) != {c.shot_number for c in required}:
        raise TargetedCaptionRecoveryError('Complete GCS narration stems are required')
    reports = {}
    cues = []
    cursor = 0.0
    with tempfile.TemporaryDirectory(prefix='reviveai-caption-align-') as temp:
        for item in source.result.voiceover_cues:
            if not item.text.strip():
                cursor += item.duration_seconds
                continue
            stem = stem_map[item.shot_number]
            normalized = Path(temp) / f'voice-{item.shot_number:02d}.wav'
            # Original stems use the delivery mix's sample rate. Normalize to STT PCM.
            raw = Path(temp) / f'source-{item.shot_number:02d}.wav'
            uri = stem.get('gcs_uri')
            if not uri:
                raise TargetedCaptionRecoveryError('Stem is missing GCS URI')
            store._artifacts.ensure_local(raw, owner_id=source_job_id,
                relative_path=f"assets/{stem['filename']}", gcs_uri=uri)
            if not raw.exists():
                raise TargetedCaptionRecoveryError(f"Narration stem for shot {item.shot_number} unavailable")
            from app.services.audio_finishing_job_service import _ffmpeg_executable, _run
            _run([_ffmpeg_executable(), '-y', '-i', str(raw), '-ac', '1', '-ar', '16000',
                  '-c:a', 'pcm_s16le', str(normalized)])
            report = {}
            for use_hints, recognition_model, attempt_name in (
                (False, None, "STANDARD"),
                (True, None, "HINTED"),
                (True, "latest_short", "SHORT_UTTERANCE_MODEL"),
            ):
                try:
                    aligned, report = align_voice_wav(normalized, item.text, use_hints=use_hints, recognition_model=recognition_model)
                    reports[str(item.shot_number)] = {**report, 'status': 'VERIFIED', 'attempt': attempt_name}
                    cues.extend((cursor + a, cursor + b, text) for a, b, text in aligned)
                    break
                except Exception as exc:
                    report = {**_diagnostic(exc), 'method': 'UNVERIFIED', 'attempt': attempt_name}
            else:
                # Only independent acoustic alignment can resolve invalid STT word offsets.
                # Do not use forced alignment to conceal transcript mismatches.
                if report.get('failure_code') == 'INVALID_WORD_OFFSETS' and report.get('transcript_match_ratio', 0) >= 0.90:
                    try:
                        from app.services.remote_forced_alignment import force_align_voice_wav
                        aligned, aligned_report = force_align_voice_wav(normalized, item.text)
                        reports[str(item.shot_number)] = {**aligned_report, 'status': 'VERIFIED', 'attempt': 'FORCED_ALIGNMENT'}
                        cues.extend((cursor + a, cursor + b, text) for a, b, text in aligned)
                    except Exception as exc:
                        reports[str(item.shot_number)] = {**report, 'forced_alignment_error': str(exc)[:350], 'status': 'UNVERIFIED'}
                else:
                    reports[str(item.shot_number)] = report
            cursor += item.duration_seconds
        if any(report.get('status') != 'VERIFIED' for report in reports.values()) or len(reports) != len(required):
            raise TargetedCaptionRecoveryError('Caption alignment is still unverified; no assets or state changed', reports)
        now = datetime.now(timezone.utc)
        # Preserve the approved visual-master provenance used by deterministic QC.
        # The source job was created from this assembly; never infer a replacement ID.
        from app.services.final_assembly_job_service import final_assembly_job_store
        from app.models.final_assembly import FinalAssemblyReviewStatus
        assembly = final_assembly_job_store.get(source.assembly_job_id)
        if (not assembly.result or assembly.result.review_status != FinalAssemblyReviewStatus.APPROVED
                or (source.detail or {}).get('source_visual_asset_id') != assembly.result.final_video.asset_id):
            raise TargetedCaptionRecoveryError('Source visual-master lineage is not approved or does not match assembly')
        newer = store.create(source.assembly_job_id, source.options)
        newer.result = source.result.model_copy(deep=True)
        newer.stage = AudioFinishingJobStage.COMPLETED
        newer.result.review_status = AudioFinishingReviewStatus.NEEDS_REVIEW
        newer.result.reviewed_at = None
        newer.detail = {
            **(source.detail or {}),
            'subtitle_alignment': 'SPEECH_VERIFIED',
            'subtitle_cues': len(cues),
            'speech_alignment_reports': reports,
            'narration_stems': stems,
            'caption_only_recovery': True,
            'source_audio_job_id': source_job_id,
            'visual_master_preserved': True,
            'audio_mix_preserved': True,
            'fresh_ai_review_required': True,
        }
        newer.message = 'Subtitle-only recovery completed; fresh AI review required'
        newer.error = None
        newer.progress_current = newer.progress_total
        assets_dir = store.assets_dir(newer.job_id)
        for asset in (newer.result.delivery_video, newer.result.audio_mix):
            if asset is None:
                continue
            # Reuse immutable source GCS binaries, and expose through the new job's URL.
            if not asset.gcs_uri:
                source_path, _ = store.asset_path(source.job_id, asset.asset_id)
                shutil.copy2(source_path, assets_dir / asset.filename)
            asset.asset_url = f'/api/v1/youtube/audio-jobs/{newer.job_id}/assets/{asset.asset_id}'
        subtitle_id = f'subs_{uuid4().hex}'
        subtitle_path = assets_dir / f'{subtitle_id}.srt'
        write_srt(subtitle_path, cues)
        newer.result.subtitles = AssemblyAsset(
            asset_id=subtitle_id, kind=AssemblyAssetKind.SUBTITLES, created_at=now,
            filename=subtitle_path.name, mime_type='application/x-subrip',
            asset_url=f'/api/v1/youtube/audio-jobs/{newer.job_id}/assets/{subtitle_id}',
        )
        newer.result.warnings = [x for x in newer.result.warnings if 'storyboard-estimated SRT' not in x and 'Audio-aligned captions unavailable' not in x]
        store.save(newer)
        return newer
