"""
Schema helpers for persisted soundtrack references.
"""

from typing import Optional


class SoundtrackReference:

    def __init__(
        self,
        soundtrack_id: Optional[str] = None,
        storage_path: Optional[str] = None,
        source: Optional[str] = None,
    ):
        self.soundtrack_id = soundtrack_id
        self.storage_path = storage_path
        self.source = source

    def to_dict(self):
        return {
            "soundtrack_id": self.soundtrack_id,
            "storage_path": self.storage_path,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            soundtrack_id=data.get("soundtrack_id"),
            storage_path=data.get("storage_path"),
            source=data.get("source"),
        )
