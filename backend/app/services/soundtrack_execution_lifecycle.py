"""
Lifecycle helper for soundtrack execution state.
"""


class SoundtrackExecutionLifecycle:

    def start(self, job_state, context):
        return {
            **job_state,
            "soundtrack_execution": {
                "status": "READY",
                "soundtrack_id": context.soundtrack_id,
                "storage_path": context.storage_path,
            },
        }

    def mark_processing(self, job_state):
        state = dict(job_state)
        state.setdefault("soundtrack_execution", {})
        state["soundtrack_execution"]["status"] = "PROCESSING"
        return state

    def complete(self, job_state):
        state = dict(job_state)
        state.setdefault("soundtrack_execution", {})
        state["soundtrack_execution"]["status"] = "COMPLETED"
        return state

    def fail(self, job_state, error):
        state = dict(job_state)
        state.setdefault("soundtrack_execution", {})
        state["soundtrack_execution"].update(
            {
                "status": "FAILED",
                "error": str(error),
            }
        )
        return state
