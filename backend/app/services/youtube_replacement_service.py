"""Explicit, fail-closed replacement of a scheduled YouTube video.

Never uses the regular master deduplication path and never regenerates media.
The upload is PRIVATE until a separate user-confirmed activation request.
"""
from __future__ import annotations

import hashlib
import tempfile
from datetime import timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from app.services.firestore_job_repository import FirestoreJobRepository
from app.services.youtube_publishing_service import YouTubePublishingError, YouTubePublishingService, now
from app.models.youtube_publishing import YouTubePublication, YouTubePublishStatus
from app.services.autopilot_state_service import autopilot_state_store, AutopilotStateConflictError
from app.services.youtube_publication_claim_service import youtube_publication_claim_service

MAX_BYTES = 64 * 1024 * 1024


class YouTubeReplacementService:
    def __init__(self, publisher: YouTubePublishingService):
        self.publisher = publisher
        self.jobs = FirestoreJobRepository('youtube_replacement_jobs')

    def _job_id(self, original_id: str, digest: str) -> str:
        return 'ytrepl_' + hashlib.sha256((original_id + ':' + digest).encode()).hexdigest()[:28]

    def status(self, original_id: str, digest: str) -> dict | None:
        return self.jobs.load(self._job_id(original_id, digest))

    async def _youtube_video(self, video_id: str) -> dict:
        p = self.publisher
        async with httpx.AsyncClient(timeout=p.settings.youtube_request_timeout_seconds) as client:
            response = await p._authenticated_get(client, 'https://www.googleapis.com/youtube/v3/videos', params={
                'part': 'snippet,status,contentDetails', 'id': video_id,
            })
        if response.status_code != 200:
            raise YouTubePublishingError('YouTube video verification failed (HTTP %s).' % response.status_code)
        items = response.json().get('items') or []
        if len(items) != 1 or items[0].get('id') != video_id:
            raise YouTubePublishingError('YouTube video was not found on the connected channel.')
        channel = self.publisher.connection().channel_id
        if not channel or (items[0].get('snippet') or {}).get('channelId') != channel:
            raise YouTubePublishingError('Connected channel does not own the video.')
        return items[0]

    async def _update_privacy(self, video_id: str, *, publish_at=None) -> None:
        status = {'privacyStatus': 'private'}
        if publish_at is not None:
            status['publishAt'] = publish_at.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
        token = await self.publisher._access_token()
        async with httpx.AsyncClient(timeout=self.publisher.settings.youtube_request_timeout_seconds) as client:
            response = await client.put('https://www.googleapis.com/youtube/v3/videos',
                params={'part': 'status'},
                headers={'Authorization': f'Bearer {token}'},
                json={'id': video_id, 'status': status})
        if response.status_code != 200:
            raise YouTubePublishingError('YouTube status update failed (HTTP %s): %s' % (response.status_code, response.text[:400]))

    async def stage(self, original_id: str, content: bytes, *, expected_sha256: str) -> dict:
        if not content or len(content) > MAX_BYTES:
            raise YouTubePublishingError('Replacement MP4 must be between 1 byte and 64 MiB.')
        if b'ftyp' not in content[:32]:
            raise YouTubePublishingError('Invalid MP4 header.')
        digest = hashlib.sha256(content).hexdigest()
        if digest != expected_sha256.lower():
            raise YouTubePublishingError('MP4 SHA-256 does not match the supplied checksum.')
        original = self.publisher.get(original_id)
        if (original.status != YouTubePublishStatus.SCHEDULED or not original.youtube_video_id or
                original.superseded_by_publication_id or not original.publish_at or original.publish_at <= now() + timedelta(minutes=30)):
            raise YouTubePublishingError('Only an active future scheduled publication (30+ min away) can be replaced.')
        remote = await self._youtube_video(original.youtube_video_id)
        if (remote.get('status') or {}).get('privacyStatus') != 'private':
            raise YouTubePublishingError('Original video is not private on YouTube; replacement blocked.')
        job_id = self._job_id(original_id, digest)
        previous = self.jobs.load(job_id)
        if previous:
            return {**previous, 'idempotent': True}
        # Persist intent BEFORE uploading. Repeated calls must not start an additional upload.
        new_id = 'ytpub_' + uuid4().hex
        job = {'job_id': job_id, 'original_publication_id': original_id, 'replacement_publication_id': new_id,
               'sha256': digest, 'phase': 'UPLOAD_PENDING', 'scheduled_at': original.publish_at.isoformat(),
               'created_at': now().isoformat(), 'error': None}
        # Atomically create the intent, preventing concurrent requests with the same digest.
        ref = self.jobs._collection().document(job_id)
        try:
            ref.create({'payload_json': __import__('json').dumps(job), 'schema_version': 2, 'storage_mode': 'inline-json-v1'})
        except Exception:
            previous = self.jobs.load(job_id)
            if previous:
                return {**previous, 'idempotent': True}
            raise
        new_pub = original.model_copy(deep=True)
        new_pub.publication_id = new_id
        new_pub.youtube_video_id = None
        new_pub.youtube_url = None
        new_pub.status = YouTubePublishStatus.UPLOADING
        new_pub.publish_at = None
        new_pub.privacy_status = 'private'
        new_pub.published_at = None
        new_pub.public_confirmed_at = None
        new_pub.public_release_at = None
        new_pub.public_release_time_source = None
        new_pub.master_fingerprint = 'replacement:' + digest
        new_pub.upload_session_uri = None
        new_pub.upload_bytes_total = 0
        new_pub.upload_bytes_committed = 0
        new_pub.upload_started_at = None
        new_pub.upload_completed_at = None
        # Hide the staged private video from list()/latest_for_recommendation()
        # and from autonomy_tick until the user explicitly activates it.
        new_pub.superseded_by_publication_id = original_id
        new_pub.superseded_at = None
        new_pub.created_at = now()
        new_pub.error = None
        self.publisher._save_pub(new_pub)
        # This direct private upload never uses the old package asset and never runs Veo.
        with tempfile.TemporaryDirectory(prefix='reviveai-ytrepl-') as directory:
            path = Path(directory) / 'replacement.mp4'
            path.write_bytes(content)
            draft = __import__('app.services.publishing_assistant_service', fromlist=['publishing_draft_store']).publishing_draft_store.get(original.publishing_draft_id)
            try:
                await self.publisher._create_upload_session(new_pub, path, draft)
                response = await self.publisher._upload_from_offset(new_pub, path, 0)
                if response.status_code not in (200, 201):
                    raise YouTubePublishingError('Replacement upload not confirmed; HTTP %s. Do not retry the upload automatically.' % response.status_code)
                new_pub = self.publisher._finish_upload_response(new_pub, response)
                await self._youtube_video(new_pub.youtube_video_id)
            except Exception as exc:
                job['phase'] = 'UPLOAD_RECONCILIATION_REQUIRED'
                job['error'] = f'{type(exc).__name__}: {str(exc)[:400]}'
                self.jobs.save(job_id, job)
                raise
        job['phase'] = 'READY_FOR_CONFIRMATION'
        job['replacement_youtube_video_id'] = new_pub.youtube_video_id
        job['error'] = None
        self.jobs.save(job_id, job)
        return job

    async def commit(self, original_id: str, digest: str, *, confirm: bool) -> dict:
        if not confirm:
            raise YouTubePublishingError('Explicit confirmation is required.')
        job_id = self._job_id(original_id, digest)
        job = self.jobs.load(job_id)
        if not job or job.get('phase') not in {'READY_FOR_CONFIRMATION', 'ACTIVATING', 'COMPLETED'}:
            raise YouTubePublishingError('No verified staged replacement exists for this publication and SHA-256.')
        if job['phase'] == 'COMPLETED':
            return job
        owner = 'replacement:' + uuid4().hex
        if not youtube_publication_claim_service.acquire_upload_lease(publication_id=original_id, owner=owner, lease_seconds=180):
            raise YouTubePublishingError('Another publication operation holds the lock; retry later.')
        try:
            original = self.publisher.get(original_id)
            replacement = self.publisher.get(job['replacement_publication_id'])
            if original.superseded_by_publication_id not in (None, replacement.publication_id):
                raise YouTubePublishingError('Original publication already superseded by another replacement.')
            if original.publish_at is None or original.publish_at <= now() + timedelta(minutes=15):
                raise YouTubePublishingError('Too close to the scheduled release; replacement requires manual intervention.')
            old_remote = await self._youtube_video(original.youtube_video_id)
            new_remote = await self._youtube_video(replacement.youtube_video_id)
            if (new_remote.get('status') or {}).get('privacyStatus') != 'private':
                raise YouTubePublishingError('Replacement is not private.')
            job['phase'] = 'ACTIVATING'
            self.jobs.save(job_id, job)
            # First remove the old public schedule. Never allow two scheduled releases.
            if (old_remote.get('status') or {}).get('publishAt'):
                await self._update_privacy(original.youtube_video_id)
            await self._update_privacy(replacement.youtube_video_id, publish_at=original.publish_at)
            verified = await self._youtube_video(replacement.youtube_video_id)
            actual_schedule = (verified.get('status') or {}).get('publishAt')
            if not actual_schedule:
                raise YouTubePublishingError('Replacement schedule was not verified. Original is still preserved privately.')
            replacement.superseded_by_publication_id = None
            replacement.superseded_at = None
            replacement.publish_at = original.publish_at
            replacement.status = YouTubePublishStatus.SCHEDULED
            replacement.schedule_reason = 'Explicitly approved replacement of ' + original_id
            self.publisher._save_pub(replacement)
            original.superseded_by_publication_id = replacement.publication_id
            original.superseded_at = now()
            original.publish_at = None
            original.privacy_status = 'private'
            self.publisher._save_pub(original)
            record = autopilot_state_store.get()
            if record and record.session.currentPublicationId == original_id:
                session = record.session.model_copy(deep=True)
                session.currentPublicationId = replacement.publication_id
                session.updatedAt = now().isoformat()
                session.message = 'Replacement video is scheduled; awaiting its public release before learning.'
                try:
                    autopilot_state_store.save(session, expected_revision=record.revision)
                except AutopilotStateConflictError:
                    raise YouTubePublishingError('YouTube replacement is scheduled, but Autopilot revision changed. Retry commit to reconcile.')
            job['phase'] = 'COMPLETED'
            job['error'] = None
            self.jobs.save(job_id, job)
            return job
        finally:
            youtube_publication_claim_service.release_upload_lease(publication_id=original_id, owner=owner)
