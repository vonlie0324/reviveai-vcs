"""Explicitly opt-in isolated REAL cloud GCS/Firestore semantics probe.

Not a production recovery runner. No reads/writes to ReviveAI production resources.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

PROD_PROJECT = 'ai-projects-250716'
PROD_DB = 'reviveai-prod'
PROD_BUCKET = 'reviveai'

def ensure_safe(project: str, database: str, bucket: str, prefix: str):
    for key, value in {'project': project, 'database': database, 'bucket': bucket, 'prefix': prefix}.items():
        if not value or not value.strip():
            raise ValueError(f'{key} must be provided explicitly')
    if project.lower() == PROD_PROJECT or database.lower() in (PROD_DB, '(default)') or bucket.lower() == PROD_BUCKET:
        raise ValueError('REFUSED: production project/database/bucket or default database')
    if 'prod' in project.lower() or 'prod' in database.lower() or 'prod' in bucket.lower():
        raise ValueError('REFUSED: suspicious production-like resource')
    if not prefix.startswith('reviveai-recovery-staging-tests/') or '..' in prefix or prefix.startswith('/'):
        raise ValueError('REFUSED: prefix must be reviveai-recovery-staging-tests/<isolated-run>')
    if os.environ.get('FIRESTORE_EMULATOR_HOST'):
        raise ValueError('REFUSED: FIRESTORE_EMULATOR_HOST is set; unset for REAL staging probe')

def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def run(args):
    ensure_safe(args.project, args.database, args.bucket, args.prefix)
    base = {'status':'DRY_RUN_NO_CLOUD_CLIENTS', 'project':args.project, 'database':args.database,
            'bucket':args.bucket, 'prefix':args.prefix, 'production_access':False,
            'operations': ['gcs.create_only_then_generation_specific_read_verify',
                           'firestore.create_synthetic_doc_then_transactional_compare_and_set',
                           'firestore.reject_stale_expected_generation',
                           'gcs.reject_second_create_on_existing_name'],
            'executed_cloud_writes':0}
    if not args.execute_staging_writes:
        return base
    if args.confirm != 'STAGING_ONLY_I_AUTHORIZE_TEST_WRITES':
        raise ValueError('REFUSED: missing staging-only write authorization confirmation')
    if not args.prefix.endswith('/'):
        raise ValueError('REFUSED: staging prefix must end with /')
    # Only import cloud libraries after resource validation and explicit opt-in.
    from google.cloud import firestore, storage
    from google.api_core.exceptions import PreconditionFailed, Conflict
    client = firestore.Client(project=args.project, database=args.database)
    gcs = storage.Client(project=args.project)
    bucket = gcs.bucket(args.bucket)
    token = secrets.token_hex(16)
    doc_path = f'reviveai_recovery_staging_tests/{token}'
    object_name = f'{args.prefix}{token}/probe.bin'
    payload = f'reviveai-staging-probe:{token}'.encode('ascii')
    result = {**base, 'status':'STARTED', 'firestore_document':doc_path,
              'gcs_object':f'gs://{args.bucket}/{object_name}', 'expected_sha256':sha256(payload)}
    ref = client.document(doc_path)
    blob = bucket.blob(object_name)
    # Write intent locally first: no destructive cleanup on unexpected error.
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(result,indent=2),encoding='utf-8')
    # Upload with GCS generation=0 create-only guarantee; server establishes generation.
    blob.upload_from_string(payload,content_type='application/octet-stream',if_generation_match=0)
    blob.reload()
    generation = int(blob.generation)
    remote = bucket.blob(object_name,generation=generation).download_as_bytes()
    if sha256(remote) != sha256(payload):
        raise RuntimeError('Remote GCS content hash mismatch')
    result['gcs_generation'] = generation
    result['gcs_hash_valid'] = True
    collision_rejected = False
    try:
        bucket.blob(object_name).upload_from_string(b'BAD_OVERWRITE',if_generation_match=0)
    except (PreconditionFailed,Conflict):
        collision_rejected = True
    if not collision_rejected:
        raise RuntimeError('GCS create-only collision was not rejected')
    result['gcs_create_only_collision_rejected'] = True
    # Create a synthetic document in the isolated staging database.
    ref.create({'generation':1,'state':'INTENT','run_token':token})
    @firestore.transactional
    def cas(tx, expected):
        snap = ref.get(transaction=tx)
        data = snap.to_dict() or {}
        if data.get('generation') != expected or data.get('run_token') != token:
            return False
        tx.update(ref,{'generation':expected+1,'state':'STAGED_VERIFIED'})
        return True
    if not cas(client.transaction(),1):
        raise RuntimeError('Staging Firestore CAS unexpectedly failed')
    if cas(client.transaction(),1):
        raise RuntimeError('Stale Firestore CAS unexpectedly succeeded')
    final = ref.get().to_dict() or {}
    if final.get('generation') != 2 or final.get('state') != 'STAGED_VERIFIED':
        raise RuntimeError('Staging Firestore final state mismatch')
    result.update(status='STAGING_CLOUD_INTERFACE_PASSED',firestore_cas=True,
                  stale_cas_rejected=True,executed_cloud_writes=3,
                  cleanup='NOT AUTOMATIC: synthetic document and object retained for audit; operator cleanup only')
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['project','database','bucket','prefix']:
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--report',type=Path)
    parser.add_argument('--execute-staging-writes',action='store_true')
    parser.add_argument('--confirm',default='')
    args=parser.parse_args()
    try:
        result=run(args)
        print(json.dumps(result,indent=2))
        if args.report:
            args.report.parent.mkdir(parents=True,exist_ok=True)
            args.report.write_text(json.dumps(result,indent=2),encoding='utf-8')
    except Exception as exc:
        print(f'STAGING PROBE FAILED CLOSED: {type(exc).__name__}: {exc}',file=sys.stderr)
        raise SystemExit(2)

if __name__=='__main__': main()
