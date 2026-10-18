"""
Lifespan registration helper for soundtrack recovery runtime.
"""


async def register_recovery_runtime(
    app,
    runtime_dependencies,
):
    app.state.soundtrack_recovery_dependencies = (
        runtime_dependencies
    )

    return runtime_dependencies


async def unregister_recovery_runtime(
    app,
):
    app.state.soundtrack_recovery_dependencies = None
