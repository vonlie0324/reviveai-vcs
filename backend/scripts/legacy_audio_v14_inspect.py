"""Explicitly authorized READ-ONLY inspection. No app imports and no writes."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

JOB = 'audio_821f2a568f804076b10fa4364793385c'
TENANT = '61cf44d3ae8277b1f9d2aa781d87e52d'


def iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def expiry_state(value, now):
    if not isinstance(value, datetime):
        return 'UNKNOWN'
    if value.tzinfo is None:
        return 'UNKNOWN_NAIVE_TIMESTAMP'
    return 'ACTIVE' if value > now else 'EXPIRED'


def summarize(audio, lock, queue, autopilot, now):
    payload = {}
    parse_error = None
    raw = audio.get('payload_json')
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError('payload_json is not an object')
        except (ValueError, TypeError) as exc:
            parse_error = type(exc).__name__
    elif audio.get('storage_mode') == 'gzip-chunks-v1':
        parse_error = 'CHUNKED_PAYLOAD_NOT_DECODED'
    else:
        parse_error = 'NO_INLINE_PAYLOAD'
    detail = payload.get('detail') or {}
    result = payload.get('result')
    checkpoint = detail.get('render_checkpoint')
    state_payload = {}
    state_raw = autopilot.get('payload_json')
    if isinstance(state_raw, str):
        try:
            state_payload = json.loads(state_raw)
        except (ValueError, TypeError):
            pass
    session = state_payload.get('session') or {}
    return {
        'read_at_utc': now.isoformat(),
        'write_operations_performed': 0,
        'production_commit_enabled': False,
        'audio_job': {
            'document_exists': bool(audio), 'storage_mode': audio.get('storage_mode', 'legacy-or-unspecified'),
            'schema_version': audio.get('schema_version'),
            'chunk_count': audio.get('chunk_count'), 'payload_parse_warning': parse_error,
            'job_id': payload.get('job_id'), 'stage': payload.get('stage'),
            'updated_at': payload.get('updated_at'), 'has_result': result is not None,
            'checkpoint_state': checkpoint.get('state') if isinstance(checkpoint, dict) else None,
            'source_visual_asset_id': detail.get('source_visual_asset_id')},
        'mux_lock': {'document_exists': bool(lock), 'owner_present': bool(lock.get('owner')),
                     'generation': lock.get('generation'), 'expires_at': iso(lock.get('expires_at')),
                     'expiry_state': expiry_state(lock.get('expires_at'), now)},
        'supervisor_queue': {'document_exists': bool(queue), 'status': queue.get('status'),
                             'execution_owner': queue.get('execution_owner'),
                             'revision': queue.get('revision'),
                             'lease_owner_present': bool(queue.get('lease_owner')),
                             'lease_expires_at': iso(queue.get('lease_expires_at')),
                             'lease_state': expiry_state(queue.get('lease_expires_at'), now),
                             'next_run_at': iso(queue.get('next_run_at'))},
        'autopilot_session': {'document_exists': bool(autopilot),
                              'storage_mode': autopilot.get('storage_mode', 'legacy-or-unspecified'),
                              'revision': state_payload.get('revision'),
                              'status': session.get('status'),
                              'executionOwner': session.get('executionOwner'),
                              'currentAudioJobId': session.get('currentAudioJobId'),
                              'currentPublicationId_present': bool(session.get('currentPublicationId'))},
        'interpretation': 'READ_ONLY_OBSERVATION_NOT_COMMIT_AUTHORIZATION',
        'warnings': ['Concurrent supervisor activity may change immediately after reads',
                     'Authoritative commit still requires transaction-level lease and revision fencing',
                     'Chunked payload not decoded by this inspector']
    }


def main():
    p = argparse.ArgumentParser(description='Read four explicitly selected production Firestore docs using GET only')
    p.add_argument('--project', required=True)
    p.add_argument('--database', required=True)
    p.add_argument('--tenant', required=True)
    p.add_argument('--audio-job-id', default=JOB)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--acknowledge-production-reads', action='store_true')
    a = p.parse_args()
    if not a.acknowledge_production_reads:
        p.error('Explicit --acknowledge-production-reads required')
    if os.getenv('FIRESTORE_EMULATOR_HOST'):
        p.error('FIRESTORE_EMULATOR_HOST is set: remove it for authoritative inspection')
    if a.project != 'ai-projects-250716' or a.database != 'reviveai-prod' or a.tenant != TENANT or a.audio_job_id != JOB:
        p.error('Project/database/tenant/audio ID does not match approved read-only inspection scope')
    if a.out.exists():
        p.error('Output file already exists; choose a new name (never overwrite)')
    from google.cloud import firestore
    db = firestore.Client(project=a.project, database=a.database)
    root = db.collection('reviveai_tenants').document(a.tenant)
    refs = [root.collection('audio_finishing_jobs').document(a.audio_job_id),
            root.collection('audio_mux_recovery_locks').document(a.audio_job_id),
            db.collection('reviveai_autopilot_supervisor').document(a.tenant),
            root.collection('autopilot_state').document('active_session')]
    data = []
    for ref in refs:
        snap = ref.get()  # single read per document; no mutations
        data.append(snap.to_dict() if snap.exists else {})
    report = summarize(*data, datetime.now(timezone.utc))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open('x', encoding='utf-8') as f:
        json.dump(report, f, indent=2, default=iso)
    print('V14: READ_ONLY_INSPECTION_COMPLETE_COMMIT_DISABLED')
    print('AUDIO:', report['audio_job'])
    print('MUX LOCK:', report['mux_lock'])
    print('SUPERVISOR QUEUE:', report['supervisor_queue'])
    print('AUTOPILOT SESSION:', report['autopilot_session'])
    print('REPORT:', a.out)
    print('4 DOCUMENT GETS; 0 WRITES; NO APP STARTUP; NO CLOUD RUN; NO YOUTUBE')

if __name__ == '__main__':
    main()
