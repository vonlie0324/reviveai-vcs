"""V15 offline coordination contract. Zero network/cloud access. NOT production code."""
from __future__ import annotations
from dataclasses import dataclass, replace
from typing import Optional

class UnsafeRecovery(RuntimeError): pass

@dataclass(frozen=True)
class State:
    revision: int = 10468
    audio_stage: str = 'RENDERING'
    audio_result: bool = False
    audio_checkpoint: bool = False
    publication: Optional[str] = None
    queue_status: str = 'RUNNING'
    execution_owner: str = 'BACKEND'
    supervisor_owner: Optional[str] = None
    supervisor_expired: bool = True
    maintenance_owner: Optional[str] = None
    maintenance_generation: int = 0
    maintenance_expired: bool = True
    job_generation: int = 1
    completed: bool = False
    review_status: Optional[str] = None
    journal_verified: bool = False
    assets_verified: bool = False

class Simulator:
    """Atomic transitions represent proposed single-transaction operations.

    Deliberately NOT a Firestore implementation. No real locks or uploads.
    """
    def __init__(self, state: State | None = None): self.state = state or State()

    def supervisor_acquire(self, owner: str) -> bool:
        s=self.state
        if s.maintenance_owner and not s.maintenance_expired: return False
        if s.queue_status!='RUNNING' or s.execution_owner!='BACKEND': return False
        if s.supervisor_owner and not s.supervisor_expired and s.supervisor_owner!=owner: return False
        self.state=replace(s,supervisor_owner=owner,supervisor_expired=False)
        return True

    def maintenance_acquire(self, owner: str, expected_revision: int) -> int:
        s=self.state
        if not owner or s.revision!=expected_revision or s.queue_status!='RUNNING' or s.execution_owner!='BACKEND': raise UnsafeRecovery('session changed')
        if s.publication or s.audio_stage!='RENDERING' or s.audio_result or s.audio_checkpoint or s.completed: raise UnsafeRecovery('job changed')
        if s.supervisor_owner and not s.supervisor_expired: raise UnsafeRecovery('live supervisor lease')
        if s.maintenance_owner and not s.maintenance_expired: raise UnsafeRecovery('maintenance in progress')
        generation=s.maintenance_generation+1
        self.state=replace(s,maintenance_owner=owner,maintenance_generation=generation,maintenance_expired=False)
        return generation

    def maintenance_renew(self, owner: str, generation: int) -> bool:
        s=self.state
        return bool(s.maintenance_owner==owner and s.maintenance_generation==generation and not s.maintenance_expired)

    def mark_artifacts(self, owner: str, generation: int, *, journal_verified: bool, assets_verified: bool):
        if not self.maintenance_renew(owner,generation): raise UnsafeRecovery('lost maintenance claim')
        self.state=replace(self.state,journal_verified=journal_verified,assets_verified=assets_verified)

    def commit(self, owner: str, generation: int, expected_revision: int, expected_job_generation: int):
        s=self.state
        if not self.maintenance_renew(owner,generation): raise UnsafeRecovery('maintenance fence')
        if s.revision!=expected_revision or s.job_generation!=expected_job_generation: raise UnsafeRecovery('revision fence')
        if s.publication or s.audio_stage!='RENDERING' or s.audio_result or s.audio_checkpoint: raise UnsafeRecovery('job fence')
        if s.supervisor_owner and not s.supervisor_expired: raise UnsafeRecovery('supervisor fence')
        if not (s.journal_verified and s.assets_verified): raise UnsafeRecovery('unverified artifacts')
        self.state=replace(s,audio_stage='COMPLETED',audio_result=True,completed=True,review_status='NEEDS_REVIEW',job_generation=s.job_generation+1,maintenance_owner=None,maintenance_expired=True)

    def release(self, owner: str, generation: int) -> bool:
        s=self.state
        if not self.maintenance_renew(owner,generation): return False
        self.state=replace(s,maintenance_owner=None,maintenance_expired=True)
        return True
