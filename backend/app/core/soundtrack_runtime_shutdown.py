"""
Shutdown handling helpers for soundtrack runtime.
"""


async def shutdown_soundtrack_runtime(
    app,
):
    manager = getattr(
        app.state,
        "soundtrack_recovery_lifespan_manager",
        None,
    )

    if manager:
        await manager.shutdown()

    app.state.soundtrack_recovery_lifespan_manager = None
