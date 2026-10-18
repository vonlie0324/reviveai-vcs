"""
Worker-level soundtrack checkpoint manager.

Used by background workers to persist soundtrack execution state.
"""


class SoundtrackWorkerCheckpointManager:

    def __init__(
        self,
        lifecycle,
        checkpoint_store=None,
    ):
        self.lifecycle = lifecycle
        self.checkpoint_store = checkpoint_store

    def start(
        self,
        job_id,
        job_state,
        context,
    ):
        state = self.lifecycle.start(
            job_state,
            context,
        )

        self._save(job_id, state)

        return state

    def processing(
        self,
        job_id,
        job_state,
    ):
        state = self.lifecycle.mark_processing(
            job_state
        )

        self._save(job_id, state)

        return state

    def complete(
        self,
        job_id,
        job_state,
    ):
        state = self.lifecycle.complete(
            job_state
        )

        self._save(job_id, state)

        return state

    def fail(
        self,
        job_id,
        job_state,
        error,
    ):
        state = self.lifecycle.fail(
            job_state,
            error,
        )

        self._save(job_id, state)

        return state

    def _save(
        self,
        job_id,
        state,
    ):
        if self.checkpoint_store:
            self.checkpoint_store.save(
                job_id,
                state,
            )
