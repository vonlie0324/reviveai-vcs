from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from uuid import uuid4

import httpx

from app.core.config import Settings
from app.core.tenant import tenant_namespace
from app.models.media_studio import (
    AiKeyframeFidelity,
    FidelityCheckStatus,
    KeyframeFidelityCheck,
    KeyframeFidelityReport,
    KeyframeFidelityStatus,
    MediaAsset,
    MediaAssetKind,
    MediaAssetReviewStatus,
    MediaSourceSnapshot,
)
from app.models.production_brief import StoryboardShot

from app.services.channel_autonomy_policy import channel_policy_store
from app.services.budget_service import BudgetService
from app.services.firestore_budget_service import FirestoreBudgetService
from app.services.veo_operation_capture_service import VeoOperationCaptureService
from app.services.veo_heartbeat_service import VeoHeartbeatService

logger = logging.getLogger(__name__)


class MediaGenerationError(RuntimeError):
    pass


class MediaGenerationService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.budget_service = BudgetService()
        self.firestore_budget_service = FirestoreBudgetService()
        self.veo_capture_service = VeoOperationCaptureService()
        self.veo_heartbeat_service = VeoHeartbeatService()






    def capture_veo_failure(
        self,
        production_id,
        operation_id,
        provider_response,
    ):
        """
        Persist failed Veo lifecycle state and provider metadata.
        """
        return self.veo_capture_service.capture_failed(
            production_id,
            operation_id,
            provider_response,
        )

    def capture_veo_completion(
        self,
        production_id,
        operation_id,
        provider_response,
    ):
        """
        Capture Veo response and return normalized usage data.
        """
        # CaptureService exposes capture_completed(), not capture().  Persist the
        # terminal response before reconciling the durable budget reservation.
        return self.veo_capture_service.capture_completed(
            production_id,
            operation_id,
            provider_response,
        )

    def extract_veo_usage_cost(self, provider_response: Any) -> Optional[float]:
        """
        Extract actual Veo usage cost from provider response.

        Supports common usage metadata formats.
        """

        if not provider_response:
            return None

        if isinstance(provider_response, dict):
            usage = provider_response.get("usage", {})

            return (
                usage.get("cost")
                or usage.get("total_cost")
                or usage.get("estimated_cost")
            )

        usage = getattr(provider_response, "usage", None)

        if usage:
            return (
                getattr(usage, "cost", None)
                or getattr(usage, "total_cost", None)
            )

        return None

    def extract_provider_cost(self, provider_response: Any) -> Optional[float]:
        """
        Extract actual provider usage cost when available.

        Keeps provider-specific parsing isolated.
        """
        if not provider_response:
            return None

        usage = getattr(provider_response, "usage", None)

        if isinstance(usage, dict):
            return usage.get("cost")

        if isinstance(provider_response, dict):
            return (
                provider_response.get("usage", {})
                .get("cost")
            )

        return None

    def check_generation_budget(
        self,
        estimated_cost: float,
        remaining_budget: float,
    ):
        """
        Budget validation before expensive provider calls.

        Budget exhaustion is returned as a workflow state,
        not raised as a generation exception.
        """
        return self.budget_service.check(
            estimated_cost,
            remaining_budget,
        )

    def _client(self):
        try:
            from google import genai
        except Exception as exc:
            raise MediaGenerationError("google-genai is not installed.") from exc
        return genai.Client(
            vertexai=True,
            project=self.settings.google_cloud_project,
            location=self.settings.google_cloud_location,
        )

    @staticmethod
    def _extension_for_mime(mime_type: str) -> str:
        return ".jpg" if mime_type in {"image/jpeg", "image/jpg"} else ".png"

    async def _download_identity_images(self, source: MediaSourceSnapshot, limit: int = 3):
        evidence = source.character_identity_evidence
        if evidence is None or not evidence.source_videos:
            return []

        timeout_seconds = float(getattr(self.settings, "content_dna_thumbnail_timeout_seconds", 10) or 10)
        candidates = evidence.source_videos[: max(3, limit * 2)]
        outputs = []
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
            for video in candidates:
                if len(outputs) >= max(1, limit):
                    break
                if not video.thumbnail_url:
                    continue
                try:
                    response = await client.get(video.thumbnail_url)
                    response.raise_for_status()
                except Exception as exc:
                    logger.warning(
                        "Historical identity thumbnail unavailable video_id=%s: %s",
                        video.video_id,
                        exc,
                    )
                    continue
                if not response.content:
                    continue
                mime = response.headers.get("content-type", "image/jpeg").split(";", 1)[0].strip().lower()
                if not mime.startswith("image/"):
                    mime = "image/jpeg"
                outputs.append((video, response.content, mime))
        return outputs

    @staticmethod
    def _extract_image(response) -> tuple[bytes, str]:
        parts = getattr(response, "parts", None)
        if not parts:
            candidates = getattr(response, "candidates", None) or []
            if candidates:
                parts = getattr(getattr(candidates[0], "content", None), "parts", None)
        for part in parts or []:
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                return inline.data, getattr(inline, "mime_type", None) or "image/png"
        raise MediaGenerationError("The image model returned no image output.")

    @staticmethod
    def _gemini_json_schema(model_cls) -> Dict[str, Any]:
        schema = model_cls.model_json_schema()
        unsupported = {"exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength", "default", "examples"}

        def clean(value: Any) -> Any:
            if isinstance(value, dict):
                output: Dict[str, Any] = {}
                for key, child in value.items():
                    if key in unsupported:
                        continue
                    output[key] = clean(child)
                return output
            if isinstance(value, list):
                return [clean(v) for v in value]
            return value

        return clean(schema)

    async def _generate_image(self, *, contents, prompt: str, production_id: str, channel_id: str) -> tuple[bytes, str]:
        """Budget-gate every image attempt before provider submission.

        A provider request with an uncertain outcome keeps its reservation held;
        do not retry blindly after a timeout or connection loss.
        """
        try:
            from google.genai import types
        except Exception as exc:
            raise MediaGenerationError("google-genai image types are unavailable.") from exc

        # Do not send paid work to Google's retired image model. Fail before reserving.
        if self.settings.image_generation_model == "gemini-2.5-flash-image":
            raise MediaGenerationError(
                "gemini-2.5-flash-image retired on 2026-10-02. "
                "Configure IMAGE_GENERATION_MODEL=gemini-3.1-flash-image "
                "and calibrate REVIVEAI_IMAGE_GENERATION_RESERVATION_USD."
            )
        raw_rate = os.getenv("REVIVEAI_IMAGE_GENERATION_RESERVATION_USD", "").strip()
        try:
            reserve_usd = float(raw_rate)
        except ValueError as exc:
            raise MediaGenerationError("Invalid image generation reservation rate") from exc
        if not math.isfinite(reserve_usd) or reserve_usd <= 0:
            raise MediaGenerationError("Configure REVIVEAI_IMAGE_GENERATION_RESERVATION_USD before generating images")
        if not production_id or not channel_id:
            raise MediaGenerationError("Image generation requires canonical production and channel identity")
        budget = self.firestore_budget_service
        policy = channel_policy_store.get(channel_id)
        budget.ensure_production_budget(production_id, channel_id, policy.max_total_production_cost_usd)
        client = self._client()
        # Provider errors can have an uncertain billed outcome. Never submit a
        # second request automatically; retain the reservation for reconciliation.
        operation_id = f"gemini_image_{uuid4().hex}"
        claim = budget.reserve(production_id, reserve_usd, operation_id)
        if not claim.get("allowed"):
            raise MediaGenerationError(f"Image generation budget reservation denied: {claim.get('reason') or 'insufficient_budget'}")
        try:
            response = await client.aio.models.generate_content(
                model=self.settings.image_generation_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(aspect_ratio=self.settings.media_image_aspect_ratio),
                ),
            )
            # The request succeeded, so reconcile even if the response has no
            # usable image; Gemini image pricing is configured per attempt.
            budget.complete(operation_id, reserve_usd)
            return self._extract_image(response)
        except Exception as exc:
            logger.warning("Image generation failed operation=%s: %s", operation_id, exc)
            raise MediaGenerationError(
                f"Image generation could not complete; budget operation {operation_id} requires reconciliation before retry"
            ) from exc

    async def _structured_fidelity_call(self, *, contents, production_id: str, channel_id: str) -> AiKeyframeFidelity:
        try:
            from google.genai import types
        except Exception as exc:
            raise MediaGenerationError("google-genai fidelity review types are unavailable.") from exc

        from app.services.ai_review_budget import review_cost_reservation_usd

        if not production_id or not channel_id:
            raise MediaGenerationError("Fidelity review requires production and channel identity")
        try:
            reserve_usd = review_cost_reservation_usd()
            self.firestore_budget_service.ensure_production_budget(
                production_id, channel_id,
                channel_policy_store.get(channel_id).max_total_production_cost_usd,
            )
        except (ValueError, RuntimeError) as exc:
            raise MediaGenerationError(f"Fidelity review budget unavailable: {exc}") from exc
        client = self._client()
        attempts = self.settings.media_generation_retry_attempts
        last_error: Optional[Exception] = None
        schema = self._gemini_json_schema(AiKeyframeFidelity)
        for attempt in range(1, attempts + 1):
            operation_id = f"gemini_fidelity_{uuid4().hex}"
            reservation = self.firestore_budget_service.reserve(production_id, reserve_usd, operation_id)
            if not reservation.get("allowed"):
                raise MediaGenerationError(
                    f"Fidelity review budget denied: {reservation.get('reason') or 'insufficient_budget'}"
                )
            try:
                response = await client.aio.models.generate_content(
                    model=self.settings.gemini_model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_json_schema=schema,
                        temperature=0.1,
                        max_output_tokens=2200,
                    ),
                )
            except Exception as exc:
                # Provider execution may have been billed. The reservation stays
                # held for reconciliation; do not auto-submit another billed call.
                raise MediaGenerationError(
                    f"Fidelity review provider outcome uncertain; operation {operation_id} requires reconciliation"
                ) from exc
            # The provider returned a response, even if parsing later fails.
            self.firestore_budget_service.complete(operation_id, reserve_usd)
            text = getattr(response, "text", None)
            if not text:
                raise MediaGenerationError("Gemini returned an empty fidelity review.")
            try:
                return AiKeyframeFidelity.model_validate_json(text)
            except Exception as exc:
                raise MediaGenerationError("Gemini returned an invalid fidelity review.") from exc

    def reference_prompt(self, source: MediaSourceSnapshot) -> str:
        i = source.production_identity
        supporting = ", ".join(i.supporting_subjects) or "none"
        evidence = source.character_identity_evidence
        if evidence and evidence.source_videos:
            identity_rule = f"""
HISTORICAL CHARACTER IDENTITY — HIGHEST PRIORITY:
The attached historical channel images show the recurring character {evidence.character_name}.
Treat those images as the authoritative source for stable physical identity: fur/coat color and pattern, face shape, muzzle, eyes, ears, body proportions, coat length/texture, and other recognizable traits.
If the text below conflicts with a clearly visible stable physical trait in the attached historical images, preserve the historical visual trait. Do not blend the character with a different breed, animal, or character.
The text remains authoritative for production-specific styling such as wardrobe, props, setting, pose, and lighting.
""".strip()
        else:
            identity_rule = (
                "No historical character images were resolved for this production. "
                "Use the Production Identity text conservatively and do not invent extra defining traits."
            )
        return f"""
Create a canonical vertical character reference image for a short-form video production.

{identity_rule}

PRODUCTION IDENTITY:
Character name: {i.character_name}
Subject label: {i.species_or_subject}
Subject count: {i.subject_count}
Supporting subjects: {supporting}
Appearance notes: {i.appearance}
Wardrobe: {i.wardrobe}
Personality: {', '.join(i.personality)}
Primary prop: {i.primary_prop}
Setting anchor: {i.setting_anchor}
Lighting: {i.lighting_style}
Anatomy rule: {i.anatomy_rule}

REFERENCE IMAGE GOAL:
Show the main character clearly from head to paws, readable wardrobe, identifiable facial features, and the primary prop nearby without blocking the character. Preserve plausible animal anatomy. No text overlays, no logos, no watermark, no collage, no split panels. Use a clean production-reference composition suitable as the canonical visual identity for later shot generation. Vertical 9:16 framing.
""".strip()

    async def generate_reference(self, source: MediaSourceSnapshot, assets_dir: Path, generation_attempt: int = 1, *, channel_id: str) -> MediaAsset:
        try:
            from google.genai import types
        except Exception as exc:
            raise MediaGenerationError("google-genai image types are unavailable.") from exc

        prompt = self.reference_prompt(source)
        identity_images = await self._download_identity_images(source, limit=3)
        contents = [types.Part.from_text(text=prompt)]
        for index, (video, image_bytes, image_mime) in enumerate(identity_images, start=1):
            contents.append(
                types.Part.from_text(
                    text=(
                        f"HISTORICAL CHARACTER APPEARANCE {index}: {video.title}. "
                        "Use this image only for the recurring character's stable physical identity."
                    )
                )
            )
            contents.append(types.Part.from_bytes(data=image_bytes, mime_type=image_mime))

        data, mime = await self._generate_image(contents=contents, prompt=prompt, production_id=source.production_brief_job_id, channel_id=channel_id)
        asset_id = f"ref_{uuid4().hex}"
        filename = f"{asset_id}{self._extension_for_mime(mime)}"
        assets_dir.mkdir(parents=True, exist_ok=True)
        (assets_dir / filename).write_bytes(data)
        return MediaAsset(
            asset_id=asset_id,
            kind=MediaAssetKind.CHARACTER_REFERENCE,
            created_at=datetime.now(timezone.utc),
            model=self.settings.image_generation_model,
            mime_type=mime,
            filename=filename,
            asset_url="",
            prompt=prompt,
            review_status=MediaAssetReviewStatus.NEEDS_REVIEW,
            generation_attempt=generation_attempt,
            identity_grounding_video_ids=[video.video_id for video, _, _ in identity_images],
            identity_grounding_images_supplied=len(identity_images),
        )

    def keyframe_prompt(self, source: MediaSourceSnapshot, shot: StoryboardShot, corrective_instruction: Optional[str] = None, creator_note: Optional[str] = None) -> str:
        i = source.production_identity
        correction = ""
        if corrective_instruction or creator_note:
            correction = f"""

TARGETED CORRECTION — PRESERVE EVERYTHING ALREADY CORRECT:
{corrective_instruction or 'Keep the approved visual identity and storyboard intent.'}
{('Creator note: ' + creator_note) if creator_note else ''}
Change only what is necessary to satisfy this shot-specific correction. Treat this as a NEW COMPOSITION, not a cosmetic retouch of the previous attempt: re-stage the subject, camera, and interacting objects where needed to meet the storyboard action and framing. Preserve the approved character identity, wardrobe, environment, and palette. Preserve required props but correct their placement or count when the shot requires it.
For any contact-critical action, lock the final still image at the INSTANT OF CONTACT: the specified body part and object have no visible air gap. Position or slightly tilt the touched object to make contact evident. Do not substitute gaze, a pointing gesture, or proximity for contact; do not invent extra objects. Keep other already-passing attributes unchanged.
"""
        return f"""
Generate THIS shot, not a copy of the reference composition. The attached approved character reference image locks physical identity ONLY (face, coat, proportions); it does NOT prescribe camera framing, action, center placement, gaze, or supporting subjects. The storyboard shot instructions below are binding for composition and action.

SHOT-LOCAL CONTRACT — MUST BE VISIBLE IN THIS STILL FRAME:
1. PRIMARY ACTION: {shot.visual_action}
2. SUBJECT PRIORITY AND PLACEMENT: Choose the framing that shows the required actors performing the action; do not automatically center the main character when the shot calls for guests or props.
3. CAMERA CONTRACT: {shot.camera_direction}
4. SHOT PURPOSE: {shot.purpose}
5. SHOT UNIQUENESS: Show this shot's intended viewpoint. Do not reproduce a prior heroic portrait just to preserve identity.
6. PHYSICAL INTERACTION: If the action calls for touching, nudging, holding, pressing, pushing, or another contact action, stage the still at the moment of visible contact between the specified subject part and object. Merely looking toward, pointing toward, reaching for, or hovering near the object is NOT evidence of the required contact.
7. OBJECT COUNT: Follow any explicit counts in the shot action, purpose, or original generation prompt. Show exactly the requested number of shot-specific props; do not invent extras. This overrides generic continuity language that would add unrelated objects.
8. FRAME PRIORITY: The action and the object being acted on must be large enough to assess. If a close-up is requested, crop away unneeded full-body views, floor space, luggage, and other background details. Match the stated camera direction rather than defaulting to a character portrait.
9. IMAGE LIMITATION: Depict the necessary pose/contact state in the keyframe; temporal motion must also be fulfilled and reviewed in the generated video.
10. CONTACT PROOF: When the storyboard requires a nudge, touch, push, press or pat, freeze the image at direct visible body-part-to-object contact, with NO AIR GAP at the contact point. The object may lean or tilt naturally at the impact point as visual evidence, without changing its identity. A hand, paw, snout or tool simply near the object fails this contract.

CONTINUITY LOCK:
Character: {i.character_name}
Subject: {i.species_or_subject}
Subject count: {i.subject_count}
Supporting subjects: {', '.join(i.supporting_subjects) or 'none'}
Appearance: {i.appearance}
Wardrobe: {i.wardrobe}
Primary prop: {i.primary_prop}
Setting anchor: {i.setting_anchor}
Lighting: {i.lighting_style}
Anatomy rule: {i.anatomy_rule}

SHOT {shot.shot_number}:
Purpose: {shot.purpose}
Visual action: {shot.visual_action}
Camera: {shot.camera_direction}
Original generation prompt: {shot.generation_prompt}
{correction}
Create one clean cinematic vertical 9:16 storyboard keyframe. Keep the approved character's face, fur, proportions, wardrobe, and palette consistent with the attached reference. Preserve the setting and prop continuity. Match the requested action, camera framing, and camera angle as closely as possible. No captions or text overlays in the generated image. Do not redesign the character.
FINAL FRAME VALIDATION: Show all required shot-specific objects in the exact stated count. If physical contact is part of the action, the contact point MUST be visible in this single image with zero visible separation; pose the subject and object accordingly, even if this requires a new composition. Do not leave the intended touch or nudge as future motion only.
""".strip()

    async def generate_keyframe(
        self,
        source: MediaSourceSnapshot,
        reference_asset: MediaAsset,
        reference_bytes: bytes,
        shot: StoryboardShot,
        assets_dir: Path,
        generation_attempt: int = 1,
        corrective_instruction: Optional[str] = None,
        creator_note: Optional[str] = None,
        channel_id: str = "",
    ) -> MediaAsset:
        try:
            from google.genai import types
        except Exception as exc:
            raise MediaGenerationError("google-genai image types are unavailable.") from exc
        prompt = self.keyframe_prompt(source, shot, corrective_instruction=corrective_instruction, creator_note=creator_note)
        contents = [
            types.Part.from_text(text=prompt),
            types.Part.from_bytes(data=reference_bytes, mime_type=reference_asset.mime_type),
        ]
        data, mime = await self._generate_image(contents=contents, prompt=prompt, production_id=source.production_brief_job_id, channel_id=channel_id)
        asset_id = f"kf_{shot.shot_number}_{uuid4().hex}"
        filename = f"{asset_id}{self._extension_for_mime(mime)}"
        (assets_dir / filename).write_bytes(data)
        return MediaAsset(
            asset_id=asset_id,
            kind=MediaAssetKind.KEYFRAME,
            shot_number=shot.shot_number,
            created_at=datetime.now(timezone.utc),
            model=self.settings.image_generation_model,
            mime_type=mime,
            filename=filename,
            asset_url="",
            prompt=prompt,
            review_status=MediaAssetReviewStatus.NEEDS_REVIEW,
            source_reference_asset_id=reference_asset.asset_id,
            generation_attempt=generation_attempt,
        )

    async def review_keyframe_fidelity(
        self,
        *,
        source: MediaSourceSnapshot,
        reference_asset: MediaAsset,
        reference_bytes: bytes,
        keyframe_asset: MediaAsset,
        keyframe_bytes: bytes,
        shot: StoryboardShot,
        channel_id: str,
    ) -> KeyframeFidelityReport:
        try:
            from google.genai import types
        except Exception as exc:
            raise MediaGenerationError("google-genai fidelity review types are unavailable.") from exc

        identity = source.production_identity
        prompt = f"""
You are ReviveAI's storyboard fidelity reviewer. Compare the generated KEYFRAME with both the approved REFERENCE IMAGE and the approved STORYBOARD SHOT.

Do not judge whether the image is attractive. Judge only whether it preserves the approved visual identity and actually depicts the planned shot.

APPROVED PRODUCTION IDENTITY
Character: {identity.character_name}
Subject: {identity.species_or_subject}
Appearance: {identity.appearance}
Wardrobe: {identity.wardrobe}
Setting: {identity.setting_anchor}
Primary prop: {identity.primary_prop}
Supporting subjects: {', '.join(identity.supporting_subjects) or 'none'}
Anatomy rule: {identity.anatomy_rule}

APPROVED STORYBOARD SHOT {shot.shot_number}
Purpose: {shot.purpose}
Required action: {shot.visual_action}
Camera direction: {shot.camera_direction}

Review these eight dimensions independently:
1. character_identity — same character/breed/fur/face/proportions as reference
2. wardrobe — approved clothing/accessories preserved
3. setting — planned environment preserved
4. primary_prop — required prop is present and recognizable when the shot calls for it; any explicit count of required shot-specific props must match exactly (no extra or missing objects)
5. supporting_subjects — required supporting subjects are present when relevant; do not fail if the shot legitimately crops them out
6. required_action — the visible action matches the storyboard. For physical-contact verbs, require visible contact at the expected body part and object; looking, hovering, pointing, or reaching alone does not pass. For explicit prop counts, a wrong count is a meaningful failure even if the prop is recognizable.
7. camera_framing — close-up/medium/wide/over-the-shoulder framing matches the storyboard intent
8. camera_angle — low/high/eye-level/over-the-shoulder/perspective matches the storyboard intent

Use PASS unless there is a meaningful visible mismatch. For camera framing or angle, mark REVIEW when the generated composition is materially different enough to weaken the storyboard purpose.
If any dimension is REVIEW, provide concise issues and ONE concrete corrective_instruction that describes the intended visible pose/contact point, exactly specified object count (if any), and framing without changing the approved character identity or style. Do not substitute movement that can only happen in video for a still-frame contact pose. Never claim that future movement is visibly present in a still image.
Do not output numeric scores or probabilities.
""".strip()
        contents = [
            types.Part.from_text(text=prompt),
            types.Part.from_text(text="APPROVED REFERENCE IMAGE:"),
            types.Part.from_bytes(data=reference_bytes, mime_type=reference_asset.mime_type),
            types.Part.from_text(text="GENERATED KEYFRAME TO REVIEW:"),
            types.Part.from_bytes(data=keyframe_bytes, mime_type=keyframe_asset.mime_type),
        ]
        ai = await self._structured_fidelity_call(contents=contents, production_id=source.production_brief_job_id, channel_id=channel_id)
        mapping = [
            ("character_identity", "Character identity", ai.character_identity),
            ("wardrobe", "Wardrobe", ai.wardrobe),
            ("setting", "Setting", ai.setting),
            ("primary_prop", "Primary prop", ai.primary_prop),
            ("supporting_subjects", "Supporting subjects", ai.supporting_subjects),
            ("required_action", "Required action", ai.required_action),
            ("camera_framing", "Camera framing", ai.camera_framing),
            ("camera_angle", "Camera angle", ai.camera_angle),
        ]
        issues = [item.strip() for item in ai.issues if item.strip()]
        checks = [
            KeyframeFidelityCheck(
                key=key,
                label=label,
                status=status,
                detail=("Matches approved source." if status == FidelityCheckStatus.PASS else "Review against the approved storyboard."),
            )
            for key, label, status in mapping
        ]
        requires_review = any(status == FidelityCheckStatus.REVIEW for _, _, status in mapping)
        return KeyframeFidelityReport(
            shot_number=shot.shot_number,
            status=KeyframeFidelityStatus.REVIEW_REQUIRED if requires_review else KeyframeFidelityStatus.PASS,
            checks=checks,
            issues=issues,
            corrective_instruction=ai.corrective_instruction.strip() if ai.corrective_instruction else None,
            evaluated_at=datetime.now(timezone.utc),
            model=self.settings.gemini_model,
        )

    @staticmethod
    def supported_video_duration(seconds: float) -> int:
        """Map storyboard timing to Veo's supported 4/6/8 second clip lengths."""
        if seconds <= 4:
            return 4
        if seconds <= 6:
            return 6
        return 8

    def video_prompt(self, source: MediaSourceSnapshot, shot: StoryboardShot, corrective_instruction: Optional[str] = None) -> str:
        i = source.production_identity
        return f"""
Animate the attached approved storyboard keyframe into ONE continuous vertical short-form video shot.

LOCKED VISUAL IDENTITY — PRESERVE EXACTLY:
Character: {i.character_name}
Subject: {i.species_or_subject}
Subject count: {i.subject_count}
Supporting subjects: {', '.join(i.supporting_subjects) or 'none'}
Appearance: {i.appearance}
Wardrobe: {i.wardrobe}
Primary prop: {i.primary_prop}
Setting: {i.setting_anchor}
Lighting: {i.lighting_style}
Anatomy: {i.anatomy_rule}

SHOT {shot.shot_number} MOTION PLAN:
Purpose: {shot.purpose}
Action: {shot.visual_action}
Camera direction: {shot.camera_direction}
Planned storyboard duration: {shot.duration_seconds:g} seconds

{("REGENERATION CORRECTION — MANDATORY: " + corrective_instruction) if corrective_instruction else ""}

MOTION RULES:
- Start from the attached approved keyframe; do not redesign the character or environment.
- Preserve face, fur, proportions, wardrobe, prop colors, cabin/set layout, and supporting subjects.
- Animate only the motion needed for this shot's action and camera direction.
- Keep movement controlled and physically plausible; avoid morphing, duplicated limbs, sudden costume changes, or new characters.
- No cuts, no scene changes, no text overlays, no logos, and no added captions.
- Keep the final frame visually compatible with the same Production Identity for later editing.
""".strip()

    @staticmethod
    def _download_gcs_video(gcs_uri: str, destination: Path) -> None:
        if not gcs_uri.startswith("gs://"):
            raise MediaGenerationError(f"Unsupported generated video URI: {gcs_uri}")
        try:
            from google.cloud import storage
        except Exception as exc:
            raise MediaGenerationError(
                "google-cloud-storage is required to download Veo outputs. Run pip install -r requirements.txt."
            ) from exc
        path = gcs_uri[5:]
        bucket_name, _, blob_name = path.partition("/")
        if not bucket_name or not blob_name:
            raise MediaGenerationError(f"Invalid Veo GCS URI: {gcs_uri}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        storage.Client().bucket(bucket_name).blob(blob_name).download_to_filename(str(destination))

    def _generate_video_sync(
        self,
        *,
        keyframe_path: Path,
        prompt: str,
        output_path: Path,
        output_gcs_uri: str,
        duration_seconds: int,
        on_operation_started: Optional[Callable[[str], None]] = None,
        production_id: Optional[str] = None,
        operation_id: Optional[str] = None,
    ) -> tuple[Optional[str], str]:
        import time
        try:
            from google import genai
            from google.genai import types
        except Exception as exc:
            raise MediaGenerationError("google-genai Veo types are unavailable.") from exc

        client = genai.Client(
            vertexai=True,
            project=self.settings.google_cloud_project,
            location=self.settings.video_generation_location,
        )
        image = types.Image.from_file(location=str(keyframe_path))
        if production_id and operation_id:
            self.veo_capture_service.persist_state(
                operation_id,
                production_id,
                "STARTED",
                {
                    "model": self.settings.video_generation_model,
                },
            )

        # Always initialize the name: the provider may return a completed
        # operation before an on_operation_started callback is supplied.
        operation_name = ""
        operation = client.models.generate_videos(
            model=self.settings.video_generation_model,
            source=types.GenerateVideosSource(prompt=prompt, image=image),
            config=types.GenerateVideosConfig(
                number_of_videos=1,
                duration_seconds=duration_seconds,
                aspect_ratio=self.settings.media_image_aspect_ratio,
                resolution=self.settings.video_generation_resolution,
                generate_audio=self.settings.video_generation_audio,
                enhance_prompt=True,
                output_gcs_uri=output_gcs_uri,
            ),
        )
        operation_name = str(
            getattr(operation, "name", None)
            or getattr(operation, "id", None)
            or ""
        ).strip()
        if on_operation_started is not None:
            on_operation_started(operation_name)

        if production_id and operation_id:
            self.veo_capture_service.persist_state(
                operation_id,
                production_id,
                "RUNNING",
                {
                    "providerOperation": operation_name,
                },
            )

        while not getattr(operation, "done", False):
            time.sleep(self.settings.video_generation_poll_seconds)
            operation = client.operations.get(operation)

        response = getattr(operation, "response", None) or getattr(operation, "result", None)

        # Capture completed Veo operation before asset persistence.
        # This stores raw provider response and normalizes usage metadata.
        provider_response = {
            "name": getattr(operation, "name", None),
            "id": getattr(operation, "id", None),
            "model": self.settings.video_generation_model,
            "response": str(response),
        }

        if production_id and operation_id:
            usage = self.capture_veo_completion(
                production_id,
                operation_id,
                provider_response,
            )

            actual_cost = (
                usage.get("cost")
                if usage
                else None
            )


        videos = getattr(response, "generated_videos", None) or []
        if not videos:
            reasons = getattr(response, "rai_media_filtered_reasons", None)
            suffix = f" Safety reasons: {reasons}" if reasons else ""
            raise MediaGenerationError(f"Veo returned no generated video.{suffix}")
        video = getattr(videos[0], "video", None)
        if video is None:
            raise MediaGenerationError("Veo returned a generation result without video media.")

        gcs_uri = getattr(video, "uri", None)
        data = getattr(video, "video_bytes", None) or getattr(video, "data", None)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if data:
            output_path.write_bytes(data)
        elif gcs_uri:
            self._download_gcs_video(gcs_uri, output_path)
        elif hasattr(video, "save"):
            video.save(str(output_path))
        else:
            raise MediaGenerationError("Veo finished, but ReviveAI could not persist the generated video output.")
        return gcs_uri, "video/mp4"

    async def generate_video_clip(
        self,
        *,
        source: MediaSourceSnapshot,
        keyframe_asset: MediaAsset,
        keyframe_path: Path,
        shot: StoryboardShot,
        assets_dir: Path,
        job_id: str,
        generation_attempt: int = 1,
        on_operation_started: Optional[Callable[[str], None]] = None,
        estimated_cost: Optional[float] = None,
        remaining_budget: Optional[float] = None,
        production_id: Optional[str] = None,
        operation_id: Optional[str] = None,
        corrective_instruction: Optional[str] = None,
    ):
        from app.models.media_studio import VideoClipAsset

        if not self.settings.video_output_gcs_uri:
            raise MediaGenerationError(
                "VIDEO_OUTPUT_GCS_URI is required for M2B.2. Set it to a writable gs:// bucket/prefix before starting Veo animation."
            )
        duration = self.supported_video_duration(shot.duration_seconds)

        # Budget gate must happen before submitting an expensive provider job.
        # Budget exhaustion is handled by the caller as a workflow state.
        if estimated_cost is not None and remaining_budget is not None:
            decision = self.check_generation_budget(
                estimated_cost,
                remaining_budget,
            )
            if not decision.allowed:
                raise MediaGenerationError(
                    "BUDGET_EXCEEDED"
                )

        prompt = self.video_prompt(source, shot, corrective_instruction=corrective_instruction)

        # Fail closed: no Veo submission without a durable, scoped reservation.
        if not production_id or not operation_id:
            raise MediaGenerationError("BUDGET_IDENTITY_REQUIRED")
        if estimated_cost is None:
            estimated_cost = (
                duration
                * float(self.settings.video_estimated_units_per_generated_second)
                * float(self.settings.video_estimated_cost_per_unit_usd)
            )
        reservation = self.firestore_budget_service.reserve(
            production_id=production_id, estimated_cost=estimated_cost,
            operation_id=operation_id,
        )
        if not reservation.get("allowed"):
            reason = str(reservation.get("reason") or "insufficient_funds")
            # Only insufficient capacity is a budget exhaustion event. Other
            # denials (e.g. idempotency recovery or an unavailable ledger) must
            # not be misreported as a reason to increase the production budget.
            if reason == "insufficient_funds":
                raise MediaGenerationError(
                    "BUDGET_EXCEEDED: production allocation insufficient; "
                    f"requested=${float(estimated_cost):.2f}, "
                    f"remaining=${float(reservation.get('remaining') or 0):.2f}"
                )
            raise MediaGenerationError(f"BUDGET_RESERVATION_REJECTED: {reason}")
        budget_transaction_id = reservation["transaction_id"]

        asset_id = f"clip_{shot.shot_number}_{uuid4().hex}"
        filename = f"{asset_id}.mp4"
        output_path = assets_dir / filename
        output_prefix = (
            f"{self.settings.video_output_gcs_uri.rstrip('/')}/tenants/{tenant_namespace()}/{job_id}/shot-{shot.shot_number}/v{generation_attempt}"
        )
        try:
            gcs_uri, mime = await asyncio.to_thread(
                self._generate_video_sync,
                keyframe_path=keyframe_path,
                prompt=prompt,
                output_path=output_path,
                output_gcs_uri=output_prefix,
                duration_seconds=duration,
                on_operation_started=on_operation_started,
                production_id=production_id,
                operation_id=operation_id,
            )
        except MediaGenerationError:
            raise
        except Exception as exc:
            raise MediaGenerationError(f"Veo could not animate shot {shot.shot_number}: {exc}") from exc

        if budget_transaction_id:
            self.firestore_budget_service.reconcile(
                production_id=production_id,
                operation_id=budget_transaction_id,
                estimated_cost=estimated_cost or 0,
                actual_cost=self.extract_veo_usage_cost(getattr(self, "_last_provider_response", None)) or estimated_cost or 0,
            )

        return VideoClipAsset(
            asset_id=asset_id,
            shot_number=shot.shot_number,
            created_at=datetime.now(timezone.utc),
            model=self.settings.video_generation_model,
            mime_type=mime,
            filename=filename,
            asset_url="",
            prompt=prompt,
            intended_duration_seconds=shot.duration_seconds,
            generated_duration_seconds=duration,
            source_keyframe_asset_id=keyframe_asset.asset_id,
            gcs_uri=gcs_uri,
            review_status=MediaAssetReviewStatus.NEEDS_REVIEW,
            generation_attempt=generation_attempt,
        )
