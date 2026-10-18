"""Adopt existing provider-completed Veo clips; never issue a generation request.

Legacy captures may live in the default Firestore database. Only authenticated,
scoped operation records are used; all budget accounting stays in the runtime DB.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.core.firebase_clients import get_runtime_firestore_client
from app.models.media_studio import (VideoClipAsset, MediaAssetReviewStatus,
    VideoGenerationChargeStatus, ClipOperationStatus)
from app.services.firestore_budget_service import FirestoreBudgetService
from app.services.media_generation_service import MediaGenerationService


def _capture_for_claim(claim_id: str, production_id: str):
    from google.cloud import firestore
    runtime = get_runtime_firestore_client()
    candidates = [runtime]
    if getattr(runtime, '_database', '(default)') != '(default)':
        candidates.append(firestore.Client(project=runtime.project, database='(default)'))
    for db in candidates:
        doc = db.collection('veo_operations').document(claim_id).get()
        if doc.exists:
            payload = doc.to_dict() or {}
            if (str(payload.get('operationId')) != claim_id or
                    str(payload.get('productionId')) != production_id):
                raise RuntimeError('VEO_CAPTURE_SCOPE_MISMATCH: refusing reuse')
            return payload
    return None


def adopt_existing_veo_operation(store, job_id: str, shot_number: int, settings) -> bool:
    job = store.get(job_id)
    if not job.result:
        return False
    if any(c.shot_number == shot_number for c in job.result.video_clips):
        return True
    charges = [c for c in job.result.video_generation_charges if c.shot_number == shot_number]
    if not charges:
        return False

    # Inspect all previous claims, including ones marked FAILED locally after
    # a capture/persistence exception, before any new claim is allowed.
    for charge in reversed(charges):
        claim_id = charge.generation_claim_id
        captured = _capture_for_claim(claim_id, job.production_brief_job_id)
        provider_name = (str((captured or {}).get('metadata', {}).get('providerOperation') or
                             charge.provider_operation_name or '').strip())
        if not provider_name:
            # If a claimed operation has no known provider identity, a retry
            # could double-bill. Require operator reconciliation.
            if charge.status in {VideoGenerationChargeStatus.CLAIMED,
                                 VideoGenerationChargeStatus.SUBMITTED}:
                raise RuntimeError(f'VEO_OUTCOME_UNKNOWN: claim {claim_id} has no provider operation')
            # A locally FAILED attempt may nevertheless have reached Google.
            # Check durable budget reservation before allowing a new attempt.
            db = get_runtime_firestore_client()
            tx = db.collection('production_cost_transactions').document(claim_id).get()
            if tx.exists and str((tx.to_dict() or {}).get('status')).upper() == 'RESERVED':
                raise RuntimeError(f'VEO_OUTCOME_UNKNOWN: reserved claim {claim_id} has no provider operation')
            continue

        # Only operations from the configured project/model endpoint are recoverable.
        expected_prefix = f'projects/{settings.google_cloud_project}/locations/'
        if not provider_name.startswith(expected_prefix) or '/operations/' not in provider_name:
            raise RuntimeError('VEO_PROVIDER_OPERATION_SCOPE_MISMATCH')
        from google import genai
        from google.genai import types
        location = provider_name.split('/locations/', 1)[1].split('/', 1)[0]
        client = genai.Client(vertexai=True, project=settings.google_cloud_project, location=location)
        operation = client.operations.get(operation=types.GenerateVideosOperation(name=provider_name))
        if not getattr(operation, 'done', False):
            raise RuntimeError(f'VEO_OPERATION_IN_PROGRESS: {provider_name}')
        if getattr(operation, 'error', None):
            raise RuntimeError(f'VEO_PROVIDER_FAILED_REVIEW_REQUIRED: {provider_name}')
        response = getattr(operation, 'response', None) or getattr(operation, 'result', None)
        videos = getattr(response, 'generated_videos', None) or []
        if not videos or not getattr(videos[0], 'video', None):
            raise RuntimeError(f'VEO_NO_RECOVERABLE_VIDEO: {provider_name}')
        video = videos[0].video
        gcs_uri = getattr(video, 'uri', None)
        if not gcs_uri or not str(gcs_uri).startswith('gs://'):
            raise RuntimeError('VEO_OUTPUT_URI_UNAVAILABLE')
        if f'/{job_id}/shot-{shot_number}/' not in gcs_uri:
            raise RuntimeError('VEO_OUTPUT_LINEAGE_MISMATCH')

        shot = next((s for s in job.result.source_snapshot.storyboard.shots if s.shot_number == shot_number), None)
        keyframe = next((k for k in job.result.keyframes if k.shot_number == shot_number), None)
        if shot is None or keyframe is None:
            raise RuntimeError('VEO_RECOVERY_SOURCE_MISSING')
        service = MediaGenerationService(settings)
        asset_id = f'clip_{shot_number}_{uuid4().hex}'
        output_path = Path(store.assets_dir(job_id)) / f'{asset_id}.mp4'
        service._download_gcs_video(gcs_uri, output_path)
        clip = VideoClipAsset(
            asset_id=asset_id, shot_number=shot_number, created_at=datetime.now(timezone.utc),
            model=charge.model, mime_type='video/mp4', filename=output_path.name,
            asset_url=f'/api/v1/youtube/media-jobs/{job_id}/assets/{asset_id}',
            prompt=service.video_prompt(job.result.source_snapshot, shot),
            intended_duration_seconds=shot.duration_seconds,
            generated_duration_seconds=charge.requested_duration_seconds,
            source_keyframe_asset_id=keyframe.asset_id, gcs_uri=gcs_uri,
            review_status=MediaAssetReviewStatus.NEEDS_REVIEW,
            generation_attempt=charge.generation_attempt,
        )
        # Save the clip first: if a later ledger action fails, subsequent adoption
        # observes the existing asset and cannot submit another provider request.
        job = store.get(job_id)
        if not any(c.shot_number == shot_number for c in job.result.video_clips):
            job.result.video_clips.append(clip)
            job.result.video_clips.sort(key=lambda c: c.shot_number)
        op = job.result.clip_operations.get(shot_number)
        if op:
            op.status = ClipOperationStatus.READY
            op.error = None
            op.message = f'Shot {shot_number} recovered from completed Veo operation; awaiting review'
            op.provider_operation_name = provider_name
            op.generation_claim_id = claim_id
            op.updated_asset_id = clip.asset_id
            op.updated_at = datetime.now(timezone.utc)
        for item in job.result.video_generation_charges:
            if item.generation_claim_id == claim_id:
                item.status = VideoGenerationChargeStatus.SUCCEEDED
                item.provider_operation_name = provider_name
                item.asset_id = clip.asset_id
                item.error = None
                item.updated_at = datetime.now(timezone.utc)
        store.save(job)
        # No verified monetary usage is in this provider response. Reconcile with
        # the policy estimate explicitly labelled as such, not as verified billing.
        budget = FirestoreBudgetService()
        tx = budget.db.collection('production_cost_transactions').document(claim_id).get()
        if tx.exists and str((tx.to_dict() or {}).get('status')).upper() == 'RESERVED':
            budget.reconcile(job.production_brief_job_id, claim_id, charge.estimated_cost_usd,
                             charge.estimated_cost_usd)
            budget.db.collection('production_cost_transactions').document(claim_id).set({
                'costBasis': 'ESTIMATED_PROVIDER_USAGE_UNAVAILABLE',
                'providerOperationName': provider_name,
                'recoveredFromGcsUri': gcs_uri,
            }, merge=True)
        return True
    return False
