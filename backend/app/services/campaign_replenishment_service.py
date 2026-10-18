from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core.config import get_settings
from app.models.recovery import NextContentRecommendation, EvidenceStrength
from app.models.revival_program import RevivalContentLane, RevivalProgramIdea
from app.services.recovery_job_service import recovery_job_store
from app.services.revival_program_service import revival_program_store
from app.services.revival_learning_service import revival_learning_store

logger = logging.getLogger(__name__)


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


class CampaignReplenishmentService:
    """Opt-in, lease-protected idea replenishment. No video upload or budget mutations.

    Called only inside the existing tenant-scoped Autopilot supervisor lease.
    Existing Recovery Intelligence recommendations are extended, not replaced.
    """

    @staticmethod
    def due(recovery_job) -> bool:
        settings = get_settings()
        if not settings.autopilot_auto_replenish_enabled or not settings.autopilot_continuous_campaign_enabled:
            return False
        meta = (recovery_job.detail or {}).get("autopilot_replenishment") or {}
        if not isinstance(meta, dict):
            return True
        stamp = meta.get("last_attempt_at")
        if not stamp:
            return True
        try:
            last = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            return datetime.now(timezone.utc) >= last + timedelta(hours=settings.autopilot_replenish_cooldown_hours)
        except (ValueError, TypeError):
            return True

    async def replenish(self, recovery_job, program) -> int:
        settings = get_settings()
        if not recovery_job.result:
            raise ValueError("Recovery Intelligence must be complete to replenish ideas")
        # Recover a partially committed cycle: Recovery Intelligence is committed first.
        existing = {idea.recommendation_id for idea in program.ideas}
        pending = [r for r in recovery_job.result.recommendations if r.recommendation_id not in existing]
        if pending:
            self._extend_program(program, pending)
            return len(pending)
        if not self.due(recovery_job):
            return 0
        # Record attempt before AI work; Cloud Task retries cannot repeatedly bill Gemini.
        recovery_job.detail = dict(recovery_job.detail or {})
        previous = recovery_job.detail.get("autopilot_replenishment") or {}
        cycle = int(previous.get("cycle") or 0) + 1 if isinstance(previous, dict) else 1
        recovery_job.detail["autopilot_replenishment"] = {
            "cycle": cycle,
            "last_attempt_at": datetime.now(timezone.utc).isoformat(),
            "last_result": "GENERATING",
        }
        self._save_recovery(recovery_job)
        try:
            candidates = await self._generate(recovery_job, program, cycle)
            if not candidates:
                raise ValueError("Gemini returned no distinct, valid replenishment ideas")
            # Persist recommendations first; a retry can repair a partially written program.
            recovery_job.result.recommendations.extend(candidates)
            recovery_job.detail["autopilot_replenishment"]["last_result"] = "COMMITTED"
            recovery_job.detail["autopilot_replenishment"]["new_ideas"] = len(candidates)
            self._save_recovery(recovery_job)
            self._extend_program(program, candidates)
            return len(candidates)
        except Exception as exc:
            recovery_job.detail["autopilot_replenishment"]["last_result"] = "FAILED"
            recovery_job.detail["autopilot_replenishment"]["last_error_type"] = type(exc).__name__
            self._save_recovery(recovery_job)
            logger.exception("Autopilot replenishment failed for recovery job %s", recovery_job.job_id)
            raise

    @staticmethod
    def _save_recovery(job):
        # Reuse the store's existing durable Firestore + local-mirror persistence.
        with recovery_job_store._lock:
            recovery_job_store._persist(job)
            recovery_job_store._jobs[job.job_id] = job.model_copy(deep=True)

    @staticmethod
    def _extend_program(program, candidates):
        ids = {i.recommendation_id for i in program.ideas}
        for rec in candidates:
            if rec.recommendation_id in ids:
                continue
            ids.add(rec.recommendation_id)
            program.ideas.append(RevivalProgramIdea(
                idea_id=f"revival_idea_{uuid4().hex[:12]}",
                recommendation_id=rec.recommendation_id,
                title=rec.title, concept=rec.concept, hook=rec.hook, format=rec.format,
                lane=RevivalContentLane.EXPERIMENT,
                evidence_strength=rec.evidence_strength,
                evidence_fit_score=70, evidence_fit_label="Learning-informed hypothesis",
                why_now=rec.why_this_fits,
                strategy_lanes=rec.strategy_lanes,
            ))
        program.target_posts = max(program.target_posts, len(program.ideas))
        program.updated_at = datetime.now(timezone.utc)
        revival_program_store._persist(program)

    async def _generate(self, recovery_job, program, cycle: int):
        from google import genai
        from google.genai import types

        settings = get_settings()
        n = settings.autopilot_replenish_ideas_per_cycle
        prior = recovery_job.result.recommendations
        existing_titles = {_norm(item.title) for item in prior}
        existing_concepts = {_norm(item.concept) for item in prior}
        # Include actual persisted performance observations, rather than inventing results.
        evidence = []
        try:
            learning = revival_learning_store.get(program.program_id)
            observations = list(getattr(learning, "observations", []) or [])
            for obs in observations[-15:]:
                evidence.append({
                    "recommendation_id": getattr(obs, "recommendation_id", None),
                    "checkpoint": getattr(obs, "checkpoint", None),
                    "views": getattr(obs, "views", None),
                    "average_percentage_viewed": getattr(obs, "average_percentage_viewed", None),
                })
        except Exception:
            logger.info("Replenishment will use historical recommendations; learning observations unavailable")
        context = {
            "channel": program.channel_title,
            "program_goal": program.program_goal,
            "existing_ideas": [{"title": x.title, "concept": x.concept} for x in prior][-80:],
            "observed_performance": evidence,
        }
        prompt = (
            f"Generate {n + 4} DIFFERENT new short-form YouTube video concepts for this channel. "
            "Avoid every previous title and core concept. Preserve channel identity. "
            "Treat missing/partial analytics as unknown; do not invent performance metrics. "
            "Ideas must be practical, fresh, and distinct from each other. "
            "Return ONLY a JSON object with key 'ideas', an array of objects, each with "
            "'title', 'concept', 'hook', 'format', 'why_this_fits', and 'strategy_lanes' (array of strings). "
            "No guarantees of views or virality. Context: " + json.dumps(context, ensure_ascii=False)
        )
        client = genai.Client(vertexai=True, project=settings.google_cloud_project,
                              location=settings.google_cloud_location,
                              http_options=types.HttpOptions(api_version="v1"))
        try:
            from app.services.channel_intelligence_budget import ChannelIntelligenceBudget
            response = await ChannelIntelligenceBudget().generate(
                channel_id=program.channel_id, category="campaign_replenishment", client=client,
                model=settings.gemini_model, contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.7,
                                                   max_output_tokens=7000),
            )
        finally:
            await client.aio.aclose()
        data = json.loads(response.text or "{}")
        raw = data.get("ideas") or []
        if not isinstance(raw, list):
            raise ValueError("Replenishment JSON 'ideas' must be a list")
        selected = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()[:140]
            concept = str(row.get("concept") or "").strip()[:1200]
            hook = str(row.get("hook") or "").strip()[:300]
            fmt = str(row.get("format") or "Short")[:100]
            if not title or not concept or not hook:
                continue
            key, ckey = _norm(title), _norm(concept)
            if not key or not ckey or key in existing_titles or ckey in existing_concepts:
                continue
            existing_titles.add(key)
            existing_concepts.add(ckey)
            # Stable content-derived IDs across retries/cycle restarts.
            digest = hashlib.sha256((program.program_id + str(cycle) + key).encode()).hexdigest()[:20]
            selected.append(NextContentRecommendation(
                rank=len(prior) + len(selected) + 1,
                recommendation_id=f"replenished_{digest}",
                title=title, concept=concept, hook=hook, format=fmt,
                why_this_fits=str(row.get("why_this_fits") or "Fresh, testable variation informed by channel history.")[:500],
                evidence_strength=EvidenceStrength.EXPLORATORY,
                novelty_label="New learning-informed experiment", novelty_score=0.5,
                strategy_lanes=[str(v)[:80] for v in (row.get("strategy_lanes") or []) if isinstance(v, str)][:5],
                diversity_note="Generated as an exploration; not a verified market prediction.",
            ))
            if len(selected) >= n:
                break
        return selected


campaign_replenishment_service = CampaignReplenishmentService()
