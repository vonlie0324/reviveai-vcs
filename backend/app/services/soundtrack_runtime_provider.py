"""
Runtime provider for cloud-backed soundtrack services.
"""

from app.services.soundtrack_service_factory import (
    create_soundtrack_repository,
    create_cloud_storage_service,
)


class SoundtrackRuntimeProvider:

    def __init__(self, settings):
        self.repository = create_soundtrack_repository()
        self.storage = create_cloud_storage_service(
            settings.soundtrack_output_gcs_uri
        )

    def get_repository(self):
        return self.repository

    def get_storage(self):
        return self.storage
