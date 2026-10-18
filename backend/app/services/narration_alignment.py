"""Phrase-level captions aligned to Google TTS SSML mark timepoints.

No automatic speech recognition is involved: exact phrases are taken from the
approved narration script, and boundaries come from synthesis timepoints.
"""
from __future__ import annotations

import re
from html import escape
from dataclasses import dataclass


@dataclass(frozen=True)
class Phrase:
    text: str
    mark: str


def split_phrases(text: str, max_words: int = 6) -> list[Phrase]:
    words = " ".join(text.split()).split(" ") if text.strip() else []
    chunks: list[str] = []
    buf: list[str] = []
    for word in words:
        buf.append(word)
        if len(buf) >= max_words or (len(buf) >= 3 and re.search(r'[.!?;:]$', word)):
            chunks.append(" ".join(buf)); buf = []
    if buf:
        chunks.append(" ".join(buf))
    return [Phrase(chunk, f"revai_p{i:03d}") for i, chunk in enumerate(chunks)]


def ssml_with_marks(phrases: list[Phrase]) -> str:
    return "<speak>" + " ".join(f'<mark name="{p.mark}"/>{escape(p.text)}' for p in phrases) + "</speak>"


def timed_phrases(phrases: list[Phrase], timepoints: dict[str, float], *, shot_start: float, shot_duration: float) -> list[tuple[float, float, str]]:
    """Return only provider-grounded, strictly increasing cue boundaries."""
    if not phrases or any(p.mark not in timepoints for p in phrases):
        return []
    values = [float(timepoints[p.mark]) for p in phrases]
    if values[0] < 0 or any(a >= b for a, b in zip(values, values[1:])):
        return []
    if values[-1] >= shot_duration:
        return []  # narration is cropped; never present unspoken text as speech-aligned
    result = []
    for i, phrase in enumerate(phrases):
        start = shot_start + values[i]
        end = shot_start + (values[i + 1] if i + 1 < len(values) else shot_duration)
        if end - start < 0.10:
            return []
        result.append((start, end, phrase.text))
    return result


def write_srt(path, cues: list[tuple[float, float, str]]) -> bool:
    def stamp(value: float) -> str:
        ms = max(0, round(value * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    if not cues:
        return False
    rows = []
    for i, (start, end, text) in enumerate(cues, 1):
        if end <= start:
            raise ValueError("Invalid caption timing")
        rows.extend([str(i), f"{stamp(start)} --> {stamp(end)}", text, ""])
    path.write_text("\n".join(rows), encoding="utf-8")
    return True
