"""Conservative, provider-agnostic decisions for resumable YouTube uploads.

A 308 response can report an already committed full media body without a
video id. Resending the body in that state risks duplicate/invalid submissions.
These decisions deliberately require reconciliation or human intervention.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class UploadProgress:
    committed: int
    total: int
    complete_without_video_id: bool


def parse_committed_bytes(range_header: Optional[str], total: int) -> UploadProgress:
    """Validate a 308 Range and compute the number of committed bytes.

    Per resumable upload protocol, Range: bytes=0-N represents N+1 bytes.
    An absent Range means zero bytes committed. Never trust an inconsistent
    server range to determine the next upload offset.
    """
    import re

    if total < 0:
        raise ValueError("Invalid upload length")
    if not range_header:
        committed = 0
    else:
        match = re.fullmatch(r"bytes=0-(\d+)", range_header.strip())
        if not match:
            raise ValueError("Unexpected YouTube resumable Range header")
        committed = int(match.group(1)) + 1
    if committed > total:
        raise ValueError("YouTube reported more committed bytes than the asset contains")
    return UploadProgress(
        committed=committed,
        total=total,
        complete_without_video_id=(total > 0 and committed == total),
    )
