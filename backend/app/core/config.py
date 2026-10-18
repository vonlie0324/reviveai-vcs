from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "ReviveAI M2D.2.3.1"
    app_env: str = "development"

    # M2D.2 Firebase Authentication. The browser exchanges a Firebase ID token
    # for an HttpOnly backend session cookie so media assets and API calls share
    # one authenticated session without exposing long-lived credentials to JS.
    firebase_auth_required: bool = True
    firebase_project_id: str = ""
    # Named Firestore database used by ReviveAI durable runtime state.
    # Use "(default)" only when the project intentionally uses the default database.
    firestore_database_id: str = "(default)"
    soundtrack_output_gcs_uri: str = "gs://reviveai/soundtracks"
    firebase_session_cookie_name: str = "reviveai_session"
    firebase_csrf_cookie_name: str = "reviveai_csrf"
    firebase_session_days: int = Field(default=5, ge=1, le=14)
    firebase_recent_sign_in_seconds: int = Field(default=300, ge=60, le=900)
    firebase_cookie_secure: bool = False
    firebase_cookie_samesite: str = "lax"
    firebase_check_revoked: bool = False

    # One-time recovery for data created before M2D.2.1 tenant isolation.
    # Adoption is disabled unless the signed-in Firebase account is explicitly
    # allowlisted by UID or by a verified email address on the backend.
    legacy_adoption_allowed_uids: Annotated[list[str], NoDecode] = []
    legacy_adoption_allowed_emails: Annotated[list[str], NoDecode] = []

    youtube_api_key: str = ""
    youtube_request_timeout_seconds: float = 20.0
    youtube_oauth_client_id: str = ""
    youtube_oauth_client_secret: str = ""
    youtube_oauth_redirect_uri: str = "http://127.0.0.1:8080/api/v1/youtube/publisher/oauth/callback"
    youtube_oauth_token_encryption_key: str = ""
    youtube_max_videos: int = Field(
        default=0,
        description="0 means retrieve all accessible public uploads.",
        ge=0,
    )

    # Vertex AI / Gemini settings for Content DNA.
    google_cloud_project: str = ""
    google_cloud_location: str = "global"
    gemini_model: str = "gemini-3.5-flash"
    content_dna_batch_size: int = Field(default=6, ge=1, le=12)
    content_dna_max_videos: int = Field(
        default=36,
        description=(
            "Maximum videos used for the initial Content DNA. ReviveAI selects a recency-weighted "
            "sample across the archive so creators can continue quickly. Set 0 to classify the full archive."
        ),
        ge=0,
    )
    content_dna_thumbnail_timeout_seconds: float = Field(default=15.0, gt=0)
    content_dna_retry_attempts: int = Field(default=3, ge=1, le=5)
    content_dna_checkpoint_dir: str = ".reviveai_checkpoints"

    # M2A production-brief reliability. Keep these separate from Content DNA so
    # tuning classification retries cannot accidentally change creator production.
    production_brief_retry_attempts: int = Field(default=3, ge=1, le=5)
    production_brief_request_timeout_seconds: float = Field(default=90.0, ge=15.0, le=300.0)
    production_brief_stale_seconds: float = Field(
        default=240.0,
        ge=60.0,
        le=1800.0,
        description=(
            "Mark an unfinished production run stale after this many seconds without a persisted heartbeat. "
            "Keep this comfortably above production_brief_request_timeout_seconds."
        ),
    )

    # M2B.1 image generation. Google deprecated the older Imagen GA endpoints in 2026;
    # use the current Gemini image generation endpoint on Vertex AI.
    image_generation_model: str = "gemini-3.1-flash-image"
    media_image_aspect_ratio: str = "9:16"
    media_generation_retry_attempts: int = Field(default=2, ge=1, le=4)

    # M2B concurrency. Keep image/fidelity and Veo limits independent because they
    # have different quotas and cost profiles. A value of 1 restores the previous
    # fully sequential behavior. Start conservatively and raise only after observing
    # Vertex AI quota/429 behavior in the target project.
    media_keyframe_concurrency: int = Field(default=3, ge=1, le=8)
    media_video_concurrency: int = Field(default=2, ge=1, le=6)

    # Global process-wide generation budgets. Per-job concurrency above controls how
    # aggressively one production fans out; these limits cap ALL productions combined.
    # This is the safety layer required before campaign/wave-level parallel production.
    global_image_generation_concurrency: int = Field(default=4, ge=1, le=16)
    global_video_generation_concurrency: int = Field(default=2, ge=1, le=8)

    # M2B.2 Veo shot animation. Veo 3.1 is regional; keep video location separate
    # from Gemini/image generation which can use global.
    video_generation_model: str = "veo-3.1-generate-001"
    video_generation_location: str = "us-central1"
    video_output_gcs_uri: str = ""
    # Durable runtime artifacts (keyframes, assembled masters, audio masters, packages).
    # When omitted, ReviveAI derives a dedicated runtime-artifacts prefix from VIDEO_OUTPUT_GCS_URI.
    runtime_asset_gcs_uri: str = ""
    video_generation_resolution: str = "720p"
    video_generation_audio: bool = False

    # Autopilot cost control. When disabled, AI quality-review REGENERATE decisions
    # block rejected clips rather than starting another paid generation.
    # Manual regeneration endpoints remain available to an explicit user action.
    autopilot_allow_regeneration: bool = True

    # Headless Autopilot supervisor. When enabled, the backend owns orchestration and
    # continues advancing RUNNING sessions even when the creator closes the browser.
    # Cloud Run must keep at least one CPU-allocated instance alive for this in-process
    # worker; deployment guidance is included with the integration package.
    autopilot_backend_supervisor_enabled: bool = True
    autopilot_supervisor_interval_seconds: float = Field(default=5.0, ge=1.0, le=60.0)
    autopilot_supervisor_lease_seconds: int = Field(default=120, ge=30, le=900)
    autopilot_supervisor_max_sessions_per_tick: int = Field(default=8, ge=1, le=50)

    # Fully autonomous production + YouTube publishing, as explicitly selected
    # for this deployment. Override either flag via environment variables to
    # pause autonomous approval/publishing. All AI/QC gates remain mandatory;
    # uploads begin private, then YouTube publishes at the scheduled time.
    autopilot_autonomous_publish_enabled: bool = True
    autopilot_autonomous_final_approval_enabled: bool = True
    autopilot_publish_timezone: str = "Asia/Manila"
    autopilot_daily_publishing_enabled: bool = True
    autopilot_daily_publish_hour_local: int = Field(default=12, ge=0, le=23)
    autopilot_publish_candidate_hours_local: str = "12"
    autopilot_publish_min_lead_minutes: int = Field(default=120, ge=30, le=1440)
    autopilot_publish_min_spacing_hours: int = Field(default=24, ge=1, le=168)
    autopilot_publish_max_per_day: int = Field(default=1, ge=1, le=10)
    autopilot_youtube_made_for_kids: bool = False
    autopilot_youtube_contains_synthetic_media: bool = True

    # Continuous autonomous campaign loop. Publishing is intentionally daily while
    # learning continues in parallel. A short 6H checkpoint is enough to unlock the
    # next production so generation can finish before the next day's release slot.
    # The 24H checkpoint remains the primary apples-to-apples signal used for
    # performance ranking; 72H/7D/28D snapshots continue to mature in the background.
    autopilot_continuous_campaign_enabled: bool = False
    autopilot_auto_replenish_enabled: bool = False
    autopilot_replenish_ideas_per_cycle: int = Field(default=5, ge=2, le=10)
    autopilot_replenish_cooldown_hours: int = Field(default=24, ge=6, le=168)
    # Legacy/display checkpoint remains 24H for compatibility with existing
    # deployments. The next-production gate is intentionally separate so an old
    # Cloud Run env override cannot accidentally restore a 24H production wait.
    autopilot_continuous_learning_checkpoint: str = "24H"
    autopilot_next_production_checkpoint: str = "6H"
    autopilot_primary_performance_checkpoint: str = "24H"
    autopilot_next_production_max_wait_hours: int = Field(default=12, ge=6, le=72)
    autopilot_continuous_learning_max_wait_hours: int = Field(default=36, ge=6, le=336)
    autopilot_publication_claim_lease_seconds: int = Field(default=300, ge=60, le=1800)

    youtube_autonomy_monitor_interval_seconds: float = Field(default=300.0, ge=30.0, le=3600.0)
    youtube_autonomy_lease_seconds: int = Field(default=180, ge=30, le=1800)
    youtube_autonomy_max_tenants_per_tick: int = Field(default=10, ge=1, le=100)

    # v3.5 event-driven autonomy. When enabled, Cloud Tasks wakes Cloud Run only when
    # useful work is due; the in-process polling loops are disabled so request-based
    # billing and scale-to-zero can be used safely.
    autopilot_event_driven_enabled: bool = False
    autopilot_tasks_project_id: str = ""
    autopilot_tasks_location: str = "asia-southeast1"
    autopilot_tasks_queue: str = "reviveai-autonomy"
    autopilot_tasks_target_base_url: str = ""
    autopilot_tasks_service_account_email: str = ""
    autopilot_tasks_oidc_audience: str = ""
    autopilot_tasks_dispatch_deadline_seconds: int = Field(default=1800, ge=60, le=1800)
    autopilot_task_active_interval_seconds: int = Field(default=15, ge=5, le=300)
    autopilot_task_public_probe_grace_seconds: int = Field(default=120, ge=30, le=900)
    autopilot_task_analytics_grace_seconds: int = Field(default=300, ge=30, le=3600)

    # Cost visibility / guardrails.
    # Google bills Veo using "count" units. ReviveAI keeps the conversion explicit
    # and configurable rather than hard-coding an undocumented billing semantic.
    # For your current Veo 3.1 720p video-only setup, set the unit rate to the
    # current published price and keep the units-per-second assumption configurable.
    video_estimated_cost_per_unit_usd: float = Field(default=0.20, ge=0.0, le=10.0)
    video_estimated_units_per_generated_second: float = Field(default=1.0, ge=0.0, le=100.0)
    video_production_budget_usd: float = Field(default=10.0, ge=0.0, le=100000.0)
    video_budget_enforced: bool = True
    video_generation_poll_seconds: int = Field(default=12, ge=5, le=60)

    # M2C.1.2 deterministic final assembly + persisted resume discovery. Approved Veo clips are trimmed to storyboard timing,
    # normalized to a single 9:16 master, sequenced, and optionally receive approved on-screen text.
    assembly_render_width: int = Field(default=720, ge=360, le=2160)
    assembly_render_height: int = Field(default=1280, ge=640, le=3840)
    assembly_frame_rate: int = Field(default=30, ge=24, le=60)
    assembly_burn_on_screen_text: bool = True

    # M2C.2 unified audio finishing. The approved visual master is preserved; this
    # stage creates a separate delivery master with TTS + original procedural audio.
    audio_tts_enabled: bool = True
    audio_tts_language_code: str = "en-US"
    audio_tts_voice: str = "en-US-Chirp3-HD-Kore"
    audio_music_volume: float = Field(default=0.55, ge=0.0, le=1.5)
    audio_ambience_volume: float = Field(default=0.70, ge=0.0, le=1.5)
    audio_voice_volume: float = Field(default=1.00, ge=0.0, le=2.0)
    audio_target_lufs: float = Field(default=-16.0, ge=-24.0, le=-10.0)

    # Rights-aware trending music catalog. ReviveAI only embeds tracks whose catalog
    # entry confirms commercial use and references a local licensed audio file.
    audio_trending_music_catalog_path: str = "music_library/trending_music_catalog.json"
    audio_trending_music_library_dir: str = "music_library"

    # Creator-imported YouTube Audio Library files. ReviveAI stores only files the creator
    # explicitly uploads after downloading them from YouTube Studio; it does not scrape or fetch tracks.
    audio_youtube_library_catalog_path: str = "music_library/youtube_audio_library_catalog.json"
    audio_youtube_library_dir: str = "music_library/youtube_audio_library"
    audio_youtube_library_max_upload_mb: int = Field(default=50, ge=1, le=250)

    # M2C.3 deterministic final delivery quality control.
    delivery_qc_duration_tolerance_seconds: float = Field(default=0.35, ge=0.05, le=2.0)
    delivery_qc_loudness_tolerance_lufs: float = Field(default=2.0, ge=0.5, le=6.0)
    delivery_qc_max_true_peak_dbfs: float = Field(default=-1.0, ge=-6.0, le=0.0)
    delivery_qc_max_unexpected_silence_seconds: float = Field(default=2.5, ge=0.5, le=15.0)

    # NoDecode prevents pydantic-settings from trying to JSON-decode a
    # comma-separated environment variable such as:
    # CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @property
    def effective_firebase_project_id(self) -> str:
        return self.firebase_project_id or self.google_cloud_project

    @property
    def effective_autopilot_tasks_project_id(self) -> str:
        return (self.autopilot_tasks_project_id or self.google_cloud_project or self.firebase_project_id).strip()

    @property
    def effective_runtime_asset_gcs_uri(self) -> str:
        explicit = (self.runtime_asset_gcs_uri or "").strip()
        if explicit:
            return explicit.rstrip("/")
        video = (self.video_output_gcs_uri or "").strip()
        if video:
            return f"{video.rstrip('/')}/runtime-artifacts"
        return ""

    @field_validator("firebase_cookie_samesite")
    @classmethod
    def validate_cookie_samesite(cls, value: str):
        normalized = value.lower().strip()
        if normalized not in {"lax", "strict", "none"}:
            raise ValueError("FIREBASE_COOKIE_SAMESITE must be lax, strict, or none.")
        return normalized


    @field_validator("legacy_adoption_allowed_uids", "legacy_adoption_allowed_emails", mode="before")
    @classmethod
    def parse_legacy_adoption_allowlist(cls, value):
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if value is None or value == "":
            return [
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            ]

        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]

        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Cloud soundtrack storage
GOOGLE_CLOUD_STORAGE_BUCKET = None
