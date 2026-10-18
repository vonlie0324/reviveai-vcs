from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, Optional
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.core.tenant import TenantScopedDict, tenant_scoped_root
from app.models.audio_finishing import AudioFinishingReviewStatus
from app.models.publishing_assistant import (
    InstagramPublishingCopy,
    PublishingDraft,
    PublishingDraftContent,
    PublishingDraftStatus,
    TikTokPublishingCopy,
    YouTubePublishingCopy,
)
from app.services.audio_finishing_job_service import AudioFinishingJobNotFoundError, audio_finishing_job_store
from app.services.delivery_package_service import delivery_package_store
from app.services.delivery_qc_service import DeliveryQcOverallStatus, DeliveryQcReportNotFoundError, delivery_qc_store, qc_allows_manual_delivery
from app.services.production_brief_job_service import ProductionBriefJobNotFoundError, production_brief_job_store
from app.services.firestore_job_repository import FirestoreJobRepository
from app.services.firestore_budget_service import FirestoreBudgetService
from app.services.channel_autonomy_policy import channel_policy_store
from app.services.ai_review_budget import review_cost_reservation_usd


logger = logging.getLogger(__name__)


class PublishingAssistantError(RuntimeError):
    pass


class PublishingDraftNotFoundError(KeyError):
    pass


class PublishingDraftStore:
    """Publishing drafts with Firestore durability and local mirroring."""

    def __init__(self, checkpoint_root: str):
        self._root = Path(checkpoint_root) / "publishing_assistant"
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._cache: TenantScopedDict[str, PublishingDraft] = TenantScopedDict()
        self._cloud = FirestoreJobRepository("publishing_drafts")

    def _assembly_root(self, assembly_job_id: str) -> Path:
        path = tenant_scoped_root(self._root) / assembly_job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _draft_dir(self, assembly_job_id: str, draft_id: str) -> Path:
        return self._assembly_root(assembly_job_id) / draft_id

    def _path(self, assembly_job_id: str, draft_id: str) -> Path:
        return self._draft_dir(assembly_job_id, draft_id) / "draft.json"

    @staticmethod
    def _validate_payload(payload: dict | None) -> Optional[PublishingDraft]:
        if not payload:
            return None
        try:
            return PublishingDraft.model_validate(payload)
        except Exception:
            return None

    def _persist_local(self, draft: PublishingDraft) -> None:
        path = self._path(draft.assembly_job_id, draft.draft_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(draft.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _persist_cloud(self, draft: PublishingDraft) -> None:
        self._cloud.save(draft.draft_id, draft.model_dump(mode="json"))

    def save(self, draft: PublishingDraft) -> None:
        cloud_error: Exception | None = None
        try:
            self._persist_cloud(draft)
        except Exception as exc:
            cloud_error = exc
            logger.exception("Could not persist publishing draft %s to Firestore", draft.draft_id)
        self._persist_local(draft)
        with self._lock:
            self._cache[draft.draft_id] = draft.model_copy(deep=True)
        if cloud_error is not None and get_settings().app_env.strip().lower() in {"production", "prod"}:
            raise RuntimeError("Durable Firestore persistence failed for the publishing draft") from cloud_error

    def _load(self, path: Path) -> Optional[PublishingDraft]:
        try:
            return PublishingDraft.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Could not load publishing draft %s", path)
            return None

    def _load_cloud(self, draft_id: str) -> Optional[PublishingDraft]:
        try:
            return self._validate_payload(self._cloud.load(draft_id))
        except Exception:
            logger.exception("Could not read publishing draft %s from Firestore", draft_id)
            return None

    def _backfill_cloud(self, draft: PublishingDraft) -> None:
        try:
            self._persist_cloud(draft)
        except Exception:
            logger.exception("Could not backfill publishing draft %s to Firestore", draft.draft_id)

    def get(self, draft_id: str) -> PublishingDraft:
        with self._lock:
            cached = self._cache.get(draft_id)
            if cached:
                return cached.model_copy(deep=True)
        loaded = self._load_cloud(draft_id)
        if loaded is None:
            for path in tenant_scoped_root(self._root).glob(f"*/{draft_id}/draft.json"):
                loaded = self._load(path)
                if loaded:
                    self._backfill_cloud(loaded)
                    break
        if loaded is None:
            raise PublishingDraftNotFoundError(draft_id)
        with self._lock:
            self._cache[draft_id] = loaded
        return loaded.model_copy(deep=True)

    def list_for_audio_job(self, audio_job_id: str) -> list[PublishingDraft]:
        try:
            audio_job = audio_finishing_job_store.get(audio_job_id)
        except AudioFinishingJobNotFoundError as exc:
            raise PublishingDraftNotFoundError(audio_job_id) from exc
        items: Dict[str, PublishingDraft] = {}
        try:
            for _doc_id, payload in self._cloud.stream():
                loaded = self._validate_payload(payload)
                if loaded and loaded.audio_job_id == audio_job_id:
                    items[loaded.draft_id] = loaded
        except Exception:
            logger.exception("Could not list publishing drafts from Firestore; using local mirror")

        for path in self._assembly_root(audio_job.assembly_job_id).glob("*/draft.json"):
            loaded = self._load(path)
            if loaded and loaded.audio_job_id == audio_job_id:
                items[loaded.draft_id] = loaded
                if self._load_cloud(loaded.draft_id) is None:
                    self._backfill_cloud(loaded)
        with self._lock:
            for loaded in self._cache.values():
                if loaded.audio_job_id == audio_job_id:
                    items[loaded.draft_id] = loaded.model_copy(deep=True)
        return sorted(items.values(), key=lambda item: (item.version_number, item.updated_at), reverse=True)

    def latest_for_audio_job(self, audio_job_id: str) -> Optional[PublishingDraft]:
        items = self.list_for_audio_job(audio_job_id)
        return items[0] if items else None

    def next_version(self, audio_job_id: str) -> int:
        return max((item.version_number for item in self.list_for_audio_job(audio_job_id)), default=0) + 1


publishing_draft_store = PublishingDraftStore(get_settings().content_dna_checkpoint_dir)


def _normalize_hashtags(values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        token = re.sub(r"[^\w]", "", raw.strip().lstrip("#"), flags=re.UNICODE)
        if not token:
            continue
        tag = f"#{token}"
        if tag.lower() not in {item.lower() for item in out}:
            out.append(tag)
    return out


def _music_context(audio_job) -> str:
    result = audio_job.result
    if not result or not result.options.music_enabled:
        return "No background music is embedded."
    if result.selected_youtube_audio_library_track:
        track = result.selected_youtube_audio_library_track
        attribution = track.attribution_text.strip() if track.attribution_required and track.attribution_text else "No attribution marked required."
        return (
            f"Music source: YouTube Audio Library. Track: {track.title}. Artist: {track.artist or 'not provided'}. "
            f"Attribution required: {'yes' if track.attribution_required else 'no'}. Exact attribution when required: {attribution}"
        )
    if result.selected_trending_track:
        track = result.selected_trending_track
        return (
            f"Music source: rights-cleared provider. Track: {track.title}. Artist: {track.artist or 'not provided'}. "
            f"Provider: {track.provider or 'not provided'}. License reference: {track.license_reference or 'not provided'}."
        )
    return f"Music source: ReviveAI generated bed. Preset: {result.effective_music_preset.value}."


class PublishingAssistantService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _validate_source(self, audio_job_id: str):
        try:
            audio_job = audio_finishing_job_store.get(audio_job_id)
        except AudioFinishingJobNotFoundError as exc:
            raise PublishingAssistantError("Approved audio master not found.") from exc
        if not audio_job.result or audio_job.result.review_status != AudioFinishingReviewStatus.APPROVED:
            raise PublishingAssistantError("Approve the audio master before preparing publishing copy.")
        try:
            qc = delivery_qc_store.get(audio_job_id)
        except DeliveryQcReportNotFoundError as exc:
            raise PublishingAssistantError("Run Final Delivery QC before preparing publishing copy.") from exc
        if not qc_allows_manual_delivery(qc):
            raise PublishingAssistantError("Publishing copy is available only after Final Delivery QC returns READY.")
        package = delivery_package_store.latest_for_audio_job(audio_job_id)
        if package is None:
            raise PublishingAssistantError("Create the delivery package before preparing publishing copy.")
        try:
            production = production_brief_job_store.get(audio_job.production_brief_job_id)
        except ProductionBriefJobNotFoundError as exc:
            raise PublishingAssistantError("The approved production brief is no longer available.") from exc
        if not production.result:
            raise PublishingAssistantError("The approved production brief is incomplete.")
        return audio_job, qc, package, production

    def _client(self):
        if not self.settings.google_cloud_project:
            raise PublishingAssistantError(
                "Vertex AI is not configured. Set GOOGLE_CLOUD_PROJECT and authenticate with Application Default Credentials."
            )
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise PublishingAssistantError("google-genai is not installed. Run: pip install -r requirements.txt") from exc
        return (
            genai.Client(
                vertexai=True,
                project=self.settings.google_cloud_project,
                location=self.settings.google_cloud_location,
                http_options=types.HttpOptions(api_version="v1"),
            ),
            types,
        )

    def _prompt(self, audio_job, production, *, existing: Optional[PublishingDraftContent] = None, fields: Optional[list[str]] = None) -> str:
        result = production.result
        assert result is not None
        story = result.storyboard
        shot_lines = "\n".join(
            f"Shot {shot.shot_number}: {shot.visual_action}; on-screen text={shot.on_screen_text or 'none'}; narration={shot.voiceover_or_dialogue or 'none'}"
            for shot in story.shots
        )
        narration = " | ".join(cue.text for cue in (audio_job.result.voiceover_cues if audio_job.result else []) if cue.text) or "No synthesized narration cues."
        source_pub = result.publishing
        selective = ""
        if existing is not None and fields:
            selective = (
                "\nEXISTING CREATOR DRAFT\n"
                + json.dumps(existing.model_dump(mode="json"), ensure_ascii=False, indent=2)
                + "\nRegenerate only these fields conceptually: " + ", ".join(fields)
                + ". Return a complete JSON object, keeping all other fields semantically unchanged so the application can preserve them exactly."
            )
        return f"""
You are ReviveAI's publishing-copy assistant. Prepare platform-specific copy for a video that has passed ReviveAI AI review and deterministic delivery QC.

Rules:
- Never claim guaranteed reach, virality, ranking, revenue, or performance.
- Do not invent facts, brands, locations, people, products, or story events not present below.
- Keep the creator's approved character/story identity consistent.
- YouTube title: natural and specific, not clickbait, ideally <= 70 characters.
- YouTube description: concise, readable, and suitable for the finished video. Do not fabricate links.
- TikTok: short hook and caption appropriate to short-form viewing.
- Instagram: provide a concise caption, a fuller caption, and useful accessibility alt text.
- Hashtags must be relevant and limited; no spam-like stuffing.
- CTA must be optional/natural, never manipulative.
- Music attribution is handled deterministically by ReviveAI after generation. Do not rewrite legal attribution text.

APPROVED STORY
Working title: {result.creative_direction.working_title}
Creative promise: {result.creative_direction.one_sentence_promise}
Opening hook: {result.creative_direction.opening_hook}
Character: {result.creative_direction.production_identity.character_name}
Subject: {result.creative_direction.production_identity.species_or_subject}
Setting: {result.creative_direction.production_identity.setting_anchor}
Primary prop: {result.creative_direction.production_identity.primary_prop}
Duration: {audio_job.result.total_duration_seconds if audio_job.result else 0:.2f} seconds
Narration: {narration}
Storyboard:
{shot_lines}

EARLIER APPROVED PUBLISHING DIRECTION
Title: {source_pub.youtube_title}
Description: {source_pub.description}
Social caption: {source_pub.social_caption}
Hashtags: {', '.join(source_pub.hashtags)}
Alt text: {source_pub.accessibility_alt_text}

MUSIC / RIGHTS CONTEXT
{_music_context(audio_job)}
{selective}
""".strip()

    @classmethod
    def _sanitize_schema(cls, value):
        if isinstance(value, list):
            return [cls._sanitize_schema(item) for item in value]
        if not isinstance(value, dict):
            return value
        supported = {
            "$id", "$defs", "$ref", "$anchor", "type", "format", "title", "description",
            "enum", "items", "prefixItems", "minItems", "maxItems", "minimum", "maximum",
            "anyOf", "oneOf", "properties", "additionalProperties", "required", "propertyOrdering",
        }
        cleaned: Dict = {}
        if "exclusiveMinimum" in value and "minimum" not in value:
            cleaned["minimum"] = value["exclusiveMinimum"]
        if "exclusiveMaximum" in value and "maximum" not in value:
            cleaned["maximum"] = value["exclusiveMaximum"]
        for key, item in value.items():
            if key not in supported:
                continue
            if key in {"properties", "$defs"} and isinstance(item, dict):
                cleaned[key] = {name: cls._sanitize_schema(child) for name, child in item.items()}
            elif key == "items" and isinstance(item, dict):
                cleaned[key] = cls._sanitize_schema(item)
            elif key in {"prefixItems", "anyOf", "oneOf"} and isinstance(item, list):
                cleaned[key] = [cls._sanitize_schema(child) for child in item]
            elif key == "additionalProperties" and isinstance(item, dict):
                cleaned[key] = cls._sanitize_schema(item)
            else:
                cleaned[key] = item
        return cleaned

    async def _generate(self, prompt: str, *, production_id: str, channel_id: str) -> PublishingDraftContent:
        client, types = self._client()
        response_json_schema = self._sanitize_schema(PublishingDraftContent.model_json_schema())
        last_error: Optional[Exception] = None
        budget = FirestoreBudgetService()
        policy = channel_policy_store.get(channel_id)
        budget.ensure_production_budget(production_id, channel_id, policy.max_total_production_cost_usd)
        estimate = review_cost_reservation_usd()
        for attempt in range(max(1, self.settings.content_dna_retry_attempts)):
            operation_id = f"gemini_publishing_{uuid4().hex}"
            claim = budget.reserve(production_id, estimate, operation_id)
            if not claim.get("allowed"):
                raise PublishingAssistantError(
                    f"Publishing copy budget reservation denied: {claim.get('reason') or 'insufficient_budget'}"
                )
            try:
                response = await client.aio.models.generate_content(
                    model=self.settings.gemini_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction="Return polished, factual, editable publishing copy. Output only the requested structured JSON.",
                        temperature=0.42,
                        candidate_count=1,
                        response_mime_type="application/json",
                        response_json_schema=response_json_schema,
                        max_output_tokens=6000,
                    ),
                )
                # Provider has returned: reconcile before parsing, even if the
                # response is malformed; Gemini may bill for that attempt.
                budget.complete(operation_id, estimate)
                parsed = getattr(response, "parsed", None)
                if isinstance(parsed, PublishingDraftContent):
                    output = parsed
                elif parsed is not None:
                    output = PublishingDraftContent.model_validate(parsed)
                else:
                    text = getattr(response, "text", None)
                    if not text:
                        raise ValueError("Gemini returned an empty publishing response.")
                    output = PublishingDraftContent.model_validate_json(text)
                output.youtube.hashtags = _normalize_hashtags(output.youtube.hashtags)
                output.tiktok.hashtags = _normalize_hashtags(output.tiktok.hashtags)
                output.instagram.hashtags = _normalize_hashtags(output.instagram.hashtags)
                return output
            except Exception as exc:
                last_error = exc
                logger.warning("Publishing Assistant generation failed attempt %s: %s", attempt + 1, exc)
                # Uncertain provider failures keep their reservation; retry
                # only when the budget can reserve an independent attempt.
                if attempt + 1 < max(1, self.settings.content_dna_retry_attempts):
                    await asyncio.sleep(1.0 * (2**attempt))
        raise PublishingAssistantError(f"Gemini could not prepare publishing copy: {last_error}") from last_error

    def _new_draft(self, *, audio_job, qc, package, content: PublishingDraftContent, based_on: Optional[PublishingDraft] = None) -> PublishingDraft:
        now = datetime.now(timezone.utc)
        draft = PublishingDraft(
            draft_id=f"publishing_{uuid4().hex}",
            assembly_job_id=audio_job.assembly_job_id,
            audio_job_id=audio_job.job_id,
            audio_version=audio_job.version_number,
            source_package_id=package.package_id,
            source_package_version=package.package_version,
            qc_report_id=qc.report_id,
            version_number=publishing_draft_store.next_version(audio_job.job_id),
            based_on_draft_id=based_on.draft_id if based_on else None,
            generated_at=now,
            updated_at=now,
            model=self.settings.gemini_model,
            content=content,
        )
        publishing_draft_store.save(draft)
        return draft

    async def create(self, audio_job_id: str) -> PublishingDraft:
        audio_job, qc, package, production = self._validate_source(audio_job_id)
        content = await self._generate(self._prompt(audio_job, production), production_id=audio_job.production_brief_job_id, channel_id=audio_job.channel_id)
        return self._new_draft(audio_job=audio_job, qc=qc, package=package, content=content)

    def update(self, draft_id: str, content: PublishingDraftContent) -> PublishingDraft:
        base = publishing_draft_store.get(draft_id)
        audio_job, qc, package, _ = self._validate_source(base.audio_job_id)
        content.youtube.hashtags = _normalize_hashtags(content.youtube.hashtags)
        content.tiktok.hashtags = _normalize_hashtags(content.tiktok.hashtags)
        content.instagram.hashtags = _normalize_hashtags(content.instagram.hashtags)
        return self._new_draft(audio_job=audio_job, qc=qc, package=package, content=content, based_on=base)

    async def regenerate(self, draft_id: str, fields: list[str]) -> PublishingDraft:
        base = publishing_draft_store.get(draft_id)
        audio_job, qc, package, production = self._validate_source(base.audio_job_id)
        candidate = await self._generate(self._prompt(audio_job, production, existing=base.content, fields=fields), production_id=audio_job.production_brief_job_id, channel_id=audio_job.channel_id)
        merged = base.content.model_copy(deep=True)
        for path in fields:
            section, field = path.split(".", 1)
            source_section = getattr(candidate, section)
            target_section = getattr(merged, section)
            setattr(target_section, field, getattr(source_section, field))
        return self._new_draft(audio_job=audio_job, qc=qc, package=package, content=merged, based_on=base)

    def approve(
        self,
        draft_id: str,
        *,
        actor: str = "HUMAN",
        review_summary: Optional[str] = None,
    ) -> PublishingDraft:
        draft = publishing_draft_store.get(draft_id)
        self._validate_source(draft.audio_job_id)
        actor = (actor or "HUMAN").upper()
        if draft.status == PublishingDraftStatus.APPROVED and not (actor == "AI" and "[AI_REVIEW_APPROVED]" not in (draft.generation_note or "")):
            return draft
        draft.status = PublishingDraftStatus.APPROVED
        draft.approved_at = draft.approved_at or datetime.now(timezone.utc)
        draft.updated_at = datetime.now(timezone.utc)
        if actor == "AI" and "[AI_REVIEW_APPROVED]" not in (draft.generation_note or ""):
            suffix = f" [AI_REVIEW_APPROVED] AI reviewer PASS: {review_summary or 'Publishing copy matches the approved finished video.'}"
            draft.generation_note = f"{draft.generation_note}{suffix}".strip()
        publishing_draft_store.save(draft)
        return draft


publishing_assistant_service = PublishingAssistantService(get_settings())
