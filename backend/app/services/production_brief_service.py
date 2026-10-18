from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence

from pydantic import ValidationError

from app.core.config import Settings
from app.core.tenant import tenant_scoped_root
from app.models.content_dna import ContentDnaResult, EvidenceVideoRef
from app.models.production_brief import (
    AiCreativeDirection,
    CharacterIdentityEvidence,
    AiPublishingPackage,
    AiStoryboardOutline,
    AiStoryboardPromptPack,
    ConsistencyAnchorSet,
    ConsistencyCheck,
    DirectionFidelityCheck,
    DirectionFidelityContract,
    DirectionFidelityReport,
    DirectionFidelityStatus,
    CreativeDirection,
    ProductionConsistencyReport,
    ProductionConsistencyStatus,
    ProductionFidelityMode,
    ProductionIdentity,
    ProductionBriefCheckpoint,
    ProductionBriefJobStage,
    ProductionBriefResult,
    PublishingPackage,
    StoryboardPlan,
    StoryboardShot,
    SourceDirectionSnapshot,
)
from app.models.recovery import NextContentRecommendation
from app.models.youtube import AnalysisResult


logger = logging.getLogger(__name__)


class ProductionBriefError(RuntimeError):
    pass


ProductionBriefStageCallback = Callable[[ProductionBriefJobStage, str, int, int, Dict], None]


PRODUCTION_SYSTEM = """
You are ReviveAI's creative director for short-form digital content.

You are working from a human-selected Recovery Intelligence direction. Your job is to turn that direction into a concise, production-ready creative brief while preserving the channel's established identity.

Rules:
- Do not predict views, virality, engagement, audience growth, or performance.
- Do not describe any creative pattern as proven, winning, guaranteed, best-performing, or certain to work.
- Do not copy a source archive video. Build a fresh execution around the approved concept.
- Keep character identity and recurring channel style consistent with the supplied Content DNA.
- Establish one canonical Production Identity in the creative-direction pass and never rename or visually redefine that character downstream.
- If the subject is a non-human animal, do not depict a visible human hand or arm as belonging to the animal. Use an anthropomorphic paw/limb that clearly belongs to the same character unless the approved concept explicitly requires a separate human.
- Prefer clear, visually executable actions over abstract prose.
- Keep short-form pacing realistic. Every shot must have a purpose.
- Do not invent owner-only audience demographics, retention, watch-time, or private analytics.
- Do not introduce additional recurring characters unless the brief explicitly calls for them.
- Any generated media prompts should describe the scene, action, framing, lighting, wardrobe, props, and continuity needed for consistent generation.
- The result is a draft for human review, not permission to publish automatically.
""".strip()


class ProductionBriefService:
    CHECKPOINT_VERSION = "m2a7"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.gemini_calls = 0
        self._budget_production_id: str | None = None
        self._budget_channel_id: str | None = None
        self._stage_callback: Optional[ProductionBriefStageCallback] = None
        self._active_stage: Optional[ProductionBriefJobStage] = None
        self._active_message: str = "Building production brief"
        self._active_current: int = 0
        self._active_total: int = 5
        self._active_detail: Dict = {}

    def configure_budget_identity(self, production_id: str, channel_id: str) -> None:
        if not production_id.startswith("production_") or not channel_id:
            raise ValueError("A durable production brief ID and channel ID are required")
        self._budget_production_id = production_id
        self._budget_channel_id = channel_id

    def _reserve_gemini_attempt(self):
        from uuid import uuid4
        from app.services.firestore_budget_service import FirestoreBudgetService
        from app.services.channel_autonomy_policy import channel_policy_store
        import math
        import os

        if not self._budget_production_id or not self._budget_channel_id:
            raise ProductionBriefError("Production budget identity is not configured")
        ledger = FirestoreBudgetService()
        allocation = channel_policy_store.get(self._budget_channel_id).max_total_production_cost_usd
        ledger.ensure_production_budget(self._budget_production_id, self._budget_channel_id, allocation)
        operation_id = f"brief_gemini_{uuid4().hex}"
        raw_estimate = os.environ.get("REVIVEAI_GEMINI_BRIEF_RESERVATION_USD", "")
        try:
            estimate = float(raw_estimate)
        except ValueError as exc:
            raise ProductionBriefError("Configure REVIVEAI_GEMINI_BRIEF_RESERVATION_USD") from exc
        if not math.isfinite(estimate) or estimate <= 0:
            raise ProductionBriefError("Configure a positive REVIVEAI_GEMINI_BRIEF_RESERVATION_USD")
        claim = ledger.reserve(self._budget_production_id, estimate, operation_id)
        if not claim.get("allowed"):
            raise ProductionBriefError(f"Production brief budget reservation rejected: {claim.get('reason', 'insufficient_budget')}")
        return ledger, operation_id, estimate

    def _report_stage(
        self,
        stage: ProductionBriefJobStage,
        message: str,
        current: int,
        total: int,
        detail: Dict,
    ) -> None:
        """Persist stage/attempt progress before long-running provider calls.

        The production job is polled independently from the worker. Persisting the
        provider attempt *before* awaiting Gemini prevents the UI from appearing
        frozen at ``gemini_calls=0`` and gives stale-worker detection a heartbeat.
        """
        self._active_stage = stage
        self._active_message = message
        self._active_current = current
        self._active_total = total
        self._active_detail = dict(detail)
        if self._stage_callback is not None:
            self._stage_callback(stage, message, current, total, dict(detail))

    def _report_call_progress(self, **updates) -> None:
        if self._active_stage is None:
            return
        detail = {**self._active_detail, **updates}
        self._report_stage(
            self._active_stage,
            self._active_message,
            self._active_current,
            self._active_total,
            detail,
        )

    async def build(
        self,
        analysis: AnalysisResult,
        dna: ContentDnaResult,
        recommendation: NextContentRecommendation,
        on_stage: ProductionBriefStageCallback,
        fidelity_mode: ProductionFidelityMode = ProductionFidelityMode.STANDARD,
        source_snapshot: Optional[SourceDirectionSnapshot] = None,
    ) -> ProductionBriefResult:
        self._stage_callback = on_stage
        self._validate_configuration()
        client, types = self._create_genai_client()
        total = 5
        if source_snapshot is not None:
            recommendation = source_snapshot.recommendation.model_copy(deep=True)
        fidelity_contract = self._build_direction_fidelity_contract(recommendation)
        context = self._creative_context(analysis, dna, recommendation, fidelity_contract, fidelity_mode)
        checkpoint_key = self._checkpoint_key(analysis, dna, recommendation, fidelity_mode)
        checkpoint = self._load_checkpoint(checkpoint_key)
        if checkpoint.source_snapshot is not None:
            source_snapshot = checkpoint.source_snapshot
            recommendation = source_snapshot.recommendation.model_copy(deep=True)
        elif source_snapshot is not None:
            checkpoint.source_snapshot = source_snapshot
            self._save_checkpoint(checkpoint_key, checkpoint)
        resumed = any(
            [
                checkpoint.creative_direction,
                checkpoint.storyboard_outline,
                checkpoint.storyboard,
                checkpoint.publishing,
            ]
        )

        self._report_stage(
            ProductionBriefJobStage.PREPARING_CONTEXT,
            "Locking the approved direction and checking saved production stages",
            0,
            total,
            {
                "step_label": "Prepare creative context",
                "gemini_calls": self.gemini_calls,
                "recommendation_title": recommendation.title,
                "checkpoint_available": resumed,
                "checkpoint_stage": self._checkpoint_stage(checkpoint),
                "fidelity_mode": fidelity_mode,
                "source_subject_count": fidelity_contract.explicit_subject_count,
            },
        )
        if checkpoint.fidelity_contract is None:
            checkpoint.fidelity_contract = fidelity_contract
            self._save_checkpoint(checkpoint_key, checkpoint)
        else:
            fidelity_contract = checkpoint.fidelity_contract

        # 1) Creative direction
        self._report_stage(
            ProductionBriefJobStage.BUILDING_CREATIVE_DIRECTION,
            "Reusing the saved creative north star" if checkpoint.creative_direction else "Building the creative north star",
            1,
            total,
            {
                "step_label": "Creative direction",
                "gemini_calls": self.gemini_calls,
                "recommendation_title": recommendation.title,
                "resumed_from_checkpoint": bool(checkpoint.creative_direction),
            },
        )
        if checkpoint.creative_direction is not None:
            creative = checkpoint.creative_direction
        else:
            creative_ai = await self._build_creative_direction(client, types, context)
            creative = CreativeDirection.model_validate(creative_ai.model_dump())
            creative = self._lock_creative_direction(creative, recommendation, fidelity_contract, fidelity_mode)
            checkpoint.creative_direction = creative
            self._save_checkpoint(checkpoint_key, checkpoint)

        # 2) Compact storyboard outline. Generation prompts are deliberately excluded
        # from this call to reduce the chance of a long structured response being cut off.
        self._report_stage(
            ProductionBriefJobStage.BUILDING_STORYBOARD_OUTLINE,
            "Reusing the saved shot plan" if checkpoint.storyboard_outline else "Building a compact shot-by-shot plan",
            2,
            total,
            {
                "step_label": "Shot plan",
                "gemini_calls": self.gemini_calls,
                "target_duration_seconds": creative.target_duration_seconds,
                "resumed_from_checkpoint": bool(checkpoint.storyboard_outline),
            },
        )
        if checkpoint.storyboard_outline is not None:
            outline = checkpoint.storyboard_outline
        else:
            outline = await self._build_storyboard_outline(client, types, context, creative)
            checkpoint.storyboard_outline = outline
            self._save_checkpoint(checkpoint_key, checkpoint)

        # 3) Generate only the media prompts, then reconnect them deterministically to
        # the already validated compact outline.
        self._report_stage(
            ProductionBriefJobStage.BUILDING_STORYBOARD_PROMPTS,
            "Reusing saved media-generation prompts" if checkpoint.storyboard else "Enriching the shot plan with generation prompts",
            3,
            total,
            {
                "step_label": "Generation prompts",
                "gemini_calls": self.gemini_calls,
                "storyboard_shots": len(outline.shots),
                "resumed_from_checkpoint": bool(checkpoint.storyboard),
            },
        )
        if checkpoint.storyboard is not None:
            storyboard = checkpoint.storyboard
        else:
            prompt_mode = "gemini"
            try:
                prompt_pack = await self._build_storyboard_prompts(client, types, context, creative, outline)
            except ProductionBriefError as exc:
                # A validated shot outline is more valuable than blocking the entire
                # brief because optional prompt enrichment failed. Build conservative
                # prompts from the approved outline and surface the fallback for review.
                logger.warning("Falling back to deterministic storyboard prompts: %s", exc)
                prompt_pack = AiStoryboardPromptPack(prompts=[])
                prompt_mode = "deterministic_fallback"
            storyboard = self._merge_storyboard(
                outline,
                prompt_pack,
                identity=creative.production_identity,
                prompt_generation_mode=prompt_mode,
            )
            checkpoint.storyboard = storyboard
            self._save_checkpoint(checkpoint_key, checkpoint)

        # 4) Publishing package
        self._report_stage(
            ProductionBriefJobStage.BUILDING_PUBLISHING_PACKAGE,
            "Reusing the saved publishing package" if checkpoint.publishing else "Preparing the review-ready publishing package",
            4,
            total,
            {
                "step_label": "Publishing package",
                "gemini_calls": self.gemini_calls,
                "storyboard_shots": len(storyboard.shots),
                "resumed_from_checkpoint": bool(checkpoint.publishing),
            },
        )
        if checkpoint.publishing is not None:
            publishing = checkpoint.publishing
        else:
            publishing_ai = await self._build_publishing_package(client, types, context, creative, storyboard)
            publishing = PublishingPackage.model_validate(
                publishing_ai.model_dump(
                    exclude={"character_name_used", "setting_anchor_used", "primary_prop_used"}
                )
            )
            publishing.hashtags = self._normalize_hashtags(publishing.hashtags)
            publishing.review_notes = self._augment_review_notes(
                publishing.review_notes, creative.production_identity
            )
            checkpoint.publishing = publishing
            checkpoint.publishing_character_name_used = publishing_ai.character_name_used
            checkpoint.publishing_setting_anchor_used = publishing_ai.setting_anchor_used
            checkpoint.publishing_primary_prop_used = publishing_ai.primary_prop_used
            self._save_checkpoint(checkpoint_key, checkpoint)

        consistency_report = self._build_consistency_report(
            creative=creative,
            storyboard=storyboard,
            publishing=publishing,
            publishing_identity_echo=(
                checkpoint.publishing_character_name_used or creative.production_identity.character_name,
                checkpoint.publishing_setting_anchor_used or creative.production_identity.setting_anchor,
                checkpoint.publishing_primary_prop_used or creative.production_identity.primary_prop,
            ),
        )
        direction_fidelity = self._build_direction_fidelity_report(
            contract=fidelity_contract,
            recommendation=recommendation,
            creative=creative,
            storyboard=storyboard,
            publishing=publishing,
        )

        if source_snapshot is None:
            raise ProductionBriefError("The immutable source direction snapshot is missing for this production brief.")

        character_identity_evidence = self._build_character_identity_evidence(
            analysis=analysis,
            dna=dna,
            recommendation=recommendation,
            creative=creative,
        )

        return ProductionBriefResult(
            generated_at=datetime.now(timezone.utc),
            source_snapshot=source_snapshot,
            model=self.settings.gemini_model,
            gemini_calls=self.gemini_calls,
            selected_recommendation=recommendation,
            creative_direction=creative,
            storyboard=storyboard,
            publishing=publishing,
            consistency_report=consistency_report,
            direction_fidelity=direction_fidelity,
            evidence_anchor=list(recommendation.evidence_signals),
            closest_archive_matches=list(recommendation.closest_archive_matches),
            character_identity_evidence=character_identity_evidence,
        )

    @staticmethod
    def _normalize_character_name(value: str) -> str:
        return " ".join((value or "").strip().casefold().split())

    @staticmethod
    def _video_thumbnail_url(video) -> Optional[str]:
        thumbnails = getattr(video, "thumbnails", None)
        if thumbnails is None:
            return None
        return (
            getattr(thumbnails, "high", None)
            or getattr(thumbnails, "standard", None)
            or getattr(thumbnails, "medium", None)
            or getattr(thumbnails, "default", None)
            or getattr(thumbnails, "maxres", None)
        )

    @classmethod
    def _build_character_identity_evidence(
        cls,
        *,
        analysis: AnalysisResult,
        dna: ContentDnaResult,
        recommendation: NextContentRecommendation,
        creative: CreativeDirection,
    ) -> Optional[CharacterIdentityEvidence]:
        """Resolve the production character to Content DNA's deterministic character evidence.

        Archive similarity is intentionally not used here: archive matches explain concept
        similarity, while this evidence answers what the recurring character looked like in
        prior channel posts.
        """
        requested_names = [
            creative.production_identity.character_name,
            *recommendation.recommended_characters,
        ]
        requested_keys = {cls._normalize_character_name(name) for name in requested_names if name}
        requested_keys.discard("")
        if not requested_keys:
            return None

        matched = None
        for character in dna.characters:
            character_names = [character.name, *character.aliases]
            character_keys = {cls._normalize_character_name(name) for name in character_names if name}
            if requested_keys & character_keys:
                matched = character
                break
        if matched is None:
            return None

        aliases = list(dict.fromkeys([matched.name, *matched.aliases]))
        alias_keys = {cls._normalize_character_name(name) for name in aliases if name}
        video_map = {video.video_id: video for video in analysis.videos}
        classification_map = {item.video_id: item for item in dna.video_classifications}

        def literal_name_present(text: str) -> bool:
            normalized_text = text or ""
            for alias in aliases:
                candidate = (alias or "").strip()
                if candidate and re.search(rf"(?<!\w){re.escape(candidate)}(?!\w)", normalized_text, flags=re.IGNORECASE):
                    return True
            return False

        ranked = []
        for position, video_id in enumerate(matched.evidence_video_ids):
            video = video_map.get(video_id)
            if video is None:
                continue
            thumbnail_url = cls._video_thumbnail_url(video)
            if not thumbnail_url:
                continue

            score = 0.0
            if literal_name_present(video.title):
                score += 100.0
            else:
                metadata_blob = " ".join(
                    part
                    for part in [video.description, " ".join(video.tags or [])]
                    if part
                )
                if literal_name_present(metadata_blob):
                    score += 55.0

            classification = classification_map.get(video_id)
            if classification is not None:
                classified_names = {
                    cls._normalize_character_name(item.name)
                    for item in classification.characters
                    if item.name
                }
                if classified_names & alias_keys:
                    score += 25.0
                if classification.visual_evidence_available:
                    score += 15.0
                score += max(0.0, min(1.0, float(classification.confidence))) * 10.0

            # Preserve deterministic evidence order as the final tie-breaker.
            ranked.append((score, -position, video, thumbnail_url))

        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        source_videos = [
            EvidenceVideoRef(
                video_id=video.video_id,
                title=video.title,
                views=video.view_count,
                performance_tier="identity_evidence",
                thumbnail_url=thumbnail_url,
                watch_url=video.watch_url,
            )
            for _, _, video, thumbnail_url in ranked[:6]
        ]

        return CharacterIdentityEvidence(
            character_name=matched.name,
            aliases=[alias for alias in aliases if cls._normalize_character_name(alias) != cls._normalize_character_name(matched.name)],
            description=matched.description,
            evidence_video_ids=list(matched.evidence_video_ids),
            source_videos=source_videos,
            resolved_from_content_dna=True,
        )

    def _validate_configuration(self) -> None:
        if not self.settings.google_cloud_project:
            raise ProductionBriefError(
                "Vertex AI is not configured. Set GOOGLE_CLOUD_PROJECT and authenticate with Application Default Credentials."
            )

    def _create_genai_client(self):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise ProductionBriefError(
                "google-genai is not installed. Run: pip install -r requirements.txt"
            ) from exc

        try:
            client = genai.Client(
                vertexai=True,
                project=self.settings.google_cloud_project,
                location=self.settings.google_cloud_location,
                http_options=types.HttpOptions(api_version="v1"),
            )
        except Exception as exc:
            raise ProductionBriefError(f"Could not initialize Vertex AI: {exc}") from exc
        return client, types

    def _creative_context(
        self,
        analysis: AnalysisResult,
        dna: ContentDnaResult,
        recommendation: NextContentRecommendation,
        fidelity_contract: DirectionFidelityContract,
        fidelity_mode: ProductionFidelityMode,
    ) -> Dict[str, str]:
        tones = ", ".join(item.label for item in dna.voice_tone[:6]) or "not explicitly summarized"
        evidence_labels = "; ".join(
            f"{signal.kind}: {signal.name} — {signal.description}"
            for signal in recommendation.evidence_signals
        ) or "No additional Content DNA labels were attached."
        characters = ", ".join(recommendation.recommended_characters) or "No recurring character explicitly required"
        lanes = ", ".join(recommendation.strategy_lanes) or "No strategy lanes supplied"
        closest = "; ".join(match.video.title for match in recommendation.closest_archive_matches[:3]) or "None"
        return {
            "channel": analysis.channel.title,
            "identity": dna.identity.summary,
            "content_promise": dna.identity.content_promise,
            "dominant_format": dna.identity.dominant_format,
            "language_style": dna.identity.language_style,
            "voice_tones": tones,
            "recommendation_title": recommendation.title,
            "recommendation_concept": recommendation.concept,
            "recommendation_hook": recommendation.hook,
            "recommendation_format": recommendation.format,
            "recommended_characters": characters,
            "strategy_lanes": lanes,
            "evidence_labels": evidence_labels,
            "closest_archive_titles": closest,
            "fidelity_mode": fidelity_mode.value,
            "source_subject_count": str(fidelity_contract.explicit_subject_count or "not explicit"),
            "source_required_characters": ", ".join(fidelity_contract.required_characters) or "none explicitly required",
            "source_core_terms": ", ".join(fidelity_contract.core_terms) or "none",
            "source_concept_terms": ", ".join(fidelity_contract.concept_terms) or "none",
            "source_summary": fidelity_contract.source_summary,
        }

    async def _build_creative_direction(self, client, types, context: Dict[str, str]):
        prompt = f"""
Channel: {context['channel']}
Channel identity: {context['identity']}
Content promise: {context['content_promise']}
Dominant format: {context['dominant_format']}
Language/style: {context['language_style']}
Voice/tone labels: {context['voice_tones']}

HUMAN-SELECTED RECOVERY DIRECTION
Title: {context['recommendation_title']}
Concept: {context['recommendation_concept']}
Hook: {context['recommendation_hook']}
Format: {context['recommendation_format']}
Recurring characters requested: {context['recommended_characters']}
Strategy lanes: {context['strategy_lanes']}

Semantically relevant Content DNA labels (no performance numbers):
{context['evidence_labels']}

Closest archive titles, provided only to avoid accidental repetition:
{context['closest_archive_titles']}

APPROVED-DIRECTION FIDELITY CONTRACT
Mode: {context['fidelity_mode']}
Source summary: {context['source_summary']}
Explicit subject count: {context['source_subject_count']}
Required named characters: {context['source_required_characters']}
Core source terms: {context['source_core_terms']}
Additional concept anchors: {context['source_concept_terms']}

The approved Recovery Intelligence direction is the source of truth. Preserve its subject count, named characters, primary activity, setting logic, and key novelty. Do not silently simplify a multi-subject direction into one subject. If Mode is STRICT, treat every explicit source constraint as mandatory and prefer literal preservation over creative adaptation.

PRODUCTION IDENTITY REQUIREMENTS
- Establish one canonical lead character identity for this brief, plus the total subject_count and supporting_subjects required by the approved direction.
- If a recurring character is explicitly requested above, production_identity.character_name MUST use that exact name and identity_source should be "existing_character".
- If no recurring character is required, choose one stable name only if the concept benefits from a named persona; otherwise use a stable generic descriptor such as "the pastry chef dog" and identity_source "generic_character".
- production_identity must lock subject_count, supporting_subjects, species/subject, appearance, wardrobe, personality, primary prop, setting anchor, lighting style, and anatomy rule.
- For a non-human animal, anatomy_rule must explicitly keep visible limbs animal-owned (for example an anthropomorphic paw in a pastry glove) and must prohibit a visible human hand/arm from masquerading as the animal.
- character_direction, opening_hook, continuity_rules, avoid, and asset_checklist must all agree with this Production Identity.

STRUCTURED OUTPUT REQUIREMENTS
- format MUST be a short production-format label of at most 100 characters, not a descriptive paragraph.
- Summarize a verbose Recovery Format instead of copying it verbatim into format.
- Keep every structured field concise enough to satisfy the supplied response schema.

Create one production-ready creative direction. Keep it faithful to the approved idea, make the visual action easy to execute in a short video, and preserve recurring character identity. For avoid, include repetition/copy risks or continuity mistakes a human reviewer should watch for. Asset checklist should list only the assets actually needed for this brief.
""".strip()
        return await self._structured_call(
            client=client,
            types=types,
            prompt=prompt,
            schema=AiCreativeDirection,
            max_output_tokens=4200,
            temperature=0.35,
            failure_message="Gemini could not finish the creative-direction pass after multiple attempts.",
        )

    async def _build_storyboard_outline(self, client, types, context, creative: CreativeDirection):
        prompt = f"""
Channel: {context['channel']}
Approved concept: {context['recommendation_title']} — {context['recommendation_concept']}
Recurring characters: {context['recommended_characters']}
Channel style: {context['language_style']}; tones: {context['voice_tones']}

CREATIVE DIRECTION
Working title: {creative.working_title}
Objective: {creative.creative_objective}
Promise: {creative.one_sentence_promise}
Opening hook: {creative.opening_hook}
Narrative arc: {creative.narrative_arc}
Target duration: {creative.target_duration_seconds} seconds
PRODUCTION IDENTITY (LOCKED)
Character name: {creative.production_identity.character_name}
Subject count: {creative.production_identity.subject_count}
Supporting subjects: {', '.join(creative.production_identity.supporting_subjects) or 'none'}
Identity source: {creative.production_identity.identity_source}
Species/subject: {creative.production_identity.species_or_subject}
Appearance: {creative.production_identity.appearance}
Wardrobe: {creative.production_identity.wardrobe}
Personality: {', '.join(creative.production_identity.personality)}
Primary prop: {creative.production_identity.primary_prop}
Setting anchor: {creative.production_identity.setting_anchor}
Lighting style: {creative.production_identity.lighting_style}
Anatomy rule: {creative.production_identity.anatomy_rule}

Character direction: {creative.character_direction}
Setting: {creative.setting}
Continuity rules: {'; '.join(creative.continuity_rules)}
Avoid: {'; '.join(creative.avoid)}

Build a compact storyboard of 4 to 7 shots. Durations should add up approximately to the target duration. Keep each visual_action concrete and concise. Keep on-screen text and dialogue short enough to read or hear within the shot. Do NOT write media-generation prompts in this pass; this pass is only the validated shot outline.
""".strip()
        return await self._structured_call(
            client=client,
            types=types,
            prompt=prompt,
            schema=AiStoryboardOutline,
            max_output_tokens=3500,
            temperature=0.22,
            failure_message="Gemini could not finish the compact storyboard outline after multiple attempts.",
        )

    async def _build_storyboard_prompts(self, client, types, context, creative: CreativeDirection, outline: AiStoryboardOutline):
        shot_summary = "\n".join(
            f"Shot {shot.shot_number}: {shot.duration_seconds}s | purpose={shot.purpose} | action={shot.visual_action} | camera={shot.camera_direction}"
            for shot in outline.shots
        )
        prompt = f"""
Channel: {context['channel']}
Approved concept: {context['recommendation_title']} — {context['recommendation_concept']}
Recurring characters: {context['recommended_characters']}
PRODUCTION IDENTITY (LOCKED)
Character name: {creative.production_identity.character_name}
Subject count: {creative.production_identity.subject_count}
Supporting subjects: {', '.join(creative.production_identity.supporting_subjects) or 'none'}
Species/subject: {creative.production_identity.species_or_subject}
Appearance: {creative.production_identity.appearance}
Wardrobe: {creative.production_identity.wardrobe}
Primary prop: {creative.production_identity.primary_prop}
Setting anchor: {creative.production_identity.setting_anchor}
Lighting style: {creative.production_identity.lighting_style}
Anatomy rule: {creative.production_identity.anatomy_rule}

Character direction: {creative.character_direction}
Setting: {creative.setting}
Continuity rules: {'; '.join(creative.continuity_rules)}
Avoid: {'; '.join(creative.avoid)}

VALIDATED SHOT OUTLINE
{shot_summary}

For every shot number above, write exactly one concise media-generation prompt. Preserve the same character identity, wardrobe, scale, setting logic, props, and lighting across shots unless the outline explicitly changes them. Each prompt must be self-contained enough for a media-generation model, but keep it under roughly 120 words. Return one prompt for every shot number and no extra shots.
""".strip()
        return await self._structured_call(
            client=client,
            types=types,
            prompt=prompt,
            schema=AiStoryboardPromptPack,
            max_output_tokens=4200,
            temperature=0.25,
            failure_message="Gemini could not finish the media-prompt enrichment pass after multiple attempts.",
        )

    async def _build_publishing_package(
        self,
        client,
        types,
        context,
        creative: CreativeDirection,
        storyboard: StoryboardPlan,
    ):
        shot_summary = "\n".join(
            f"- Shot {shot.shot_number}: {shot.visual_action} | text: {shot.on_screen_text or 'none'} | dialogue: {shot.voiceover_or_dialogue or 'none'}"
            for shot in storyboard.shots
        )
        prompt = f"""
Channel: {context['channel']}
Channel language/style: {context['language_style']}
Voice/tone: {context['voice_tones']}
Approved content direction: {context['recommendation_title']}
Creative promise: {creative.one_sentence_promise}
Opening hook: {creative.opening_hook}

PRODUCTION IDENTITY (LOCKED)
Character name: {creative.production_identity.character_name}
Subject count: {creative.production_identity.subject_count}
Supporting subjects: {', '.join(creative.production_identity.supporting_subjects) or 'none'}
Species/subject: {creative.production_identity.species_or_subject}
Appearance: {creative.production_identity.appearance}
Wardrobe: {creative.production_identity.wardrobe}
Primary prop: {creative.production_identity.primary_prop}
Setting anchor: {creative.production_identity.setting_anchor}
Lighting style: {creative.production_identity.lighting_style}

Storyboard summary:
{shot_summary}

Create a concise publishing package for human review. The YouTube title should be specific and natural, not clickbait. The description and social caption should match the channel voice without making performance claims. Hashtags must be relevant and limited. The thumbnail concept should describe one clear frame rather than include lots of text. Accessibility alt text should describe the visible content plainly. review_notes should flag any continuity, factual, brand, or generation-quality checks a human should make before publishing.

For consistency validation, character_name_used MUST exactly repeat the locked Character name above, setting_anchor_used MUST exactly repeat the locked Setting anchor, and primary_prop_used MUST exactly repeat the locked Primary prop. Do not invent a different character name anywhere in the title, description, caption, thumbnail concept, audio direction, alt text, or review notes.
""".strip()
        return await self._structured_call(
            client=client,
            types=types,
            prompt=prompt,
            schema=AiPublishingPackage,
            max_output_tokens=3800,
            temperature=0.32,
            failure_message="Gemini could not finish the publishing-package pass after multiple attempts.",
        )

    @staticmethod
    def _validation_repair_instruction(exc: ValidationError) -> str:
        """Turn Pydantic validation failures into a compact model repair request."""
        lines = [
            "CORRECTION REQUIRED",
            "The previous structured response was rejected by ReviveAI application validation.",
            "Correct only the invalid fields while preserving the requested creative direction.",
        ]
        for error in exc.errors(include_url=False, include_input=False):
            loc = ".".join(str(part) for part in error.get("loc", ())) or "response"
            kind = str(error.get("type") or "validation_error")
            ctx = error.get("ctx") or {}
            if kind == "string_too_long" and ctx.get("max_length") is not None:
                requirement = f"must be at most {ctx['max_length']} characters"
            elif kind == "string_too_short" and ctx.get("min_length") is not None:
                requirement = f"must be at least {ctx['min_length']} characters"
            elif kind == "too_long" and ctx.get("max_length") is not None:
                requirement = f"must contain at most {ctx['max_length']} items"
            elif kind == "too_short" and ctx.get("min_length") is not None:
                requirement = f"must contain at least {ctx['min_length']} items"
            elif kind == "less_than_equal" and ctx.get("le") is not None:
                requirement = f"must be less than or equal to {ctx['le']}"
            elif kind == "greater_than_equal" and ctx.get("ge") is not None:
                requirement = f"must be greater than or equal to {ctx['ge']}"
            else:
                requirement = str(error.get("msg") or "does not satisfy the schema")
            lines.append(f"- {loc}: {requirement}.")
        lines.extend(
            [
                "Return the COMPLETE JSON object again, not a patch or explanation.",
                "Do not add fields that are not in the supplied schema.",
            ]
        )
        return "\n".join(lines)

    async def _structured_call(
        self,
        *,
        client,
        types,
        prompt,
        schema,
        max_output_tokens,
        temperature,
        failure_message,
    ):
        attempts = max(
            1,
            int(
                getattr(
                    self.settings,
                    "production_brief_retry_attempts",
                    self.settings.content_dna_retry_attempts,
                )
            ),
        )
        timeout_seconds = max(
            5.0,
            float(getattr(self.settings, "production_brief_request_timeout_seconds", 90.0)),
        )
        last_error: Optional[Exception] = None
        attempt_prompt = prompt

        # Do not pass a Pydantic model through response_schema. google-genai's
        # narrower OpenAPI schema rejects valid Pydantic JSON-Schema keywords.
        # Pydantic remains the authoritative application validator after response.
        response_json_schema = self._gemini_response_json_schema(schema)
        schema_name = getattr(schema, "__name__", str(schema))

        for attempt_index in range(1, attempts + 1):
            started_at = datetime.now(timezone.utc)
            self.gemini_calls += 1
            self._report_call_progress(
                gemini_calls=self.gemini_calls,
                gemini_schema=schema_name,
                gemini_attempt=attempt_index,
                gemini_attempts=attempts,
                gemini_call_state="requesting",
                gemini_attempt_started_at=started_at.isoformat(),
                gemini_timeout_seconds=timeout_seconds,
                gemini_last_error=None,
                gemini_last_error_type=None,
            )

            # Reserve before provider submission, once per attempt. An unknown
            # provider outcome retains the reservation pending reconciliation.
            ledger, operation_id, estimate = self._reserve_gemini_attempt()
            try:
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=self.settings.gemini_model,
                        contents=attempt_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=PRODUCTION_SYSTEM,
                            temperature=temperature,
                            candidate_count=1,
                            response_mime_type="application/json",
                            response_json_schema=response_json_schema,
                            max_output_tokens=max_output_tokens,
                        ),
                    ),
                    timeout=timeout_seconds,
                )

                # A returned provider response is billable even if schema validation
                # fails. Reconcile before parsing so malformed JSON is accounted for.
                ledger.reconcile(self._budget_production_id, operation_id, estimate, estimate)
                parsed = getattr(response, "parsed", None)
                if isinstance(parsed, schema):
                    result = parsed
                elif parsed is not None:
                    result = schema.model_validate(parsed)
                else:
                    response_text = getattr(response, "text", None)
                    if not response_text:
                        raise ValueError("Gemini returned an empty structured response.")
                    result = schema.model_validate_json(response_text)

                self._report_call_progress(
                    gemini_calls=self.gemini_calls,
                    gemini_schema=schema_name,
                    gemini_attempt=attempt_index,
                    gemini_attempts=attempts,
                    gemini_call_state="completed",
                    gemini_attempt_finished_at=datetime.now(timezone.utc).isoformat(),
                    gemini_last_error=None,
                    gemini_last_error_type=None,
                )
                return result

            except asyncio.TimeoutError as exc:
                # Timeout does not establish whether the provider charged.
                raise ProductionBriefError(
                    "Gemini request outcome is uncertain; reservation held for reconciliation"
                ) from exc

            except ValidationError as exc:
                last_error = exc
                repair_instruction = self._validation_repair_instruction(exc)
                logger.warning(
                    "Production brief structured validation failed schema=%s attempt=%s/%s: %s",
                    schema_name,
                    attempt_index,
                    attempts,
                    repair_instruction.replace("\n", " | "),
                )
                self._report_call_progress(
                    gemini_calls=self.gemini_calls,
                    gemini_schema=schema_name,
                    gemini_attempt=attempt_index,
                    gemini_attempts=attempts,
                    gemini_call_state="validation_repair",
                    gemini_attempt_finished_at=datetime.now(timezone.utc).isoformat(),
                    gemini_last_error_type="structured_validation",
                    gemini_last_error=repair_instruction,
                )
                # Start from the original user prompt so repeated repair attempts do
                # not accumulate contradictory instructions.
                attempt_prompt = f"{prompt}\n\n{repair_instruction}"

            except Exception as exc:
                # Do not submit a duplicate request when provider billing is unknown.
                raise ProductionBriefError(
                    "Gemini call outcome is uncertain; reservation held for reconciliation"
                ) from exc

            if attempt_index < attempts:
                self._report_call_progress(
                    gemini_calls=self.gemini_calls,
                    gemini_schema=schema_name,
                    gemini_attempt=attempt_index + 1,
                    gemini_attempts=attempts,
                    gemini_call_state="retrying",
                )
                await asyncio.sleep(1.2 * (2 ** (attempt_index - 1)))

        self._report_call_progress(
            gemini_calls=self.gemini_calls,
            gemini_schema=schema_name,
            gemini_attempt=attempts,
            gemini_attempts=attempts,
            gemini_call_state="exhausted",
        )

        if isinstance(last_error, asyncio.TimeoutError):
            raise ProductionBriefError(
                f"ReviveAI could not complete this production step because the AI request timed out after {attempts} attempts. "
                "Retry the production brief; completed production stages remain checkpointed."
            ) from last_error
        raise ProductionBriefError(failure_message) from last_error

    @classmethod
    def _gemini_response_json_schema(cls, schema_model) -> Dict:
        """Return a Gemini-compatible JSON Schema for structured output.

        Vertex AI's ``response_json_schema`` supports a useful subset of JSON
        Schema. Pydantic can emit additional keywords (for example
        ``exclusiveMinimum``, ``minLength``, and ``default``). Unsupported
        keywords are removed here. Exclusive numeric bounds are relaxed to the
        corresponding inclusive bound for generation guidance; the original
        Pydantic model still validates the final response, so application-level
        constraints remain authoritative.
        """

        raw = schema_model.model_json_schema()
        return cls._sanitize_gemini_json_schema(raw)

    @classmethod
    def _sanitize_gemini_json_schema(cls, value):
        if isinstance(value, list):
            return [cls._sanitize_gemini_json_schema(item) for item in value]
        if not isinstance(value, dict):
            return value

        supported = {
            "$id",
            "$defs",
            "$ref",
            "$anchor",
            "type",
            "format",
            "title",
            "description",
            "enum",
            "items",
            "prefixItems",
            "minItems",
            "maxItems",
            "minimum",
            "maximum",
            "anyOf",
            "oneOf",
            "properties",
            "additionalProperties",
            "required",
            "propertyOrdering",
        }

        cleaned: Dict = {}

        # Google response_json_schema does not accept exclusiveMinimum /
        # exclusiveMaximum. Preserve useful generation guidance with inclusive
        # equivalents; Pydantic enforces the exact exclusive constraint later.
        if "exclusiveMinimum" in value and "minimum" not in value:
            cleaned["minimum"] = value["exclusiveMinimum"]
        if "exclusiveMaximum" in value and "maximum" not in value:
            cleaned["maximum"] = value["exclusiveMaximum"]

        for key, item in value.items():
            if key not in supported:
                continue

            if key in {"properties", "$defs"} and isinstance(item, dict):
                cleaned[key] = {
                    name: cls._sanitize_gemini_json_schema(child)
                    for name, child in item.items()
                }
            elif key in {"items"} and isinstance(item, dict):
                cleaned[key] = cls._sanitize_gemini_json_schema(item)
            elif key in {"prefixItems", "anyOf", "oneOf"} and isinstance(item, list):
                cleaned[key] = [cls._sanitize_gemini_json_schema(child) for child in item]
            elif key == "additionalProperties" and isinstance(item, dict):
                cleaned[key] = cls._sanitize_gemini_json_schema(item)
            else:
                cleaned[key] = item

        return cleaned

    @staticmethod
    def _merge_storyboard(
        outline: AiStoryboardOutline,
        prompt_pack: AiStoryboardPromptPack,
        *,
        identity: ProductionIdentity,
        prompt_generation_mode: str = "gemini",
    ) -> StoryboardPlan:
        prompt_by_shot = {item.shot_number: item.generation_prompt.strip() for item in prompt_pack.prompts if item.generation_prompt.strip()}
        shots: list[StoryboardShot] = []
        for index, outline_shot in enumerate(outline.shots[:7], start=1):
            generation_prompt = prompt_by_shot.get(outline_shot.shot_number)
            if not generation_prompt:
                # Keep the brief usable even if the model returned a prompt with a
                # mismatched number. The deterministic fallback is intentionally
                # descriptive, not a new creative decision.
                generation_prompt = f"{outline_shot.visual_action}. {outline_shot.camera_direction}."
            generation_prompt = ProductionBriefService._apply_identity_lock_to_prompt(
                generation_prompt, identity
            )
            shots.append(
                StoryboardShot(
                    shot_number=index,
                    duration_seconds=round(max(0.5, min(20.0, outline_shot.duration_seconds)), 1),
                    purpose=outline_shot.purpose,
                    visual_action=outline_shot.visual_action,
                    camera_direction=outline_shot.camera_direction,
                    on_screen_text=outline_shot.on_screen_text,
                    voiceover_or_dialogue=outline_shot.voiceover_or_dialogue,
                    generation_prompt=generation_prompt,
                )
            )
        return StoryboardPlan(
            shots=shots,
            estimated_duration_seconds=round(sum(item.duration_seconds for item in shots), 1),
            prompt_generation_mode=prompt_generation_mode,
        )

    @staticmethod
    def _normalize_words(value: str) -> list[str]:
        stop = {
            "a", "an", "and", "the", "of", "to", "in", "on", "at", "with", "for", "from",
            "is", "are", "was", "were", "be", "as", "by", "into", "their", "his", "her",
            "this", "that", "these", "those", "tiny", "miniature", "cute", "adorable", "dog",
            "dogs", "pet", "pets", "video", "short", "reviveai",
        }
        words = re.findall(r"[a-z0-9]+", (value or "").casefold())
        normalized: list[str] = []
        for word in words:
            if word in stop or len(word) < 3:
                continue
            if word.endswith("ies") and len(word) > 4:
                word = word[:-3] + "y"
            elif word.endswith("ing") and len(word) > 5:
                word = word[:-3]
            elif word.endswith("ed") and len(word) > 4:
                word = word[:-2]
            elif word.endswith("s") and len(word) > 4:
                word = word[:-1]
            if word not in normalized:
                normalized.append(word)
        return normalized

    @classmethod
    def _build_direction_fidelity_contract(
        cls, recommendation: NextContentRecommendation
    ) -> DirectionFidelityContract:
        combined = f"{recommendation.title}. {recommendation.concept}. {recommendation.hook}"
        lower = combined.casefold()
        number_words = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
            "seven": 7, "eight": 8,
        }
        subject_count: Optional[int] = None
        animal_nouns = r"(?:dog|dogs|cat|cats|pet|pets|animal|animals|puppy|puppies|kitten|kittens|character|characters)"
        match = re.search(rf"\b([1-8]|one|two|three|four|five|six|seven|eight)\s+{animal_nouns}\b", lower)
        if match:
            raw = match.group(1)
            subject_count = int(raw) if raw.isdigit() else number_words.get(raw)
        elif len(recommendation.recommended_characters) > 1:
            subject_count = len({item.casefold() for item in recommendation.recommended_characters if item.strip()})
        elif re.search(rf"\b(?:a|an|one)\s+{animal_nouns}\b", lower):
            subject_count = 1

        required_chars = []
        seen = set()
        for item in recommendation.recommended_characters:
            value = item.strip()
            if value and value.casefold() not in seen:
                seen.add(value.casefold())
                required_chars.append(value)

        title_terms = cls._normalize_words(recommendation.title)[:8]
        concept_terms = [word for word in cls._normalize_words(recommendation.concept) if word not in title_terms][:10]
        summary_parts = [recommendation.title]
        if subject_count:
            summary_parts.append(f"{subject_count} subject{'s' if subject_count != 1 else ''}")
        if required_chars:
            summary_parts.append("characters: " + ", ".join(required_chars))
        return DirectionFidelityContract(
            source_title=recommendation.title,
            source_concept=recommendation.concept,
            required_characters=required_chars,
            explicit_subject_count=subject_count,
            core_terms=title_terms,
            concept_terms=concept_terms,
            source_summary=" · ".join(summary_parts),
        )

    @classmethod
    def _lock_creative_direction(
        cls,
        creative: CreativeDirection,
        recommendation: NextContentRecommendation,
        contract: DirectionFidelityContract,
        fidelity_mode: ProductionFidelityMode,
    ) -> CreativeDirection:
        identity = creative.production_identity
        requested = [item.strip() for item in recommendation.recommended_characters if item.strip()]
        if len(requested) == 1:
            identity = identity.model_copy(
                update={
                    "character_name": requested[0],
                    "identity_source": "existing_character",
                }
            )

        supporting = list(identity.supporting_subjects)
        if contract.explicit_subject_count and contract.explicit_subject_count > 1 and not supporting:
            supporting = [f"supporting subject {index}" for index in range(2, contract.explicit_subject_count + 1)]
        if fidelity_mode == ProductionFidelityMode.STRICT and contract.explicit_subject_count:
            identity = identity.model_copy(
                update={
                    "subject_count": contract.explicit_subject_count,
                    "supporting_subjects": supporting[: max(0, contract.explicit_subject_count - 1)],
                }
            )

        continuity = list(creative.continuity_rules)
        identity_rules = [
            f"Canonical character name stays exactly '{identity.character_name}' across the storyboard, publishing copy, and future media generation.",
            f"Subject count stays locked at {identity.subject_count}; supporting subjects: {', '.join(identity.supporting_subjects) or 'none'}.",
            f"Wardrobe stays locked: {identity.wardrobe}",
            f"Primary prop stays locked: {identity.primary_prop}",
            f"Setting anchor stays locked: {identity.setting_anchor}",
            f"Lighting stays locked: {identity.lighting_style}",
            f"Anatomy lock: {identity.anatomy_rule}",
        ]
        for item in identity_rules:
            if item.casefold() not in {value.casefold() for value in continuity}:
                continuity.append(item)

        avoid = list(creative.avoid)
        anatomy_lower = identity.anatomy_rule.casefold()
        if any(term in anatomy_lower for term in ("no human hand", "no visible human", "prohibit", "must not")):
            rule = "Do not show a visible human hand or arm as if it belongs to the animal character."
            if rule.casefold() not in {value.casefold() for value in avoid}:
                avoid.append(rule)

        return creative.model_copy(
            update={
                "production_identity": identity,
                "continuity_rules": continuity[:12],
                "avoid": avoid[:9],
            }
        )

    @staticmethod
    def _apply_identity_lock_to_prompt(prompt: str, identity: ProductionIdentity) -> str:
        lock = (
            f"CONTINUITY LOCK — Character: {identity.character_name}; "
            f"subject count: {identity.subject_count}; supporting subjects: {', '.join(identity.supporting_subjects) or 'none'}; "
            f"subject: {identity.species_or_subject}; appearance: {identity.appearance}; "
            f"wardrobe: {identity.wardrobe}; primary prop: {identity.primary_prop}; "
            f"setting: {identity.setting_anchor}; lighting: {identity.lighting_style}; "
            f"anatomy: {identity.anatomy_rule}. "
        )
        return f"{lock}SHOT: {prompt.strip()}"

    @staticmethod
    def _augment_review_notes(values: Sequence[str], identity: ProductionIdentity) -> list[str]:
        notes = [item.strip() for item in values if item and item.strip()]
        required = [
            f"Verify the approved subject count remains {identity.subject_count} across the storyboard and generated media.",
            f"Verify {identity.character_name}'s appearance and wardrobe match the locked Production Identity in every generated shot.",
            f"Verify the primary prop remains consistent: {identity.primary_prop}.",
            f"Verify the setting and lighting remain consistent with {identity.setting_anchor} and {identity.lighting_style}.",
            f"Verify anatomy follows this lock: {identity.anatomy_rule}",
        ]
        seen = {item.casefold() for item in notes}
        for item in required:
            if item.casefold() not in seen:
                notes.append(item)
                seen.add(item.casefold())
        return notes[:8]

    @classmethod
    def _term_coverage(cls, terms: Sequence[str], text: str) -> float:
        wanted = [term for term in terms if term]
        if not wanted:
            return 1.0
        haystack = set(cls._normalize_words(text))
        if not haystack:
            return 0.0
        matched = sum(1 for term in wanted if term in haystack)
        return matched / len(wanted)

    @classmethod
    def _build_direction_fidelity_report(
        cls,
        *,
        contract: DirectionFidelityContract,
        recommendation: NextContentRecommendation,
        creative: CreativeDirection,
        storyboard: StoryboardPlan,
        publishing: PublishingPackage,
    ) -> DirectionFidelityReport:
        identity = creative.production_identity
        checks: list[DirectionFidelityCheck] = []
        blocking: list[str] = []
        warnings: list[str] = []

        def add(
            key: str,
            label: str,
            passed: bool,
            source_value: str,
            brief_value: str,
            detail: str,
            *,
            blocking_failure: bool = False,
            warn_when_failed: bool = True,
        ) -> None:
            status = "PASS" if passed else ("BLOCK" if blocking_failure else "WARN")
            checks.append(
                DirectionFidelityCheck(
                    key=key,
                    label=label,
                    status=status,
                    source_value=source_value,
                    brief_value=brief_value,
                    detail=detail,
                )
            )
            if not passed:
                if blocking_failure:
                    blocking.append(detail)
                elif warn_when_failed:
                    warnings.append(detail)

        # 1) Subject count is a hard fidelity constraint only when the approved M1D
        # direction explicitly stated one. This catches silent simplification such as
        # "two dogs" becoming a single lead character in M2A.
        if contract.explicit_subject_count is not None:
            expected = contract.explicit_subject_count
            actual = identity.subject_count
            add(
                "subject_count",
                "Subject count",
                actual == expected,
                f"{expected} subject{'s' if expected != 1 else ''}",
                f"{actual} subject{'s' if actual != 1 else ''}",
                (
                    f"The production brief preserves the approved {expected}-subject direction."
                    if actual == expected
                    else f"The approved direction specifies {expected} subjects, but the production brief locks {actual}."
                ),
                blocking_failure=True,
            )
            if expected > 1:
                supporting_ok = len(identity.supporting_subjects) >= expected - 1
                add(
                    "supporting_subjects",
                    "Supporting subjects",
                    supporting_ok,
                    f"{expected - 1} supporting subject{'s' if expected - 1 != 1 else ''}",
                    ", ".join(identity.supporting_subjects) or "none",
                    (
                        "Supporting subjects are explicitly represented in the Production Identity."
                        if supporting_ok
                        else "The source direction requires multiple subjects, but the Production Identity does not describe the additional subjects clearly."
                    ),
                    blocking_failure=True,
                )

        # 2) Named characters from M1D must survive unchanged.
        generated_text = " ".join(
            [
                identity.character_name,
                " ".join(identity.supporting_subjects),
                creative.working_title,
                creative.creative_objective,
                creative.one_sentence_promise,
                creative.opening_hook,
                creative.narrative_arc,
                creative.character_direction,
                creative.setting,
                publishing.youtube_title,
                publishing.description,
                publishing.social_caption,
            ]
            + [shot.visual_action for shot in storyboard.shots]
        )
        for character in contract.required_characters:
            present = character.casefold() in generated_text.casefold()
            add(
                f"character_{character.casefold().replace(' ', '_')}",
                f"Required character: {character}",
                present,
                character,
                identity.character_name if present else "not found",
                (
                    f"The approved recurring character '{character}' remains present in the production brief."
                    if present
                    else f"The approved recurring character '{character}' is missing from the production brief."
                ),
                blocking_failure=True,
            )

        # 3) Core title/activity anchors are a deterministic lexical fidelity check.
        # It is intentionally conservative: it does not claim semantic equivalence, it
        # only verifies that the core source concepts remain visible in the brief.
        core_coverage = cls._term_coverage(contract.core_terms, generated_text)
        core_pass = core_coverage >= 0.5
        add(
            "core_direction",
            "Core direction",
            core_pass,
            contract.source_title,
            creative.working_title,
            (
                f"Core source concepts are preserved ({round(core_coverage * 100)}% anchor coverage)."
                if core_pass
                else f"The production brief may have drifted from the approved direction ({round(core_coverage * 100)}% core-anchor coverage)."
            ),
            blocking_failure=True,
        )

        concept_coverage = cls._term_coverage(contract.concept_terms, generated_text)
        concept_pass = concept_coverage >= 0.3 or not contract.concept_terms
        add(
            "source_details",
            "Source-detail coverage",
            concept_pass,
            contract.source_concept,
            creative.one_sentence_promise,
            (
                f"Key source details remain represented ({round(concept_coverage * 100)}% detail-anchor coverage)."
                if concept_pass
                else f"Several descriptive details from the approved concept are not represented ({round(concept_coverage * 100)}% detail-anchor coverage)."
            ),
            blocking_failure=False,
        )

        status = DirectionFidelityStatus.PASS if not blocking else DirectionFidelityStatus.REVIEW_REQUIRED
        return DirectionFidelityReport(
            status=status,
            contract=contract,
            checks=checks,
            blocking_issues=blocking,
            warnings=warnings,
        )

    _ANCHOR_STOPWORDS = {
        "a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "with", "for", "from",
        "is", "are", "be", "being", "that", "this", "its", "their", "his", "her", "as", "by",
        "miniature", "tiny", "small", "custom", "detailed", "decorative", "warm", "soft", "bright",
        "beautiful", "polished", "cozy", "whimsical", "elegant", "colorful", "traditional", "primary",
    }

    @classmethod
    def _anchor_terms(cls, value: str, limit: int = 5) -> list[str]:
        """Extract stable semantic anchors without requiring verbatim copy.

        The goal is intentionally modest: preserve the identifiable nouns/concepts in a
        locked prop or setting while allowing normal editorial rephrasing downstream.
        """
        terms: list[str] = []
        seen: set[str] = set()
        for token in cls._normalize_words(value):
            if len(token) < 3 or token in cls._ANCHOR_STOPWORDS:
                continue
            # light singular normalization for common English plurals
            if token.endswith("ies") and len(token) > 4:
                token = token[:-3] + "y"
            elif token.endswith("s") and not token.endswith("ss") and len(token) > 4:
                token = token[:-1]
            if token in seen:
                continue
            seen.add(token)
            terms.append(token)
            if len(terms) >= limit:
                break
        return terms

    @classmethod
    def _anchor_match(cls, canonical: str, echoed: str) -> tuple[bool, list[str], list[str]]:
        required = cls._anchor_terms(canonical)
        echo_terms = set(cls._anchor_terms(echoed, limit=20)) | set(cls._normalize_words(echoed))
        matched = [term for term in required if term in echo_terms]
        if not required:
            return bool(echoed.strip()), required, matched
        required_count = 1 if len(required) == 1 else 2
        coverage = len(matched) / len(required)
        # Two distinctive anchors are enough for a natural-language paraphrase. For
        # very short anchors, require at least half the concepts.
        passed = len(matched) >= required_count and (coverage >= 0.35 or len(matched) >= 3)
        return passed, required, matched

    @classmethod
    def _build_consistency_report(
        cls,
        *,
        creative: CreativeDirection,
        storyboard: StoryboardPlan,
        publishing: PublishingPackage,
        publishing_identity_echo: tuple[str, str, str],
    ) -> ProductionConsistencyReport:
        identity = creative.production_identity
        checks: list[ConsistencyCheck] = []
        blocking: list[str] = []
        warnings: list[str] = []

        def add(key: str, label: str, passed: bool, detail: str, *, blocking_failure: bool = False):
            status = "PASS" if passed else ("BLOCK" if blocking_failure else "WARN")
            checks.append(ConsistencyCheck(key=key, label=label, status=status, detail=detail))
            if not passed:
                (blocking if blocking_failure else warnings).append(detail)

        echoed_name, echoed_setting, echoed_prop = publishing_identity_echo
        name_ok = echoed_name.strip().casefold() == identity.character_name.strip().casefold()
        add(
            "character_name",
            "Canonical character name",
            name_ok,
            (
                f"Publishing package uses the locked character name '{identity.character_name}'."
                if name_ok
                else f"Publishing package echoed '{echoed_name}' instead of locked name '{identity.character_name}'."
            ),
            blocking_failure=True,
        )

        setting_ok, setting_terms, setting_matched = cls._anchor_match(identity.setting_anchor, echoed_setting)
        add(
            "setting_anchor",
            "Setting anchor",
            setting_ok,
            (
                f"Publishing copy preserved the setting anchors: {', '.join(setting_matched) or 'none'}."
                if setting_ok
                else f"Publishing copy did not preserve enough of the setting anchors ({', '.join(setting_terms) or 'none'})."
            ),
            blocking_failure=True,
        )

        prop_ok, prop_terms, prop_matched = cls._anchor_match(identity.primary_prop, echoed_prop)
        add(
            "primary_prop",
            "Primary prop",
            prop_ok,
            (
                f"Publishing copy preserved the primary-prop anchors: {', '.join(prop_matched) or 'none'}."
                if prop_ok
                else f"Publishing copy did not preserve enough of the primary-prop anchors ({', '.join(prop_terms) or 'none'})."
            ),
            blocking_failure=True,
        )

        shot_count_ok = 4 <= len(storyboard.shots) <= 7
        add(
            "shot_count",
            "Storyboard shot count",
            shot_count_ok,
            f"Storyboard contains {len(storyboard.shots)} shots; the production range is 4–7.",
            blocking_failure=True,
        )

        tolerance = max(2.0, creative.target_duration_seconds * 0.15)
        duration_delta = abs(storyboard.estimated_duration_seconds - creative.target_duration_seconds)
        add(
            "duration",
            "Target duration",
            duration_delta <= tolerance,
            f"Storyboard is {storyboard.estimated_duration_seconds:.1f}s against a {creative.target_duration_seconds}s target.",
            blocking_failure=False,
        )

        prompt_lock_ok = all(
            "CONTINUITY LOCK" in shot.generation_prompt
            and identity.character_name.casefold() in shot.generation_prompt.casefold()
            for shot in storyboard.shots
        )
        add(
            "prompt_identity_lock",
            "Media prompt identity lock",
            prompt_lock_ok,
            (
                "Every media-generation prompt carries the canonical Production Identity lock."
                if prompt_lock_ok
                else "One or more media-generation prompts are missing the canonical Production Identity lock."
            ),
            blocking_failure=True,
        )

        anatomy_rule = identity.anatomy_rule.casefold()
        visible_copy = " ".join(
            [creative.opening_hook, creative.character_direction]
            + [shot.visual_action for shot in storyboard.shots]
        ).casefold()
        forbids_human = any(
            token in anatomy_rule
            for token in ("no human hand", "no visible human", "must not", "prohibit")
        )
        anatomy_conflict = forbids_human and ("human hand" in visible_copy or "human arm" in visible_copy)
        add(
            "anatomy",
            "Anatomy continuity",
            not anatomy_conflict,
            (
                "Creative copy follows the locked anatomy rule."
                if not anatomy_conflict
                else "Creative copy mentions a visible human hand/arm even though the Production Identity forbids it."
            ),
            blocking_failure=True,
        )

        status = ProductionConsistencyStatus.PASS if not blocking else ProductionConsistencyStatus.REVIEW_REQUIRED
        return ProductionConsistencyReport(
            status=status,
            checks=checks,
            blocking_issues=blocking,
            warnings=warnings,
            anchors=ConsistencyAnchorSet(
                character_name=identity.character_name,
                setting_terms=setting_terms,
                primary_prop_terms=prop_terms,
            ),
        )

    @staticmethod
    def _normalize_shots(shots: Sequence[StoryboardShot]) -> list[StoryboardShot]:
        normalized: list[StoryboardShot] = []
        for index, shot in enumerate(shots[:8], start=1):
            normalized.append(
                shot.model_copy(
                    update={
                        "shot_number": index,
                        "duration_seconds": round(max(0.5, min(20.0, shot.duration_seconds)), 1),
                    }
                )
            )
        return normalized

    @staticmethod
    def _normalize_hashtags(values: Sequence[str]) -> list[str]:
        result: list[str] = []
        seen = set()
        for raw in values:
            value = (raw or "").strip().replace(" ", "")
            if not value:
                continue
            if not value.startswith("#"):
                value = f"#{value}"
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(value)
            if len(result) >= 8:
                break
        return result

    def _checkpoint_root(self) -> Path:
        root = tenant_scoped_root(Path(self.settings.content_dna_checkpoint_dir)) / "production_briefs"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _checkpoint_key(
        self,
        analysis: AnalysisResult,
        dna: ContentDnaResult,
        recommendation: NextContentRecommendation,
        fidelity_mode: ProductionFidelityMode,
    ) -> str:
        raw = json.dumps(
            {
                "version": self.CHECKPOINT_VERSION,
                "channel_id": analysis.channel.channel_id,
                "dna_generated_at": dna.generated_at.isoformat(),
                "recommendation_id": recommendation.recommendation_id,
                "title": recommendation.title,
                "concept": recommendation.concept,
                "model": self.settings.gemini_model,
                "fidelity_mode": fidelity_mode.value,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def _checkpoint_path(self, key: str) -> Path:
        return self._checkpoint_root() / f"{key}.json"

    def _load_checkpoint(self, key: str) -> ProductionBriefCheckpoint:
        path = self._checkpoint_path(key)
        if not path.exists():
            return ProductionBriefCheckpoint()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            checkpoint = ProductionBriefCheckpoint.model_validate(data)
            if checkpoint.version != self.CHECKPOINT_VERSION:
                return ProductionBriefCheckpoint()
            return checkpoint
        except Exception as exc:
            logger.warning("Ignoring invalid production brief checkpoint %s: %s", path, exc)
            return ProductionBriefCheckpoint()

    def _save_checkpoint(self, key: str, checkpoint: ProductionBriefCheckpoint) -> None:
        path = self._checkpoint_path(key)
        temp = path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(checkpoint.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(path)

    @staticmethod
    def _checkpoint_stage(checkpoint: ProductionBriefCheckpoint) -> str:
        if checkpoint.publishing is not None:
            return "publishing"
        if checkpoint.storyboard is not None:
            return "generation-prompts"
        if checkpoint.storyboard_outline is not None:
            return "shot-plan"
        if checkpoint.creative_direction is not None:
            return "creative-direction"
        if checkpoint.fidelity_contract is not None:
            return "direction-lock"
        return "none"
