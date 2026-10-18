
"""
Application patch helper.

Use from app.main.py after creating the FastAPI application.

Example:

from app.startup.cloud_soundtrack_application_patch import (
    setup_cloud_soundtrack,
)

setup_cloud_soundtrack(app)
"""

from app.api.dependencies.soundtrack_dependencies import (
    get_soundtrack_adapter,
)

from app.startup.soundtrack_cloud_startup import (
    initialize_cloud_soundtrack,
)


def setup_cloud_soundtrack(app):
    adapter = get_soundtrack_adapter()

    app.state.soundtrack_adapter = adapter

    return initialize_cloud_soundtrack(
        app,
        adapter,
    )
