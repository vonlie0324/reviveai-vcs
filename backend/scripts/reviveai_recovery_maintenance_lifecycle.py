"""Injected maintenance lifecycle for offline/emulator testing. No production entrypoint.

The supplied queue must implement the V16 acquire/renew/release methods. This
module never creates cloud clients, and deliberately does not publish or deploy.
"""
from __future__ import annotations
from dataclasses import dataclass
from threading import Event, Thread
from time import monotonic
from typing import Callable

class MaintenanceLost(RuntimeError):
    pass

@dataclass(frozen=True)
class Claim:
    namespace: str
    owner: str
    audio_job_id: str
    generation: int
    revision: int


def run_with_maintenance(queue, *, namespace: str, audio_job_id: str, owner: str,
                         expected_revision: int, operation: Callable[[Claim, Callable[[], None]], object],
                         lease_seconds: int = 120, heartbeat_seconds: float = 20):
    """Claim, renew and owner-check an injected recovery operation.

    Side effects in `operation` must use generation-fenced transactions and
    create-only staging. No thread can cancel an upload already in progress;
    failure of renewal blocks the next checkpoint and finalization transaction.
    """
    if not all((namespace, audio_job_id, owner)) or lease_seconds < 30:
        raise ValueError('invalid maintenance identity or lease')
    if not (0 < heartbeat_seconds < lease_seconds / 3):
        raise ValueError('heartbeat must be substantially shorter than lease')
    generation = queue.acquire_recovery_maintenance(namespace=namespace,
        audio_job_id=audio_job_id, owner=owner,
        expected_revision=expected_revision, lease_seconds=lease_seconds)
    if not isinstance(generation, int) or generation <= 0:
        raise MaintenanceLost('supervisor not quiescent or maintenance claim refused')
    claim = Claim(namespace, owner, audio_job_id, generation, expected_revision)
    stop = Event()
    lost = Event()
    started = monotonic()
    errors = []

    def heartbeat():
        while not stop.wait(heartbeat_seconds):
            try:
                if not queue.renew_recovery_maintenance(namespace=namespace, owner=owner,
                        generation=generation, lease_seconds=lease_seconds):
                    lost.set()
                    return
            except Exception as exc:
                errors.append(type(exc).__name__)
                lost.set()
                return

    thread = Thread(target=heartbeat, daemon=True, name='recovery-maintenance-heartbeat')
    thread.start()
    def checkpoint():
        if lost.is_set():
            raise MaintenanceLost('maintenance heartbeat failed: '+','.join(errors))
        # A fresh transactional lease renewal is the authoritative checkpoint.
        try:
            if not queue.renew_recovery_maintenance(namespace=namespace, owner=owner,
                    generation=generation, lease_seconds=lease_seconds):
                lost.set()
                raise MaintenanceLost('maintenance lease lost')
        except MaintenanceLost:
            raise
        except Exception as exc:
            lost.set()
            raise MaintenanceLost('maintenance check unavailable') from exc
        if lost.is_set():
            raise MaintenanceLost('maintenance heartbeat failed')

    try:
        checkpoint()
        result = operation(claim, checkpoint)
        checkpoint()
        return result
    finally:
        stop.set()
        thread.join(timeout=max(2.0, heartbeat_seconds + 1))
        # Release only the original owner+generation. If it fails, leave it to
        # expire, never forcibly clear another worker's claim.
        try:
            queue.release_recovery_maintenance(namespace=namespace,owner=owner,generation=generation)
        except Exception:
            pass


def run_staged_recovery(queue, db, bucket, *, namespace: str, audio_job_id: str,
                        owner: str, expected_revision: int, staged_kwargs: dict,
                        lease_seconds: int = 120, heartbeat_seconds: float = 20):
    """No cloud clients created. Inputs must have been separately verified.

    Production invocation is intentionally NOT exposed: this adapter has not
    undergone coordinated Cloud Run rollout or production staging verification.
    """
    def work(claim, checkpoint):
        from reviveai_recovery_orchestrator import stage_and_finalize
        identity = dict(staged_kwargs['identity'])
        if (identity.get('job_id') != claim.audio_job_id or
            identity.get('owner') != claim.owner or
            identity.get('revision') != claim.revision):
            raise MaintenanceLost('staging identity disagrees with maintenance claim')
        identity['generation'] = claim.generation
        kwargs = dict(staged_kwargs)
        kwargs['identity'] = identity
        kwargs['checkpoint'] = checkpoint
        return stage_and_finalize(db, bucket, **kwargs)
    return run_with_maintenance(queue, namespace=namespace, audio_job_id=audio_job_id,
        owner=owner, expected_revision=expected_revision, operation=work,
        lease_seconds=lease_seconds, heartbeat_seconds=heartbeat_seconds)
