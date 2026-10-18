ReviveAI channel-analysis Cloud Tasks fix

Replace these files in backend:
- app/api/routes/youtube.py
- app/services/cloud_task_dispatcher.py
- app/services/job_service.py
- app/api/routes/internal_tasks.py

Behavior:
- Event-driven production: POST /api/v1/youtube/analysis-jobs creates Firestore job then schedules Cloud Task.
- Cloud Task calls POST /internal/tasks/analysis with OIDC.
- Handler restores tenant ContextVar, loads durable job, executes run_analysis_job.
- Local/non-event-driven mode retains FastAPI BackgroundTasks fallback.
- Failed Cloud Task dispatch marks the analysis job FAILED and returns 503 instead of leaving it QUEUED forever.
- Duplicate terminal deliveries are acknowledged without rerunning analysis.

No new environment variables are required. It reuses the existing reviveai-autonomy Cloud Tasks queue and OIDC settings.
