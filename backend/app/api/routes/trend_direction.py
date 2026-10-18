from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from app.core.config import Settings, get_settings
from app.core.tenant import tenant_bound
from app.models.recovery import EvidenceStrength, NextContentRecommendation, RecoveryJobStage
from app.models.production_brief import ProductionFidelityMode
from app.models.trend_direction import CustomDirectionRequest, DirectionProductionRequest, TrendDirection, TrendDirectionSet
from app.services.recovery_job_service import RecoveryJobNotFoundError, recovery_job_store
from app.services.content_dna_job_service import ContentDnaJobNotFoundError, content_dna_job_store
from app.services.job_service import JobNotFoundError, job_store
from app.services.production_brief_job_service import production_brief_job_store, run_production_brief_job
from app.services.trend_direction_service import TrendDirectionService
from app.services.trend_direction_store import trend_direction_store

router=APIRouter(prefix="/api/v1/youtube",tags=["trend-directions"])

def _context(recovery_job_id:str):
    try: recovery=recovery_job_store.get(recovery_job_id)
    except RecoveryJobNotFoundError: raise HTTPException(404,"Recovery Intelligence job not found.")
    if recovery.stage!=RecoveryJobStage.COMPLETED or recovery.result is None: raise HTTPException(409,"Complete Recovery Intelligence first.")
    try: dna=content_dna_job_store.get(recovery.content_dna_job_id)
    except ContentDnaJobNotFoundError: raise HTTPException(404,"Content DNA job not found.")
    try: analysis=job_store.get(recovery.analysis_job_id)
    except JobNotFoundError: raise HTTPException(404,"Channel analysis job not found.")
    if dna.result is None or analysis.result is None: raise HTTPException(409,"Saved channel intelligence is incomplete.")
    return recovery,dna,analysis

@router.get("/recovery-jobs/{recovery_job_id}/trend-directions",response_model=TrendDirectionSet)
async def get_saved_trend_directions(recovery_job_id:str):
    _context(recovery_job_id)
    saved=trend_direction_store.get(recovery_job_id)
    if saved is None: raise HTTPException(404,"No saved direction snapshot yet.")
    return saved

@router.post("/recovery-jobs/{recovery_job_id}/trend-directions",response_model=TrendDirectionSet)
async def discover_trend_directions(recovery_job_id:str,settings:Settings=Depends(get_settings)):
    recovery,dna,analysis=_context(recovery_job_id)
    if not settings.youtube_api_key: raise HTTPException(503,"YOUTUBE_API_KEY is required for fresh trend discovery.")
    if not settings.google_cloud_project: raise HTTPException(503,"Vertex AI is required for trend analysis.")
    try:
        snapshot=await TrendDirectionService(settings).discover(analysis.result,dna.result,recovery_job_id)
        return trend_direction_store.save(snapshot)
    except Exception as exc: raise HTTPException(502,f"Fresh direction discovery failed: {exc}")

@router.post("/recovery-jobs/{recovery_job_id}/trend-directions/custom",response_model=TrendDirection)
async def refine_custom_direction(recovery_job_id:str,request:CustomDirectionRequest,settings:Settings=Depends(get_settings)):
    recovery,dna,analysis=_context(recovery_job_id)
    try:
        direction=await TrendDirectionService(settings).refine_custom(analysis.result,dna.result,recovery_job_id,request.idea)
        trend_direction_store.prepend_custom(recovery_job_id,direction)
        return direction
    except Exception as exc: raise HTTPException(502,f"AI direction assistance failed: {exc}")

@router.post("/recovery-jobs/{recovery_job_id}/production-brief-jobs/from-direction",status_code=status.HTTP_202_ACCEPTED)
async def create_from_direction(recovery_job_id:str,request:DirectionProductionRequest,background_tasks:BackgroundTasks,settings:Settings=Depends(get_settings)):
    recovery,dna,analysis=_context(recovery_job_id); d=request.direction
    recommendation=NextContentRecommendation(rank=1,recommendation_id=f"direction_{d.direction_id}",title=d.suggested_first_video or d.title,concept=d.concept,hook=d.suggested_hook,format=d.suggested_format,why_this_fits=d.why_now,recommended_characters=[],evidence_strength=EvidenceStrength.SUPPORTED,evidence_signals=[],novelty_label="Fresh market direction",novelty_score=min(1.0,max(0.0,d.scores.differentiation/15)),closest_archive_matches=[],strategy_lanes=[d.lane],diversity_note=d.lane_label,guardrail=d.guardrail)
    fidelity=ProductionFidelityMode(request.fidelity_mode)
    job=production_brief_job_store.create(recovery_job_id=recovery_job_id,content_dna_job_id=recovery.content_dna_job_id,analysis_job_id=recovery.analysis_job_id,channel_id=analysis.result.channel.channel_id,channel_title=analysis.result.channel.title,recommendation=recommendation,recovery_generated_at=recovery.result.generated_at,fidelity_mode=fidelity)
    background_tasks.add_task(tenant_bound(run_production_brief_job),job.job_id,analysis.result,dna.result,job.source_snapshot,settings,fidelity)
    return job
