"""Optional authenticated remote WhisperX aligner; fail closed if unavailable."""
from __future__ import annotations
import os
import re
import wave
from pathlib import Path
from difflib import SequenceMatcher

from app.services.speech_verified_alignment import _words, inspect_word_offsets


def force_align_voice_wav(wav_path: Path, transcript: str):
    url = os.environ.get('REVIVEAI_FORCED_ALIGN_URL', '').rstrip('/')
    if not url.startswith('https://'):
        raise ValueError('REVIVEAI_FORCED_ALIGN_URL must be configured as HTTPS')
    import requests
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token
    with wave.open(str(wav_path), 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
            raise ValueError('Forced alignment requires 16 kHz mono PCM16 WAV')
        duration = wav.getnframes() / wav.getframerate()
    if not 0 < duration <= 30:
        raise ValueError('Unexpected narration duration')
    audience = os.environ.get('REVIVEAI_FORCED_ALIGN_AUDIENCE') or url
    token = id_token.fetch_id_token(Request(), audience)
    r = requests.post(url + '/align', headers={'Authorization': f'Bearer {token}'},
                      files={'audio': (wav_path.name, wav_path.read_bytes(), 'audio/wav')},
                      data={'transcript': transcript}, timeout=(10, 110))
    r.raise_for_status()
    data = r.json()
    raw = data.get('words')
    if not isinstance(raw, list) or not raw or len(raw) > 100:
        raise ValueError('Forced alignment worker supplied no usable words')
    recognized = []
    for w in raw:
        if not isinstance(w, dict) or not all(k in w for k in ('word','start','end')):
            raise ValueError('Missing forced word timing')
        recognized.append((str(w['word']), float(w['start']), float(w['end'])))
    expected = _words(transcript)
    actual = [tok for word, _, _ in recognized for tok in _words(word)]
    similarity = SequenceMatcher(None, expected, actual).ratio() if expected and actual else 0
    if similarity < .90 or len(expected) != len(actual):
        raise ValueError(f'Forced transcript does not match approved text ({similarity:.3f})')
    recognized, issues = inspect_word_offsets(recognized, duration, overlap_tolerance=0)
    if issues:
        raise ValueError(f'Forced word offsets invalid: {issues[:3]}')
    cues=[]
    for i in range(0,len(recognized),5):
        chunk=recognized[i:i+5]
        cues.append((chunk[0][1], chunk[-1][2], ' '.join(w[0] for w in chunk)))
    return cues, {'method':'WHISPERX_FORCED_ALIGNMENT','recognized_words':len(actual),
                  'transcript_match_ratio':round(similarity,4),'timestamps_valid':True,
                  'duration_seconds':duration,'worker_model':data.get('model','unknown')}
