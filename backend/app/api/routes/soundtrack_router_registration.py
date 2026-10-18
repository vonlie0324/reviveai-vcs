
"""
Router registration helper for cloud soundtrack endpoints.

Use this in application startup/router composition
to replace legacy soundtrack route registration.
"""

from app.api.routes.soundtrack_cloud_routes import (
    list_soundtracks,
    resolve_soundtrack,
    delete_soundtrack,
)


def register_cloud_soundtrack_routes(app, adapter):
    """
    Registers cloud-backed soundtrack handlers.
    """

    app.state.soundtrack_adapter = adapter

    return {
        "list": lambda channel_id=None:
            list_soundtracks(adapter, channel_id),
        "resolve": lambda track_id:
            resolve_soundtrack(adapter, track_id),
        "delete": lambda track_id:
            delete_soundtrack(adapter, track_id),
    }
