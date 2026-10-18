"""Tenant-isolated per-channel autonomy settings."""
from __future__ import annotations

from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field, field_validator
from app.services.firestore_job_repository import FirestoreJobRepository

class ChannelAutonomyPolicy(BaseModel):
    max_final_video_duration_seconds: int = Field(default=60, ge=6, le=3600)
    max_total_production_cost_usd: Decimal = Field(default=Decimal('10.00'), gt=0, le=10000, decimal_places=2)
    publish_interval_hours: int = Field(default=24, ge=1, le=720)
    narrator_gender: Literal['MALE','FEMALE'] = 'FEMALE'
    narrator_voice_name: str = Field(default='en-US-Chirp3-HD-Kore', min_length=5, max_length=120)
    auto_accept_safe_adaptations: bool = True
    max_keyframe_attempts: int = Field(default=3, ge=1, le=5)
    autonomous_publishing_enabled: bool = True
    # Controls how campaign-level creative/technical failures are handled after bounded retries.
    # Infrastructure-wide outages remain blocking regardless of this preference.
    isolate_failed_productions: bool = True

    @field_validator('narrator_voice_name')
    @classmethod
    def validate_voice(cls, value: str) -> str:
        if not value.startswith('en-US-') or not all(c.isalnum() or c == '-' for c in value):
            raise ValueError('Choose a supported English (US) Google Cloud TTS voice.')
        return value

class ChannelPolicyStore:
    def __init__(self):
        self._repo = FirestoreJobRepository('channel_autonomy_policies')

    def get(self, channel_id: str) -> ChannelAutonomyPolicy:
        return ChannelAutonomyPolicy.model_validate(self._repo.load(self._channel_id(channel_id)) or {})

    def save(self, channel_id: str, policy: ChannelAutonomyPolicy) -> ChannelAutonomyPolicy:
        self._repo.save(self._channel_id(channel_id), policy.model_dump(mode='json'))
        return policy

    @staticmethod
    def _channel_id(channel_id: str) -> str:
        value = (channel_id or '').strip()
        if not value or len(value) > 160 or '/' in value or '\\' in value:
            raise ValueError('Invalid channel ID')
        return value

channel_policy_store = ChannelPolicyStore()
