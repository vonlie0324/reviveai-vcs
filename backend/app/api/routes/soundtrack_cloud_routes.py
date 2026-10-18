
"""
Cloud-backed soundtrack API handlers.

These handlers are intended to replace direct usage of
local soundtrack catalog services.
"""

from app.api.routes.cloud_soundtrack_adapter import (
    SoundtrackRouteCloudAdapter,
)


def list_soundtracks(adapter: SoundtrackRouteCloudAdapter, channel_id=None):
    return [
        track
        for track in adapter.list(channel_id)
    ]


def resolve_soundtrack(adapter: SoundtrackRouteCloudAdapter, track_id):
    return adapter.resolve(track_id)


def delete_soundtrack(adapter: SoundtrackRouteCloudAdapter, track_id):
    return adapter.remove(track_id)
