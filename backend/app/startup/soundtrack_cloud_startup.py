
"""
FastAPI wiring helper for cloud soundtrack services.
"""

from app.api.routes.soundtrack_router_registration import (
    register_cloud_soundtrack_routes,
)


def initialize_cloud_soundtrack(app, adapter):
    """
    Attach cloud soundtrack services to application state.
    """

    app.state.soundtrack_adapter = adapter

    return register_cloud_soundtrack_routes(
        app,
        adapter,
    )
