"""Speech-grounded phrase timestamps using voice-only PCM and Google Speech-to-Text.

Never treats storyboard estimates or approximate text matching as speech-verified.
"""
from __future__ import annotations

import re
import wave
from difflib import SequenceMatcher
from pathlib import Path


_NUMBER_WORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10"}


def _words(text: str) -> list[str]:
    # Only exact, unambiguous single-digit equivalents; do not rewrite subtitle text.
    return [_NUMBER_WORDS.get(token, token) for token in re.findall(r"[a-z0-9']+", text.lower())]


def inspect_word_offsets(recognized: list[tuple[str, float, float]], duration: float, *, overlap_tolerance: float = 0.025):
    """Validate offsets; repair only sub-25ms boundary rounding overlaps.

    Never fabricate timestamps, stretch end times, or silently accept invalid words.
    """
    corrected = []
    issues = []
    previous_end = 0.0
    for index, (word, start, end) in enumerate(recognized):
        original_start = start
        reason = None
        if not (0 <= start < end <= duration + 0.05):
            reason = 'OUT_OF_RANGE_OR_NONPOSITIVE_DURATION'
        elif start < previous_end:
            if previous_end - start <= overlap_tolerance and previous_end < end:
                start = previous_end
            else:
                reason = 'WORD_OVERLAP'
        if reason:
            issues.append({'index': index, 'word': word, 'reason': reason, 'start': round(original_start, 5), 'end': round(end, 5), 'previous_end': round(previous_end, 5), 'duration': round(duration, 5)})
        corrected.append((word, start, end))
        previous_end = max(previous_end, end)
    return corrected, issues



def validate_recognized_words(transcript: str, recognized: list[tuple[str, float, float]], *, duration: float, minimum_similarity: float = 0.90) -> bool:
    expected = _words(transcript)
    actual = [token for word, _, _ in recognized for token in _words(word)]
    if not expected or not actual or SequenceMatcher(None, expected, actual).ratio() < minimum_similarity:
        return False
    _, issues = inspect_word_offsets(recognized, duration)
    return not issues


def _offset_seconds(value) -> float:
    if hasattr(value, "total_seconds"):
        return float(value.total_seconds())
    if hasattr(value, "seconds") and hasattr(value, "nanos"):
        return float(value.seconds) + float(value.nanos) / 1e9
    raise ValueError("Unsupported Google STT duration value")


def align_voice_wav(wav_path: Path, transcript: str, *, language_code: str = 'en-US', use_hints: bool = False, recognition_model: str | None = None) -> tuple[list[tuple[float, float, str]], dict]:
    """Align short, mono, 16-kHz PCM shot audio. Raises on unavailable/low-confidence recognition."""
    from google.cloud import speech_v1 as speech
    with wave.open(str(wav_path), 'rb') as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != 16000:
            raise ValueError('Expected 16 kHz mono 16-bit PCM narration WAV')
        duration = wav.getnframes() / wav.getframerate()
        data = wav.readframes(wav.getnframes())
    if not data or duration > 59:
        raise ValueError('Missing or too-long narration for synchronous speech alignment')
    hints = [speech.SpeechContext(phrases=[transcript], boost=12.0)] if use_hints else []
    response = speech.SpeechClient().recognize(
        config=speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000, language_code=language_code,
            enable_word_time_offsets=True, speech_contexts=hints,
            **({"model": recognition_model} if recognition_model else {}),
        ),
        audio=speech.RecognitionAudio(content=data),
        timeout=45,
    )
    recognized = []
    confidence = []
    for result in response.results:
        if not result.alternatives:
            continue
        alternative = result.alternatives[0]
        if alternative.confidence:
            confidence.append(float(alternative.confidence))
        for word in alternative.words:
            start = _offset_seconds(word.start_time)
            end = _offset_seconds(word.end_time)
            recognized.append((word.word.strip(), start, end))
    expected = _words(transcript)
    actual = [token for word, _, _ in recognized for token in _words(word)]
    similarity = SequenceMatcher(None, expected, actual).ratio() if expected and actual else 0.0
    original_recognized = recognized
    recognized, offset_issues = inspect_word_offsets(recognized, duration)
    boundary_adjustments = sum(1 for old, new in zip(original_recognized, recognized) if old[1] != new[1])
    offsets_valid = not offset_issues
    if similarity < 0.90 or not offsets_valid:
        import json
        raise ValueError(json.dumps({
            'failure_code': 'TRANSCRIPT_MISMATCH' if similarity < 0.90 else 'INVALID_WORD_OFFSETS',
            'expected_words': len(expected), 'recognized_words': len(actual),
            'recognized_transcript': ' '.join(word for word, _, _ in recognized)[:300],
            'transcript_match_ratio': round(similarity, 4),
            'timestamps_valid': offsets_valid, 'offset_issues': offset_issues[:20], 'recognition_hints': use_hints, 'recognition_model': recognition_model or 'default',
        }))
    if confidence and min(confidence) < 0.75:
        raise ValueError('Speech recognition confidence below minimum threshold')
    cues = []
    for i in range(0, len(recognized), 5):
        group = recognized[i:i + 5]
        cues.append((group[0][1], group[-1][2], ' '.join(w[0] for w in group)))
    return cues, {'recognized_words': len(recognized), 'confidence_min': min(confidence) if confidence else None, 'duration_seconds': duration, 'method': 'GOOGLE_STT_WORD_OFFSETS', 'transcript_match_ratio': round(similarity,4), 'recognition_hints': use_hints, 'timestamps_valid': True, 'boundary_adjustments': boundary_adjustments, 'recognition_model': recognition_model or 'default'}
