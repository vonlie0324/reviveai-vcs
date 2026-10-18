"""
Application initializer for soundtrack recovery runtime.
"""


def initialize_soundtrack_recovery_runtime(
    app,
    runner,
):
    app.state.soundtrack_recovery_runner = runner
    return runner
