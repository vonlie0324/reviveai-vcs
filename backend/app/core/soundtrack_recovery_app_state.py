"""
Typed access helper for soundtrack recovery runtime state.
"""


def get_soundtrack_recovery_runtime(app):
    return getattr(
        app.state,
        "soundtrack_recovery_runtime",
        None,
    )
