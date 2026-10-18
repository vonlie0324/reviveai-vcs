"""
Application lifecycle integration for soundtrack recovery.
"""


async def start_soundtrack_recovery(app, recovery_scheduler):
    app.state.soundtrack_recovery_scheduler = recovery_scheduler


async def stop_soundtrack_recovery(app):
    app.state.soundtrack_recovery_scheduler = None
