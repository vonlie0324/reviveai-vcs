from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.channel_autonomy_policy import router as channel_autonomy_policy_router
from app.api.routes.ai_review import router as ai_review_router
from app.api.routes.audio_finishing import router as audio_finishing_router
from app.api.routes.autonomous_activity import router as autonomous_activity_router
from app.api.routes.auth import router as auth_router
from app.api.routes.platform_admin import router as platform_admin_router
from app.api.routes.platform_soundtracks import router as platform_soundtracks_router
from app.api.routes.platform_lyria_batches import router as platform_lyria_batches_router
from app.api.routes.autopilot_state import router as autopilot_state_router
from app.api.routes.content_dna import router as content_dna_router
from app.api.routes.delivery_package import router as delivery_package_router
from app.api.routes.delivery_qc import router as delivery_qc_router
from app.api.routes.final_assembly import router as final_assembly_router
from app.api.routes.internal_tasks import router as internal_tasks_router
from app.api.routes.media_studio import router as media_studio_router
from app.api.routes.music_match import router as music_match_router
from app.api.routes.production_brief import router as production_brief_router
from app.api.routes.production_costs import router as production_costs_router
from app.api.routes.publishing_assistant import router as publishing_assistant_router
from app.api.routes.recovery import router as recovery_router
from app.api.routes.revival_program import router as revival_program_router
from app.api.routes.trend_direction import router as trend_direction_router
from app.api.routes.youtube import router as youtube_router
from app.api.routes.youtube_publishing import router as youtube_publishing_router
from app.core.config import get_settings
from app.core.firebase_auth import require_tenant_context
from app.startup.cloud_soundtrack_application_patch import setup_cloud_soundtrack
from app.services.cloud_task_dispatcher import cloud_task_dispatcher
from app.services.event_driven_autonomy_service import event_driven_autonomy_service
from app.workers.autopilot_supervisor_worker import autopilot_supervisor_worker
from app.services.autopilot_supervisor_service import autopilot_supervisor_service
from app.workers.youtube_autonomy_worker import youtube_autonomy_worker

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.autopilot_event_driven_enabled:
        # v3.5.2: cold starts must be side-effect free. Cloud Tasks and the hourly
        # recovery sweep are the only wake-up mechanisms in event-driven mode.
        # Reconstructing/scheduling queue entries on every Cloud Run cold start can
        # create duplicate tasks and defeat scale-to-zero cost savings.
        import logging
        logging.getLogger(__name__).info(
            "Event-driven autonomy enabled; startup performs no queue scheduling"
        )
    else:
        await autopilot_supervisor_worker.start()
        await youtube_autonomy_worker.start()
    try:
        yield
    finally:
        if not settings.autopilot_event_driven_enabled:
            await youtube_autonomy_worker.stop()
            await autopilot_supervisor_worker.stop()
        else:
            await autopilot_supervisor_service.shutdown()


app = FastAPI(
    title="ReviveAI API",
    version="0.28.0",
    description="Creator intelligence, current-market direction discovery, and delegated production.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(platform_admin_router)
app.include_router(platform_soundtracks_router)
app.include_router(platform_lyria_batches_router)
_auth = [Depends(require_tenant_context)]
for router in [
    youtube_router,
    channel_autonomy_policy_router,
    content_dna_router,
    recovery_router,
    production_brief_router,
    media_studio_router,
    final_assembly_router,
    audio_finishing_router,
    delivery_qc_router,
    delivery_package_router,
    publishing_assistant_router,
    music_match_router,
    revival_program_router,
    trend_direction_router,
    ai_review_router,
    autopilot_state_router,
    production_costs_router,
    autonomous_activity_router,
]:
    app.include_router(router, dependencies=_auth)

# YouTube publishing declares authentication on each protected endpoint itself.
# Its Google OAuth callback must remain public because Google redirects to it in a
# browser context that may not carry the ReviveAI session cookie. The callback is
# protected by the short-lived, one-time OAuth state created by /publisher/connect.
app.include_router(youtube_publishing_router)
app.include_router(internal_tasks_router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
        "youtube_api_key_configured": bool(settings.youtube_api_key),
        "vertex_ai_configured": bool(settings.google_cloud_project),
        "google_cloud_project": settings.google_cloud_project or None,
        "google_cloud_location": settings.google_cloud_location,
        "gemini_model": settings.gemini_model,
        "firebase_auth_required": settings.firebase_auth_required,
        "server_side_tenant_isolation": True,
        "trend_direction_engine": True,
        "autopilot_backend_supervisor": settings.autopilot_backend_supervisor_enabled,
        "autopilot_supervisor_running": autopilot_supervisor_worker.running,
        "autopilot_execution_mode": "cloud_tasks" if settings.autopilot_event_driven_enabled else "in_process",
        "autopilot_task_dispatch_configured": cloud_task_dispatcher.configured,
        "autopilot_supervisor_ready": cloud_task_dispatcher.configured if settings.autopilot_event_driven_enabled else autopilot_supervisor_worker.running,
        "downstream_cloud_durability": True,
        "runtime_asset_gcs_configured": bool(settings.effective_runtime_asset_gcs_uri),
        "autonomous_publish_enabled": settings.autopilot_autonomous_publish_enabled,
        "autonomous_final_approval_enabled": settings.autopilot_autonomous_final_approval_enabled,
        "autopilot_continuous_campaign_enabled": settings.autopilot_continuous_campaign_enabled,
        "autopilot_continuous_learning_checkpoint": settings.autopilot_continuous_learning_checkpoint,
        "autopilot_next_production_checkpoint": settings.autopilot_next_production_checkpoint,
        "autopilot_primary_performance_checkpoint": settings.autopilot_primary_performance_checkpoint,
        "autopilot_daily_publishing_enabled": settings.autopilot_daily_publishing_enabled,
        "autopilot_daily_publish_hour_local": settings.autopilot_daily_publish_hour_local,
        "youtube_publication_idempotency": True,
        "youtube_autonomy_worker_running": youtube_autonomy_worker.running,
        "youtube_autonomy_execution_mode": "cloud_tasks" if settings.autopilot_event_driven_enabled else "in_process",
        "youtube_autonomy_ready": cloud_task_dispatcher.configured if settings.autopilot_event_driven_enabled and settings.autopilot_autonomous_publish_enabled else youtube_autonomy_worker.running,
    }


# Cloud soundtrack initialization.
setup_cloud_soundtrack(app)
