"""
Binding layer for final assembly job persistence.
"""


from app.services.media_job_soundtrack_persistence import (
    persist_job_soundtrack,
    restore_job_soundtrack,
)


class FinalAssemblyJobSoundtrackPersistenceBinding:

    def attach_asset(
        self,
        assembly_data: dict,
        soundtrack_asset: dict | None,
    ):
        return persist_job_soundtrack(
            assembly_data,
            soundtrack_asset,
        )

    def restore_asset(
        self,
        assembly_data: dict,
    ):
        return restore_job_soundtrack(
            assembly_data
        )
