"""
Shared soundtrack persistence fields.

Used by media and assembly job models when adding
cloud soundtrack references.
"""

from typing import Optional


class SoundtrackJobFields:
    soundtrack_id: Optional[str] = None
    soundtrack_storage_path: Optional[str] = None
    soundtrack_source: Optional[str] = None
