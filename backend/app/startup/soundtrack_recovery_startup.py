"""
Startup registration for soundtrack recovery worker.
"""


def initialize_soundtrack_recovery(
    app,
    recovery_worker,
):
    app.state.soundtrack_recovery_worker = recovery_worker

    return recovery_worker
