"""
Runtime initialization helper.
"""

from app.services.soundtrack_runtime_provider import (
    SoundtrackRuntimeProvider,
)


def initialize_soundtrack_runtime(app, settings):
    provider = SoundtrackRuntimeProvider(settings)

    app.state.soundtrack_repository = (
        provider.get_repository()
    )

    app.state.soundtrack_storage = (
        provider.get_storage()
    )

    return provider
