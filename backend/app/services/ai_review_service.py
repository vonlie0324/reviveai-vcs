from __future__ import annotations

import asyncio
import json
import logging
import uuid
import re
import subprocess
import tempfile
import urllib.request
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.services.audio_finishing_job_service import audio_finishing_job_store
from app.services.firestore_budget_service import FirestoreBudgetService
from app.services.channel_autonomy_policy import channel_policy_store
from app.services.ai_review_budget import review_cost_reservation_usd
from app.services.gemini_usage_meter import gemini_token_cost
from app.services.delivery_qc_service import delivery_qc_store
from app.services.final_assembly_job_service import final_assembly_job_store
from app.services.media_studio_job_service import media_studio_job_store
from app.services.production_brief_job_service import production_brief_job_store
from app.services.publishing_assistant_service import publishing_draft_store

logger = logging.getLogger(__name__)


class AiReviewError(RuntimeError):
    pass


class AiReviewDecision(str, Enum):
    PASS = "PASS"
    REGENERATE = "REGENERATE"


class AiCreativeReview(BaseModel):
    decision: AiReviewDecision
    summary: str
    issues: list[str] = Field(default_factory=list)
    corrective_instruction: Optional[str] = None
    shot_number: Optional[int] = None


class AiAudioMixSuggestion(BaseModel):
    voice_volume: Optional[float] = Field(default=None, ge=0.0, le=1.5)
    music_volume: Optional[float] = Field(default=None, ge=0.0, le=1.5)
    ambience_volume: Optional[float] = Field(default=None, ge=0.0, le=1.5)
    duck_music_during_voiceover: Optional[bool] = None


class AiAudioReview(BaseModel):
    decision: AiReviewDecision
    summary: str
    issues: list[str] = Field(default_factory=list)
    corrective_instruction: Optional[str] = None
    suggested_mix: Optional[AiAudioMixSuggestion] = None


class AiPublishingReview(BaseModel):
    decision: AiReviewDecision
    summary: str
    issues: list[str] = Field(default_factory=list)
    fields_to_regenerate: list[str] = Field(default_factory=list)


T = TypeVar("T", bound=BaseModel)


class AiReviewService:
    """Independent multimodal critic used by Autopilot.

    The generation services create media. This service judges already-created
    outputs against the locked production brief and deterministic QC evidence.
    It never publishes content and never records the final human approval.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def _client(self):
        if not self.settings.google_cloud_project:
            raise AiReviewError("Vertex AI is not configured. Set GOOGLE_CLOUD_PROJECT and authenticate with ADC.")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise AiReviewError("google-genai is not installed. Run pip install -r requirements.txt") from exc
        client = genai.Client(
            vertexai=True,
            project=self.settings.google_cloud_project,
            location=self.settings.google_cloud_location,
            http_options=types.HttpOptions(api_version="v1"),
        )
        return client, types

    @staticmethod
    def _sanitize_schema(value: Any) -> Any:
        unsupported = {"exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength", "default", "examples"}
        if isinstance(value, list):
            return [AiReviewService._sanitize_schema(item) for item in value]
        if not isinstance(value, dict):
            return value
        return {
            key: AiReviewService._sanitize_schema(child)
            for key, child in value.items()
            if key not in unsupported
        }

    async def _structured(self, model_cls: Type[T], contents: Any, *, production_id: str, channel_id: str, max_tokens: int = 2600) -> T:
        estimate = review_cost_reservation_usd()
        budget = FirestoreBudgetService()
        policy = channel_policy_store.get(channel_id)
        budget.ensure_production_budget(production_id, channel_id, policy.max_total_production_cost_usd)
        client, types = self._client()
        attempts = max(1, int(getattr(self.settings, "content_dna_retry_attempts", 2) or 2))
        last_error: Optional[Exception] = None
        schema = self._sanitize_schema(model_cls.model_json_schema())
        for attempt in range(attempts):
            # Each paid attempt receives its own durable reservation. Uncertain
            # provider outcomes remain RESERVED for operator reconciliation.
            operation_id = f"gemini_review_{uuid.uuid4().hex}"
            claim = budget.reserve(production_id, estimate, operation_id)
            if not claim.get("allowed"):
                raise AiReviewError(f"AI review budget reservation denied: {claim.get('reason') or 'insufficient_budget'}")
            try:
                response = await client.aio.models.generate_content(
                    model=self.settings.gemini_model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_json_schema=schema,
                        temperature=0.08,
                        candidate_count=1,
                        max_output_tokens=max_tokens,
                    ),
                )
                # Gemini response usage is not an invoice. Record the bounded
                # estimate; billing corrections must be reconciled separately.
                # Meter model usage when configured. Multimodal modality-specific
                # tariffs and missing usage remain on the conservative reserved
                # estimate; do not invent exact provider billing.
                try:
                    measured_cost, _usage = gemini_token_cost(response)
                except ValueError:
                    measured_cost = estimate
                budget.complete(operation_id, measured_cost)
                parsed = getattr(response, "parsed", None)
                if isinstance(parsed, model_cls):
                    return parsed
                if parsed is not None:
                    return model_cls.model_validate(parsed)
                text = getattr(response, "text", None)
                if not text:
                    raise ValueError("Gemini returned an empty AI-review response.")
                return model_cls.model_validate_json(text)
            except Exception as exc:
                last_error = exc
                logger.warning("AI review failed attempt %s/%s: %s", attempt + 1, attempts, exc)
                if attempt + 1 < attempts:
                    await asyncio.sleep(1.0 * (2**attempt))
        raise AiReviewError(f"Gemini could not complete AI review: {last_error}") from last_error

    @staticmethod
    def _ffmpeg_executable() -> str:
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as exc:
            raise AiReviewError("AI video review requires imageio-ffmpeg.") from exc

    @classmethod
    def _video_duration(cls, path: Path) -> float:
        ffmpeg = cls._ffmpeg_executable()
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(path.resolve())],
            capture_output=True,
            text=True,
        )
        text = (result.stderr or "") + "\n" + (result.stdout or "")
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
        if not match:
            return 0.0
        h, m, s = match.groups()
        return int(h) * 3600 + int(m) * 60 + float(s)

    @classmethod
    def _sample_video_frames(cls, path: Path, *, count: int = 4) -> list[bytes]:
        ffmpeg = cls._ffmpeg_executable()
        duration = max(0.2, cls._video_duration(path))
        ratios = [0.06, 0.34, 0.66, 0.92][:max(1, min(count, 4))]
        frames: list[bytes] = []
        with tempfile.TemporaryDirectory(prefix="reviveai-ai-review-") as tmp:
            tmpdir = Path(tmp)
            for index, ratio in enumerate(ratios, start=1):
                at = max(0.0, min(duration - 0.05, duration * ratio))
                out = tmpdir / f"frame-{index}.jpg"
                command = [
                    ffmpeg, "-y", "-ss", f"{at:.3f}", "-i", str(path.resolve()),
                    "-frames:v", "1", "-vf", "scale='min(768,iw)':-2",
                    "-q:v", "3", str(out),
                ]
                result = subprocess.run(command, capture_output=True, text=True)
                if result.returncode == 0 and out.exists() and out.stat().st_size > 0:
                    frames.append(out.read_bytes())
        if not frames:
            raise AiReviewError("ReviveAI could not sample frames from the rendered video for AI review.")
        return frames

    @staticmethod
    async def _download_reference_image(url: str) -> Optional[tuple[bytes, str]]:
        if not url or not url.startswith(("http://", "https://")):
            return None

        def fetch() -> Optional[tuple[bytes, str]]:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "ReviveAI/2.0 (+visual-identity-review)"},
            )
            with urllib.request.urlopen(request, timeout=12) as response:
                data = response.read(8 * 1024 * 1024 + 1)
                if len(data) > 8 * 1024 * 1024:
                    return None
                mime = (response.headers.get_content_type() or "image/jpeg").strip().lower()
                if not mime.startswith("image/") or not data:
                    return None
                return data, mime

        try:
            return await asyncio.to_thread(fetch)
        except Exception as exc:
            logger.info("Could not load archive identity reference %s: %s", url, exc)
            return None

    async def review_production_brief(self, production_job_id: str) -> AiCreativeReview:
        job = production_brief_job_store.get(production_job_id)
        if not job.result:
            raise AiReviewError("Production brief is unavailable for AI review.")
        result = job.result
        source = result.source_snapshot.recommendation
        creative = result.creative_direction
        storyboard = [shot.model_dump(mode="json") for shot in result.storyboard.shots]
        publishing = result.publishing.model_dump(mode="json")
        prompt = f"""
You are ReviveAI's independent production-plan critic. Another Gemini workflow generated this brief.
Review the plan before any media is created. Do not rewrite it yourself; decide PASS or REGENERATE.

IMMUTABLE RECOVERY DIRECTION
Title: {source.title}
Concept: {source.concept}
Hook: {source.hook}
Format: {source.format}
Recommended characters: {', '.join(source.recommended_characters) or 'not specified'}

GENERATED CREATIVE DIRECTION
{json.dumps(creative.model_dump(mode='json'), ensure_ascii=False, indent=2)}

STORYBOARD
{json.dumps(storyboard, ensure_ascii=False, indent=2)}

EARLY PUBLISHING DIRECTION
{json.dumps(publishing, ensure_ascii=False, indent=2)}

DETERMINISTIC CHECKS
Consistency: {result.consistency_report.status}
Direction fidelity: {result.direction_fidelity.status}

PASS only when the brief preserves the source concept, is internally coherent, visually executable, keeps character identity stable,
has realistic shot timing, and contains no obvious factual/story contradiction or unsupported claim.
REGENERATE when a material creative or textual defect remains despite the deterministic checks.
Do not reject for subjective wording preferences. Give one concise corrective_instruction when regeneration is needed.
""".strip()
        return await self._structured(AiCreativeReview, prompt, production_id=production_job_id, channel_id=job.channel_id)

    async def review_reference(self, media_job_id: str) -> AiCreativeReview:
        job = media_studio_job_store.get(media_job_id)
        if not job.result or not job.result.reference_asset:
            raise AiReviewError("The generated character reference is unavailable.")
        result = job.result
        identity = result.source_snapshot.production_identity
        reference = result.reference_asset
        reference_path, _ = media_studio_job_store.asset_path(job.job_id, reference.asset_id)
        evidence = result.source_snapshot.character_identity_evidence
        evidence_json = evidence.model_dump(mode="json") if evidence is not None else {}
        archive_images: list[tuple[str, bytes, str]] = []
        for match in result.source_snapshot.closest_archive_matches[:3]:
            url = getattr(match.video, "thumbnail_url", None)
            payload = await self._download_reference_image(url or "")
            if payload is not None:
                data, mime = payload
                archive_images.append((match.video.title, data, mime))
        prompt = f"""
You are ReviveAI's independent visual identity reviewer. You did NOT generate this image.
Decide whether the GENERATED CHARACTER REFERENCE is safe to use as the canonical identity for an automated video-production pipeline.

APPROVED IDENTITY CONTRACT
Character: {identity.character_name}
Subject: {identity.species_or_subject}
Subject count: {identity.subject_count}
Supporting subjects: {', '.join(identity.supporting_subjects) or 'none'}
Appearance: {identity.appearance}
Wardrobe: {identity.wardrobe}
Primary prop: {identity.primary_prop}
Setting anchor: {identity.setting_anchor}
Lighting: {identity.lighting_style}
Anatomy rule: {identity.anatomy_rule}
Identity source: {identity.identity_source}

SOURCE EVIDENCE METADATA
{json.dumps(evidence_json, ensure_ascii=False)[:6000]}

The optional ARCHIVE IDENTITY IMAGES below are historical channel thumbnails, not scene templates. When they clearly show the recurring character,
use them as higher-value evidence for face/fur/markings/proportions and stable wardrobe identity. Do not require the new reference to copy an old pose or background.

Review only material continuity problems: wrong character/species, wrong count, major appearance/wardrobe mismatch,
missing identity-defining prop when required, impossible anatomy, or an image too unclear to anchor later shots.
Do not reject for minor aesthetic preference. PASS means the pipeline may continue without human review.
REGENERATE means the image should be regenerated automatically. Provide one concise corrective_instruction that states the visible mismatch.
""".strip()
        client, types = self._client()
        contents = [types.Part.from_text(text=prompt)]
        for index, (title, data, mime) in enumerate(archive_images, start=1):
            contents.append(types.Part.from_text(text=f"ARCHIVE IDENTITY IMAGE {index}: {title}"))
            contents.append(types.Part.from_bytes(data=data, mime_type=mime))
        contents.extend([
            types.Part.from_text(text="GENERATED CHARACTER REFERENCE TO REVIEW:"),
            types.Part.from_bytes(data=reference_path.read_bytes(), mime_type=reference.mime_type),
        ])
        return await self._structured(AiCreativeReview, contents, production_id=job.production_brief_job_id, channel_id=job.channel_id)

    async def review_clip(self, media_job_id: str, shot_number: int) -> AiCreativeReview:
        job = media_studio_job_store.get(media_job_id)
        if not job.result:
            raise AiReviewError("Media Studio result is unavailable.")
        result = job.result
        clip = next((item for item in result.video_clips if item.shot_number == shot_number), None)
        keyframe = next((item for item in result.keyframes if item.shot_number == shot_number), None)
        shot = next((item for item in result.source_snapshot.storyboard.shots if item.shot_number == shot_number), None)
        if not clip or not keyframe or not shot:
            raise AiReviewError(f"Shot {shot_number} does not have the clip, keyframe, and storyboard required for AI review.")
        identity = result.source_snapshot.production_identity
        clip_path, _ = media_studio_job_store.asset_path(job.job_id, clip.asset_id)
        keyframe_path, _ = media_studio_job_store.asset_path(job.job_id, keyframe.asset_id)
        frames = self._sample_video_frames(clip_path, count=4)
        prompt = f"""
You are ReviveAI's independent animated-shot reviewer. Judge the generated Veo clip against the approved starting keyframe,
production identity, and storyboard. The attached stills are chronological samples from the generated clip.

LOCKED IDENTITY
Character: {identity.character_name}
Subject: {identity.species_or_subject}
Appearance: {identity.appearance}
Wardrobe: {identity.wardrobe}
Primary prop: {identity.primary_prop}
Setting: {identity.setting_anchor}
Anatomy: {identity.anatomy_rule}

SHOT {shot.shot_number}
Purpose: {shot.purpose}
Required action: {shot.visual_action}
Camera direction: {shot.camera_direction}
Planned duration: {shot.duration_seconds:g}s

PASS only when the clip preserves identity and the sampled progression is compatible with the requested action/camera.
REGENERATE for visible morphing, duplicated/missing limbs, identity/wardrobe/setting changes, new unwanted subjects,
missing required action, major camera mismatch, or frames that indicate a broken/unsafe animation.
Do not reject for tiny stylistic differences. If REGENERATE, preserve everything already correct and give one precise corrective_instruction.
""".strip()
        client, types = self._client()
        contents = [
            types.Part.from_text(text=prompt),
            types.Part.from_text(text="APPROVED STARTING KEYFRAME:"),
            types.Part.from_bytes(data=keyframe_path.read_bytes(), mime_type=keyframe.mime_type),
        ]
        for index, frame in enumerate(frames, start=1):
            contents.append(types.Part.from_text(text=f"CLIP SAMPLE FRAME {index} OF {len(frames)}:"))
            contents.append(types.Part.from_bytes(data=frame, mime_type="image/jpeg"))
        return await self._structured(AiCreativeReview, contents, production_id=job.production_brief_job_id, channel_id=job.channel_id)

    async def review_visual_master(self, assembly_job_id: str) -> AiCreativeReview:
        job = final_assembly_job_store.get(assembly_job_id)
        if not job.result:
            raise AiReviewError("Final visual master is unavailable.")
        result = job.result
        production = production_brief_job_store.get(job.production_brief_job_id)
        if not production.result:
            raise AiReviewError("Production brief is unavailable for visual-master review.")
        path, _ = final_assembly_job_store.asset_path(job.job_id, result.final_video.asset_id)
        frames = self._sample_video_frames(path, count=4)
        timeline = [
            {
                "shot": item.shot_number,
                "duration": item.output_duration_seconds,
                "text": item.on_screen_text,
                "voice": item.voiceover_or_dialogue,
            }
            for item in result.timeline
        ]
        prompt = f"""
You are ReviveAI's independent final visual-master reviewer. The individual source clips have already passed shot-level AI review.
Review only the ASSEMBLY: sequence coherence, obvious blank/black/corrupt frames, visibly broken transitions,
caption/on-screen-text legibility, and whether the sampled final master is consistent with the approved timeline.

Working title: {result.working_title}
Target duration: {result.total_duration_seconds:.2f}s
Captions burned in: {result.captions_burned_in}
Timeline: {json.dumps(timeline, ensure_ascii=False)}

PASS when the assembled picture is technically and visually coherent enough to proceed to audio.
REGENERATE only for an assembly/render problem. Do not reopen already-cleared creative decisions.
""".strip()
        client, types = self._client()
        contents = [types.Part.from_text(text=prompt)]
        for index, frame in enumerate(frames, start=1):
            contents.append(types.Part.from_text(text=f"FINAL MASTER SAMPLE {index} OF {len(frames)}:"))
            contents.append(types.Part.from_bytes(data=frame, mime_type="image/jpeg"))
        return await self._structured(AiCreativeReview, contents, production_id=job.production_brief_job_id, channel_id=job.channel_id)

    async def review_audio_master(self, audio_job_id: str) -> AiAudioReview:
        job = audio_finishing_job_store.get(audio_job_id)
        if not job.result:
            raise AiReviewError("Audio master is unavailable.")
        result = job.result
        if not result.audio_mix:
            raise AiReviewError("Rendered audio mix is unavailable.")
        audio_path, mime = audio_finishing_job_store.asset_path(job.job_id, result.audio_mix.asset_id)
        cue_text = [
            {
                "shot": cue.shot_number,
                "start": cue.start_seconds,
                "duration": cue.duration_seconds,
                "text": cue.text,
                "synthesized": cue.synthesized,
            }
            for cue in result.voiceover_cues
        ]
        prompt = f"""
You are ReviveAI's independent audio finishing reviewer. Listen to the attached rendered audio mix and compare it with the approved audio direction.

Audio direction: {result.audio_direction}
Duration: {result.total_duration_seconds:.2f}s
Voice: {result.effective_tts_voice or 'project default'}
Options: {json.dumps(job.options.model_dump(mode='json'), ensure_ascii=False)}
Voiceover cues: {json.dumps(cue_text, ensure_ascii=False)}

PASS when narration is intelligible, not audibly cut off, music/ambience support rather than overpower speech,
and the overall mood is compatible with the approved audio direction.
REGENERATE only for a material mix problem. If regeneration is needed, suggest conservative bus values from 0.0 to 1.5.
Do not request a different visual edit here.
""".strip()
        client, types = self._client()
        contents = [
            types.Part.from_text(text=prompt),
            types.Part.from_bytes(data=audio_path.read_bytes(), mime_type=mime),
        ]
        return await self._structured(AiAudioReview, contents, production_id=job.production_brief_job_id, channel_id=job.channel_id)

    async def review_delivery_warnings(self, audio_job_id: str) -> AiCreativeReview:
        audio_job = audio_finishing_job_store.get(audio_job_id)
        report = delivery_qc_store.get(audio_job_id)
        if report.overall_status.value == "BLOCKED":
            return AiCreativeReview(
                decision=AiReviewDecision.REGENERATE,
                summary="Deterministic delivery QC has a blocking failure.",
                issues=[item.summary for item in report.checks if item.status.value == "FAIL"],
                corrective_instruction="Correct the blocking delivery-QC failure before packaging.",
            )
        warnings = [
            {
                "key": item.key,
                "category": item.category,
                "label": item.label,
                "summary": item.summary,
                "detail": item.detail,
                "metric": item.metric,
                "expected": item.expected,
            }
            for item in report.checks
            if item.status.value == "WARN"
        ]
        if not warnings:
            return AiCreativeReview(decision=AiReviewDecision.PASS, summary="No delivery warnings require AI review.")
        prompt = f"""
You are ReviveAI's delivery-warning reviewer. Deterministic QC found no FAIL checks but returned these WARN checks:
{json.dumps(warnings, ensure_ascii=False, indent=2)}

Decide whether these warnings are acceptable for a short-form social video or whether the asset should be regenerated.
PASS only when the warnings are non-blocking and do not indicate likely audible/visible delivery defects.
REGENERATE when the warning reasonably indicates a user-visible defect.
""".strip()
        return await self._structured(AiCreativeReview, prompt, production_id=audio_job.production_brief_job_id, channel_id=audio_job.channel_id)

    async def review_publishing_draft(self, draft_id: str) -> AiPublishingReview:
        draft = publishing_draft_store.get(draft_id)
        audio_job = audio_finishing_job_store.get(draft.audio_job_id)
        production = production_brief_job_store.get(audio_job.production_brief_job_id)
        if not production.result:
            raise AiReviewError("Production brief is unavailable for publishing review.")
        result = production.result
        allowed = {
            "youtube.title", "youtube.description", "youtube.hashtags", "youtube.tags", "youtube.thumbnail_text_suggestions",
            "tiktok.hook", "tiktok.caption", "tiktok.hashtags", "tiktok.cta",
            "instagram.caption_short", "instagram.caption_long", "instagram.hashtags", "instagram.alt_text", "instagram.cta",
        }
        prompt = f"""
You are ReviveAI's independent publishing-copy reviewer. Another Gemini pass generated this draft.
Review it against the approved story and final production facts.

APPROVED STORY
Working title: {result.creative_direction.working_title}
Promise: {result.creative_direction.one_sentence_promise}
Opening hook: {result.creative_direction.opening_hook}
Character: {result.creative_direction.production_identity.character_name}
Setting: {result.creative_direction.production_identity.setting_anchor}
Storyboard: {json.dumps([s.model_dump(mode='json') for s in result.storyboard.shots], ensure_ascii=False)}

DRAFT
{json.dumps(draft.content.model_dump(mode='json'), ensure_ascii=False, indent=2)}

PASS only when copy is factual, consistent with the video, readable, non-spammy, and does not promise guaranteed reach/performance.
REGENERATE if any field invents facts, conflicts with the video, is misleading/clickbait, omits essential accessibility context,
or is clearly weak enough to harm usability. fields_to_regenerate must contain only exact field paths from this allowlist:
{', '.join(sorted(allowed))}
Return a small targeted field list instead of regenerating everything.
""".strip()
        review = await self._structured(AiPublishingReview, prompt, production_id=audio_job.production_brief_job_id, channel_id=audio_job.channel_id)
        review.fields_to_regenerate = [field for field in review.fields_to_regenerate if field in allowed]
        if review.decision == AiReviewDecision.REGENERATE and not review.fields_to_regenerate:
            review.fields_to_regenerate = ["youtube.title", "youtube.description", "tiktok.caption", "instagram.caption_long"]
        return review


def review_to_detail(review: BaseModel) -> dict[str, Any]:
    return review.model_dump(mode="json")
