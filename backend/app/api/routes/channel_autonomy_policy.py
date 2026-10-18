"""Authenticated channel policy and server-generated voice previews."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.core.firebase_auth import require_tenant_context
from app.services.channel_autonomy_policy import ChannelAutonomyPolicy, channel_policy_store
from app.services.channel_cost_estimator import estimate_channel_production

router = APIRouter(prefix='/api/v1/youtube/channel-policies', tags=['channel-policy'], dependencies=[Depends(require_tenant_context)])

class VoicePreviewRequest(BaseModel):
    voice_name: str = Field(min_length=5, max_length=120)


def _voices():
    try:
        from google.cloud import texttospeech
        client = texttospeech.TextToSpeechClient()
        results = client.list_voices(language_code='en-US').voices
        return [
            {'name': voice.name, 'gender': texttospeech.SsmlVoiceGender(voice.ssml_gender).name}
            for voice in results if voice.name.startswith('en-US-') and voice.ssml_gender in (
                texttospeech.SsmlVoiceGender.MALE, texttospeech.SsmlVoiceGender.FEMALE)
        ]
    except Exception as exc:
        raise HTTPException(status_code=503, detail='Google Cloud TTS voice catalog is unavailable.') from exc

@router.get('/cost-estimate')
def channel_cost_estimate(duration_seconds: int = 30, max_keyframe_attempts: int = 2):
    if not 6 <= duration_seconds <= 3600 or not 1 <= max_keyframe_attempts <= 5:
        raise HTTPException(status_code=422, detail='Invalid duration or attempt count')
    return estimate_channel_production(duration_seconds, max_keyframe_attempts)

@router.get('/voices')
def list_narrator_voices():
    return {'voices': _voices()}

@router.post('/voices/preview')
def preview_narrator_voice(request: VoicePreviewRequest):
    voices = _voices()
    if request.voice_name not in {v['name'] for v in voices}:
        raise HTTPException(status_code=422, detail='Voice is not supported for this catalog.')
    try:
        from google.cloud import texttospeech
        client = texttospeech.TextToSpeechClient()
        audio = client.synthesize_speech(
            input=texttospeech.SynthesisInput(text='Welcome to our channel. Today, we are exploring something extraordinary. Let us begin!'),
            voice=texttospeech.VoiceSelectionParams(language_code='en-US', name=request.voice_name),
            audio_config=texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3),
            timeout=20,
        ).audio_content
        return Response(content=audio, media_type='audio/mpeg', headers={'Cache-Control': 'private, max-age=3600'})
    except Exception as exc:
        raise HTTPException(status_code=503, detail='Voice preview could not be synthesized.') from exc

@router.get('/{channel_id}', response_model=ChannelAutonomyPolicy)
def get_channel_policy(channel_id: str):
    try:
        return channel_policy_store.get(channel_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.put('/{channel_id}', response_model=ChannelAutonomyPolicy)
def put_channel_policy(channel_id: str, policy: ChannelAutonomyPolicy):
    try:
        catalog = {voice['name']: voice['gender'] for voice in _voices()}
        if catalog.get(policy.narrator_voice_name) != policy.narrator_gender:
            raise HTTPException(status_code=422, detail='Narrator voice and gender do not match the Google TTS catalog.')
        return channel_policy_store.save(channel_id, policy)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
