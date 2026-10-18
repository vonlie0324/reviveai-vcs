"""
FastAPI registration helpers for soundtrack recovery runtime.
"""


def register_soundtrack_recovery(
    app,
    lifespan_manager,
):
    app.state.soundtrack_recovery_lifespan_manager = (
        lifespan_manager
    )

    return app
