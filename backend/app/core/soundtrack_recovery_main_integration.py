"""
Helper for attaching soundtrack recovery lifecycle to application startup.
"""


def attach_soundtrack_recovery_lifespan(
    app,
    lifespan_handler,
):
    app.state.soundtrack_recovery_lifespan = (
        lifespan_handler
    )

    return app
