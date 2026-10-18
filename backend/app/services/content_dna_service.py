from __future__ import annotations

import asyncio
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import httpx

from app.core.config import Settings
from app.models.content_dna import (
    AiChannelSynthesis,
    AiCharacterGroup,
    AiGroup,
    AiIdentity,
    AiVoiceTone,
    AiIdentityVoiceSynthesis,
    AiPatternSynthesis,
    AiThemeCharacterSynthesis,
    AiThemeSynthesis,
    AiCharacterSynthesis,
    AiVideoClassification,
    AiVideoClassificationBatch,
    ChannelIdentity,
    CharacterInsight,
    ContentDnaJobStage,
    ContentDnaResult,
    GroupInsight,
    VideoContentClassification,
    VoiceToneInsight,
)
from app.models.youtube import AnalysisResult, VideoSnapshot
from app.services.content_dna_metrics_service import build_evidence_metrics, sanitize_video_ids


class ContentDnaError(RuntimeError):
    pass


StageCallback = Callable[[ContentDnaJobStage, str, int, int, Dict], None]


@dataclass
class ContentDnaCheckpoint:
    classifications: List[VideoContentClassification]
    visuals_analyzed: int
    successful_classifications: int
    total_videos: int
    identity_voice: Optional[AiIdentityVoiceSynthesis] = None
    themes: Optional[AiThemeSynthesis] = None
    characters: Optional[AiCharacterSynthesis] = None
    patterns: Optional[AiPatternSynthesis] = None


CheckpointCallback = Callable[[ContentDnaCheckpoint], None]


VIDEO_CLASSIFICATION_SYSTEM = """
You are ReviveAI's content-understanding analyst. Classify public YouTube content only from the supplied metadata and thumbnail images.

Rules:
- Do not infer private audience demographics, creator identity, creator intent, or off-screen facts.
- Do not infer performance. View counts, likes, comments, performance tiers, and analytics are intentionally hidden from you.
- Preserve every supplied video_id exactly.
- Keep theme, story-pattern, visual-pattern, and tone labels concise and reusable across the channel instead of inventing a unique label for every video.
- Use at most 3 themes, 3 story patterns, 5 visual patterns, and 4 tones per video.
- Name a recurring character only when the name is explicit in supplied text or clearly visible in the thumbnail. Otherwise use a generic description such as "unnamed dog" only when materially useful.
- Base visual claims only on the supplied thumbnail. If no thumbnail is supplied, do not invent visual details.
- Confidence must reflect how strongly the public evidence supports the classification.
""".strip()


CHANNEL_SYNTHESIS_SYSTEM = """
You are ReviveAI's channel-level content analyst. Build a compact Content DNA from aggregated per-video classifications.

Rules:
- Performance data is intentionally absent. Do not guess which content performed well or poorly.
- Normalize casing, singular/plural variants, and obvious near-duplicate candidate labels into reusable channel-level concepts.
- When the task requests aliases, aliases must be copied exactly from the supplied candidate labels.
- For named characters, merge spelling/casing variants only when the supplied public-text evidence clearly indicates the same recurring character. Do not merge distinct characters merely because their names look similar.
- Do not return video IDs unless the task explicitly asks for them; ReviveAI reconnects evidence deterministically in the backend.
- Do not claim causation, audience demographics, private analytics, or motivations.
- Keep descriptions concise so the final Content DNA is easy for a creator to scan.
""".strip()


def select_content_dna_videos(videos: Sequence[VideoSnapshot], limit: int) -> List[VideoSnapshot]:
    """Select a fast, recency-weighted archive sample without using performance data.

    Half of the sample comes from the newest uploads. The remainder is spread
    across the older archive so long-running channel themes are still visible.
    This preserves the performance firewall: views/likes/comments never affect
    which videos Gemini sees.
    """
    items = list(videos)
    if not limit or limit <= 0 or len(items) <= limit:
        return items

    dated = sorted(
        items,
        key=lambda video: video.published_at.timestamp() if video.published_at else float("-inf"),
        reverse=True,
    )
    recent_count = max(1, min(limit, (limit + 1) // 2))
    selected = list(dated[:recent_count])
    older = dated[recent_count:]
    remaining = limit - len(selected)
    if remaining > 0 and older:
        if remaining >= len(older):
            selected.extend(older)
        elif remaining == 1:
            selected.append(older[len(older) // 2])
        else:
            last = len(older) - 1
            indexes = [round(i * last / (remaining - 1)) for i in range(remaining)]
            selected.extend(older[index] for index in indexes)

    # De-duplicate defensively while preserving selection order.
    unique: List[VideoSnapshot] = []
    seen: set[str] = set()
    for video in selected:
        if video.video_id not in seen:
            unique.append(video)
            seen.add(video.video_id)
    return unique[:limit]


class ContentDnaService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.gemini_calls = 0
        self._intelligence_channel_id = None

    async def build(
        self,
        analysis: AnalysisResult,
        on_stage: StageCallback,
        checkpoint: Optional[ContentDnaCheckpoint] = None,
        on_checkpoint: Optional[CheckpointCallback] = None,
    ) -> ContentDnaResult:
        self._intelligence_channel_id = analysis.channel.channel_id
        self._validate_configuration()
        videos = self._videos_to_analyze(analysis.videos)
        total = len(videos)
        if not total:
            raise ContentDnaError("No public videos are available for Content DNA analysis.")

        reusable_checkpoint = self._checkpoint_is_usable(checkpoint, videos)
        on_stage(
            ContentDnaJobStage.PREPARING_EVIDENCE,
            "Preparing titles, descriptions, tags, and thumbnails",
            0,
            total,
            {
                "videos_selected": total,
                "archive_total": len(analysis.videos),
                "fast_dna": total < len(analysis.videos),
                "selection_strategy": "recency_weighted_archive_sample" if total < len(analysis.videos) else "full_archive",
                "performance_hidden_from_gemini": True,
                "checkpoint_available": reusable_checkpoint,
                "resumed_videos": total if reusable_checkpoint else 0,
            },
        )

        client, types = self._create_genai_client()

        if reusable_checkpoint and checkpoint is not None:
            classifications = list(checkpoint.classifications)
            visuals_analyzed = checkpoint.visuals_analyzed
            successful_classifications = checkpoint.successful_classifications
            on_stage(
                ContentDnaJobStage.ANALYZING_VIDEOS,
                f"Reusing {total} saved video classifications",
                total,
                total,
                {
                    "videos_analyzed": total,
                    "archive_total": len(analysis.videos),
                    "fast_dna": total < len(analysis.videos),
                    "visuals_analyzed": visuals_analyzed,
                    "gemini_calls": self.gemini_calls,
                    "performance_hidden_from_gemini": True,
                    "checkpoint_reused": True,
                    "videos_remaining": 0,
                    "batch_index": math.ceil(total / self.settings.content_dna_batch_size),
                    "batch_total": math.ceil(total / self.settings.content_dna_batch_size),
                    "recent_items": self._recent_items(videos, classifications[-3:]),
                },
            )
        else:
            classifications = []
            visuals_analyzed = 0
            successful_classifications = 0
            batch_size = self.settings.content_dna_batch_size
            batch_total = math.ceil(total / batch_size)

            async with httpx.AsyncClient(
                timeout=self.settings.content_dna_thumbnail_timeout_seconds,
                follow_redirects=True,
            ) as image_client:
                for start in range(0, total, batch_size):
                    batch = videos[start : start + batch_size]
                    batch_records, batch_visuals, batch_success = await self._classify_batch(
                        client=client,
                        types=types,
                        image_client=image_client,
                        channel_title=analysis.channel.title,
                        videos=batch,
                    )
                    classifications.extend(batch_records)
                    visuals_analyzed += batch_visuals
                    successful_classifications += batch_success

                    current = min(start + len(batch), total)
                    batch_index = (start // batch_size) + 1
                    on_stage(
                        ContentDnaJobStage.ANALYZING_VIDEOS,
                        f"Understanding video {current} of {total}",
                        current,
                        total,
                        {
                            "videos_analyzed": current,
                            "archive_total": len(analysis.videos),
                            "fast_dna": total < len(analysis.videos),
                            "visuals_analyzed": visuals_analyzed,
                            "gemini_calls": self.gemini_calls,
                            "performance_hidden_from_gemini": True,
                            "checkpoint_reused": False,
                            "videos_remaining": max(0, total - current),
                            "batch_index": batch_index,
                            "batch_total": batch_total,
                            "recent_items": self._recent_items(batch, batch_records[-3:]),
                        },
                    )

            if on_checkpoint is not None:
                on_checkpoint(
                    ContentDnaCheckpoint(
                        classifications=list(classifications),
                        visuals_analyzed=visuals_analyzed,
                        successful_classifications=successful_classifications,
                        total_videos=total,
                    )
                )

        # M1C.5 normalizes casing/plural variants in the reusable labels without
        # changing the underlying blind classification evidence or requiring a
        # new multimodal pass. Existing M1C.3/M1C.4 checkpoints can therefore be
        # reused safely.
        classifications = self._normalize_classifications(classifications)

        # Persist normalized classifications and any completed synthesis stages.
        # This makes Resume Content DNA genuinely stage-aware: after M1C.6, if a
        # later synthesis call fails, previously completed synthesis steps are not
        # regenerated on the next resume.
        synthesis_checkpoint = ContentDnaCheckpoint(
            classifications=list(classifications),
            visuals_analyzed=visuals_analyzed,
            successful_classifications=successful_classifications,
            total_videos=total,
            identity_voice=checkpoint.identity_voice if reusable_checkpoint and checkpoint else None,
            themes=checkpoint.themes if reusable_checkpoint and checkpoint else None,
            characters=checkpoint.characters if reusable_checkpoint and checkpoint else None,
            patterns=checkpoint.patterns if reusable_checkpoint and checkpoint else None,
        )
        if on_checkpoint is not None:
            on_checkpoint(synthesis_checkpoint)

        synthesis = await self._synthesize_channel(
            client=client,
            types=types,
            analysis=analysis,
            classifications=classifications,
            on_stage=on_stage,
            total=total,
            checkpoint_reused=reusable_checkpoint,
            checkpoint=synthesis_checkpoint,
            on_checkpoint=on_checkpoint,
        )

        on_stage(
            ContentDnaJobStage.CONNECTING_PERFORMANCE,
            "Connecting Content DNA to the deterministic evidence layer",
            total,
            total,
            {
                "videos_analyzed": total,
                "visuals_analyzed": visuals_analyzed,
                "gemini_calls": self.gemini_calls,
                "performance_connection": "backend_only",
                "synthesis_step": 4,
                "synthesis_total": 4,
                "checkpoint_reused": reusable_checkpoint,
            },
        )

        return self._compose_result(
            analysis=analysis,
            classifications=classifications,
            synthesis=synthesis,
            visuals_analyzed=visuals_analyzed,
            successful_classifications=successful_classifications,
        )

    def _validate_configuration(self) -> None:
        if not self.settings.google_cloud_project:
            raise ContentDnaError(
                "GOOGLE_CLOUD_PROJECT is not configured. Add it to backend/.env, enable Vertex AI, "
                "and authenticate locally with Application Default Credentials."
            )
        if not self.settings.gemini_model:
            raise ContentDnaError("GEMINI_MODEL is not configured.")

    def _create_genai_client(self):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise ContentDnaError(
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
            raise ContentDnaError(f"Could not initialize Vertex AI: {exc}") from exc
        return client, types

    def _videos_to_analyze(self, videos: Sequence[VideoSnapshot]) -> List[VideoSnapshot]:
        return select_content_dna_videos(videos, self.settings.content_dna_max_videos)

    @staticmethod
    def _checkpoint_is_usable(
        checkpoint: Optional[ContentDnaCheckpoint],
        videos: Sequence[VideoSnapshot],
    ) -> bool:
        if checkpoint is None or checkpoint.total_videos != len(videos):
            return False
        expected = [video.video_id for video in videos]
        actual = [item.video_id for item in checkpoint.classifications]
        return expected == actual

    async def _classify_batch(
        self,
        *,
        client,
        types,
        image_client: httpx.AsyncClient,
        channel_title: str,
        videos: Sequence[VideoSnapshot],
    ) -> Tuple[List[VideoContentClassification], int, int]:
        thumbnail_results = await asyncio.gather(
            *[self._download_thumbnail(image_client, self._thumbnail_url(video)) for video in videos]
        )

        parts = [
            types.Part.from_text(
                text=(
                    f"Channel: {channel_title}\n"
                    f"Classify the following {len(videos)} videos. Each video block is followed by its thumbnail when available. "
                    "Return one classification for every supplied video_id."
                )
            )
        ]
        visual_available: Dict[str, bool] = {}

        for video, image_payload in zip(videos, thumbnail_results):
            parts.append(types.Part.from_text(text=self._metadata_prompt(video)))
            if image_payload is not None:
                image_bytes, mime_type = image_payload
                parts.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))
                visual_available[video.video_id] = True
            else:
                parts.append(types.Part.from_text(text="Thumbnail unavailable; classify visual fields conservatively."))
                visual_available[video.video_id] = False

        content = types.Content(role="user", parts=parts)
        parsed = await self._generate_structured_with_retry(
            client=client,
            model=self.settings.gemini_model,
            contents=content,
            config=types.GenerateContentConfig(
                system_instruction=VIDEO_CLASSIFICATION_SYSTEM,
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=AiVideoClassificationBatch,
                max_output_tokens=12000,
            ),
            model_cls=AiVideoClassificationBatch,
            failure_message=(
                "Gemini could not return a complete classification for one video batch after multiple attempts. "
                "Retry Content DNA; no partial AI interpretation has been connected to performance evidence."
            ),
        )

        expected = {video.video_id: video for video in videos}
        returned: Dict[str, AiVideoClassification] = {}
        for item in parsed.classifications:
            if item.video_id in expected and item.video_id not in returned:
                returned[item.video_id] = item

        records: List[VideoContentClassification] = []
        successful = 0
        for video in videos:
            item = returned.get(video.video_id)
            if item is None:
                records.append(
                    VideoContentClassification(
                        video_id=video.video_id,
                        summary="Gemini did not return a classification for this video.",
                        confidence=0.0,
                        evidence_notes=["Classification unavailable for this batch."],
                        visual_evidence_available=visual_available.get(video.video_id, False),
                    )
                )
                continue

            successful += 1
            records.append(
                VideoContentClassification(
                    **item.model_dump(),
                    visual_evidence_available=visual_available.get(video.video_id, False),
                )
            )

        return records, sum(1 for value in visual_available.values() if value), successful

    async def _synthesize_channel(
        self,
        *,
        client,
        types,
        analysis: AnalysisResult,
        classifications: Sequence[VideoContentClassification],
        on_stage: StageCallback,
        total: int,
        checkpoint_reused: bool,
        checkpoint: ContentDnaCheckpoint,
        on_checkpoint: Optional[CheckpointCallback],
    ) -> AiChannelSynthesis:
        """Build channel-level DNA from compact aggregates, not the full archive JSON.

        M1C.2 still asked Gemini to emit long evidence_video_id arrays and repeated the
        complete 89-video classification payload for every synthesis pass. That can
        produce truncated structured JSON. M1C.3 instead asks Gemini only to normalize
        compact candidate labels. The backend then deterministically reconnects each
        canonical alias to every matching video_id.
        """
        aggregate = self._build_synthesis_aggregate(classifications, analysis)
        common_header = (
            f"Channel title: {analysis.channel.title}\n"
            f"Public channel description: {analysis.channel.description[:1000]}\n"
            f"Classified videos: {len(classifications)}\n\n"
            "Performance data is intentionally absent. Do not infer performance.\n"
            "IMPORTANT: Whenever you return aliases, copy them EXACTLY from the supplied candidate labels. "
            "Do not invent alias strings. ReviveAI uses those aliases to reconnect evidence deterministically.\n"
        )

        # Resume at the first missing synthesis artifact. Each completed artifact is
        # persisted alongside the expensive video classifications. This means a
        # transient failure no longer repeats successful synthesis work.
        identity_voice = checkpoint.identity_voice
        themes_only = checkpoint.themes
        characters_only = checkpoint.characters
        patterns = checkpoint.patterns

        completed_steps = sum(
            value is not None
            for value in (identity_voice, themes_only, characters_only, patterns)
        )

        on_stage(
            ContentDnaJobStage.SYNTHESIZING_DNA,
            "Resuming saved channel synthesis" if completed_steps else "Mapping channel identity and voice",
            total,
            total,
            self._synthesis_detail(
                total,
                completed_steps,
                ["Identity & voice", "Themes", "Characters", "Story & visual grammar", "Synthesis complete"][completed_steps],
                checkpoint_reused,
            ),
        )

        if identity_voice is None:
            identity_prompt = (
                common_header
                + "\nCOMPACT_CHANNEL_SIGNALS_JSON="
                + json.dumps(
                    {
                        "top_themes": aggregate["themes"][:20],
                        "top_tones": aggregate["tones"][:20],
                        "content_intents": aggregate["content_intents"][:12],
                        "settings": aggregate["settings"][:12],
                        "sample_videos": aggregate["sample_videos"][:12],
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n\nTASK: Return a concise channel identity and 4-8 reusable voice/tone traits. "
                "Each tone must include aliases copied exactly from top_tones. Keep explanations to one sentence."
            )
            identity_voice = await self._generate_structured_with_retry(
                client=client,
                model=self.settings.gemini_model,
                contents=identity_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=CHANNEL_SYNTHESIS_SYSTEM,
                    temperature=0.1,
                    candidate_count=1,
                    response_mime_type="application/json",
                    response_schema=AiIdentityVoiceSynthesis,
                    max_output_tokens=3000,
                ),
                model_cls=AiIdentityVoiceSynthesis,
                failure_message=self._synthesis_failure_message("Identity & voice"),
            )
            checkpoint.identity_voice = identity_voice
            if on_checkpoint is not None:
                on_checkpoint(checkpoint)

        on_stage(
            ContentDnaJobStage.SYNTHESIZING_DNA,
            "Channel identity and voice mapped",
            total,
            total,
            self._synthesis_detail(total, 1, "Themes", checkpoint_reused),
        )

        # M1C.6 deliberately separates themes and characters. M1C.5 asked Gemini
        # to return both taxonomies in one structured response; on real channels
        # that response could still be truncated even though the input was compact.
        if themes_only is None:
            theme_prompt = (
                common_header
                + "\nTHEME_CANDIDATES_JSON="
                + json.dumps(aggregate["themes"][:32], ensure_ascii=False, separators=(",", ":"))
                + "\n\nTASK: Normalize the supplied candidates into 5-8 recurring channel themes. "
                "For every theme, aliases MUST be exact candidate labels from THEME_CANDIDATES_JSON. "
                "Use a short display name and one concise sentence of description. "
                "Do not return characters or video IDs."
            )
            themes_only = await self._generate_structured_with_retry(
                client=client,
                model=self.settings.gemini_model,
                contents=theme_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=CHANNEL_SYNTHESIS_SYSTEM,
                    temperature=0.1,
                    candidate_count=1,
                    response_mime_type="application/json",
                    response_schema=AiThemeSynthesis,
                    max_output_tokens=3500,
                ),
                model_cls=AiThemeSynthesis,
                failure_message=self._synthesis_failure_message("Themes"),
            )
            checkpoint.themes = themes_only
            if on_checkpoint is not None:
                on_checkpoint(checkpoint)

        on_stage(
            ContentDnaJobStage.SYNTHESIZING_DNA,
            "Themes mapped",
            total,
            total,
            self._synthesis_detail(total, 2, "Characters", checkpoint_reused),
        )

        if characters_only is None:
            character_prompt = (
                common_header
                + "\nCHARACTER_CANDIDATES_JSON="
                + json.dumps(aggregate["characters"][:24], ensure_ascii=False, separators=(",", ":"))
                + "\n\nTASK: Summarize up to 12 meaningful recurring named characters using only names in CHARACTER_CANDIDATES_JSON. "
                "For each character, aliases MUST be copied exactly from CHARACTER_CANDIDATES_JSON and may include clear spelling/casing variants only when public-text evidence indicates the same recurring character. "
                "Choose one canonical display name; prefer the candidate with more public_text_video_mentions, then higher classification count. "
                "Do NOT merge distinct names merely because they look similar (for example, Choco and Coco can be different characters). "
                "Normalize duplicate role labels and casing. Keep each description to one concise sentence. Do not return themes or video IDs."
            )
            characters_only = await self._generate_structured_with_retry(
                client=client,
                model=self.settings.gemini_model,
                contents=character_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=CHANNEL_SYNTHESIS_SYSTEM,
                    temperature=0.1,
                    candidate_count=1,
                    response_mime_type="application/json",
                    response_schema=AiCharacterSynthesis,
                    max_output_tokens=5000,
                ),
                model_cls=AiCharacterSynthesis,
                failure_message=self._synthesis_failure_message("Characters"),
            )
            checkpoint.characters = characters_only
            if on_checkpoint is not None:
                on_checkpoint(checkpoint)

        themes_characters = AiThemeCharacterSynthesis(
            themes=themes_only.themes,
            characters=characters_only.characters,
        )
        on_stage(
            ContentDnaJobStage.SYNTHESIZING_DNA,
            "Themes and characters mapped",
            total,
            total,
            self._synthesis_detail(total, 3, "Story & visual grammar", checkpoint_reused),
        )

        if patterns is None:
            pattern_prompt = (
                common_header
                + "\nSTORY_PATTERN_CANDIDATES_JSON="
                + json.dumps(aggregate["story_patterns"][:40], ensure_ascii=False, separators=(",", ":"))
                + "\nVISUAL_PATTERN_CANDIDATES_JSON="
                + json.dumps(aggregate["visual_patterns"][:40], ensure_ascii=False, separators=(",", ":"))
                + "\n\nTASK: Normalize 5-10 recurring story patterns and 5-10 recurring visual patterns. "
                "Every alias MUST be copied exactly from the corresponding candidate list. "
                "Do not return video IDs."
            )
            patterns = await self._generate_structured_with_retry(
                client=client,
                model=self.settings.gemini_model,
                contents=pattern_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=CHANNEL_SYNTHESIS_SYSTEM,
                    temperature=0.1,
                    candidate_count=1,
                    response_mime_type="application/json",
                    response_schema=AiPatternSynthesis,
                    max_output_tokens=5000,
                ),
                model_cls=AiPatternSynthesis,
                failure_message=self._synthesis_failure_message("Story & visual grammar"),
            )
            checkpoint.patterns = patterns
            if on_checkpoint is not None:
                on_checkpoint(checkpoint)

        synthesis = self._reconnect_synthesis_evidence(
            classifications=classifications,
            identity_voice=identity_voice,
            themes_characters=themes_characters,
            patterns=patterns,
        )
        on_stage(
            ContentDnaJobStage.SYNTHESIZING_DNA,
            "Story and visual grammar mapped",
            total,
            total,
            self._synthesis_detail(total, 4, "Synthesis complete", checkpoint_reused),
        )
        return synthesis

    def _synthesis_detail(
        self,
        total: int,
        step: int,
        label: str,
        checkpoint_reused: bool,
    ) -> Dict:
        return {
            "videos_analyzed": total,
            "gemini_calls": self.gemini_calls,
            "performance_hidden_from_gemini": True,
            "synthesis_step": step,
            "synthesis_total": 4,
            "synthesis_label": label,
            "checkpoint_reused": checkpoint_reused,
            "synthesis_strategy": "compact_alias_map",
        }

    @staticmethod
    def _synthesis_failure_message(step: str) -> str:
        return (
            f"Gemini could not complete the compact '{step}' synthesis after multiple attempts. "
            "Your completed video classifications are safe. Resume Content DNA to retry only channel synthesis."
        )

    @staticmethod
    def _normalize_label(value: str) -> str:
        return " ".join((value or "").strip().casefold().split())

    @staticmethod
    def _singular_token(token: str) -> str:
        """Conservative singularization used only for duplicate-label detection."""
        if len(token) > 4 and token.endswith("ies"):
            return token[:-3] + "y"
        if len(token) > 4 and token.endswith("ses") and not token.endswith("sses"):
            return token[:-2]
        if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
            return token[:-1]
        return token

    @classmethod
    def _semantic_label_key(cls, value: str) -> str:
        normalized = cls._normalize_label(value).replace("&", " and ")
        tokens = re.findall(r"[a-z0-9]+", normalized)
        stopwords = {"a", "an", "the", "and", "of"}
        roots = [cls._singular_token(token) for token in tokens if token not in stopwords]
        return " ".join(roots)

    @staticmethod
    def _display_label_score(value: str) -> Tuple[int, int]:
        label = (value or "").strip()
        if not label:
            return (0, 0)
        letters = [char for char in label if char.isalpha()]
        if not letters:
            return (1, len(label))
        if label.istitle():
            return (4, len(label))
        if any(char.isupper() for char in label[1:]) or any(char.isdigit() for char in label):
            return (3, len(label))
        if label[:1].isupper():
            return (2, len(label))
        return (1, len(label))

    @classmethod
    def _dedupe_display_labels(cls, values: Sequence[str]) -> List[str]:
        best: Dict[str, str] = {}
        order: List[str] = []
        for raw in values:
            label = " ".join(str(raw or "").strip().split())
            key = cls._semantic_label_key(label)
            if not key:
                continue
            if key not in best:
                best[key] = label
                order.append(key)
            elif cls._display_label_score(label) > cls._display_label_score(best[key]):
                best[key] = label
        return [best[key] for key in order]

    def _normalize_classifications(
        self,
        classifications: Sequence[VideoContentClassification],
    ) -> List[VideoContentClassification]:
        """Normalize reusable labels without changing the classification meaning.

        This runs after a checkpoint is loaded, so old M1C.3/M1C.4 checkpoints can
        benefit from M1C.5 casing/plural cleanup without another multimodal pass.
        Character names are *not* fuzzy-merged here; character alias merging remains
        an explicit synthesis task grounded in public-text candidates.
        """
        normalized: List[VideoContentClassification] = []
        for item in classifications:
            characters = []
            for character in item.characters:
                role = None
                if character.role:
                    role_values = self._dedupe_display_labels([character.role])
                    role = role_values[0] if role_values else None
                characters.append(
                    character.model_copy(
                        update={
                            "name": " ".join((character.name or "").strip().split()),
                            "animal_or_subject": " ".join((character.animal_or_subject or "").strip().split()) or None,
                            "role": role,
                        }
                    )
                )
            normalized.append(
                item.model_copy(
                    update={
                        "themes": self._dedupe_display_labels(item.themes),
                        "story_patterns": self._dedupe_display_labels(item.story_patterns),
                        "visual_patterns": self._dedupe_display_labels(item.visual_patterns),
                        "tones": self._dedupe_display_labels(item.tones),
                        "characters": characters,
                    }
                )
            )
        return normalized

    def _aggregate_labels(
        self,
        classifications: Sequence[VideoContentClassification],
        attribute: str,
    ) -> List[Dict]:
        counts: Counter[str] = Counter()
        display_candidates: Dict[str, Counter[str]] = defaultdict(Counter)
        samples: Dict[str, List[str]] = defaultdict(list)
        for item in classifications:
            for raw in getattr(item, attribute, []) or []:
                label = str(raw).strip()
                key = self._semantic_label_key(label)
                if not key:
                    continue
                counts[key] += 1
                display_candidates[key][label] += 1
                if len(samples[key]) < 3:
                    samples[key].append(item.video_id)

        def display_for(key: str) -> str:
            candidates = display_candidates[key]
            return max(
                candidates,
                key=lambda label: (candidates[label], self._display_label_score(label)),
            )

        return [
            {"label": display_for(key), "count": count, "sample_video_ids": samples[key]}
            for key, count in counts.most_common()
        ]

    def _aggregate_scalar(
        self,
        classifications: Sequence[VideoContentClassification],
        attribute: str,
    ) -> List[Dict]:
        counts: Counter[str] = Counter()
        display_candidates: Dict[str, Counter[str]] = defaultdict(Counter)
        for item in classifications:
            raw = getattr(item, attribute, None)
            if raw is None:
                continue
            label = str(raw).strip()
            key = self._semantic_label_key(label)
            if not key or key == "unknown":
                continue
            counts[key] += 1
            display_candidates[key][label] += 1

        result = []
        for key, count in counts.most_common():
            candidates = display_candidates[key]
            display = max(candidates, key=lambda label: (candidates[label], self._display_label_score(label)))
            result.append({"label": display, "count": count})
        return result

    @staticmethod
    def _public_text_blob(video: VideoSnapshot) -> str:
        return " ".join(
            part
            for part in [video.title, video.description, " ".join(video.tags or [])]
            if part
        )

    @staticmethod
    def _literal_name_present(name: str, text: str) -> bool:
        candidate = (name or "").strip()
        if not candidate or not text:
            return False
        return bool(re.search(rf"(?<!\w){re.escape(candidate)}(?!\w)", text, flags=re.IGNORECASE))

    def _aggregate_characters(
        self,
        classifications: Sequence[VideoContentClassification],
        analysis: AnalysisResult,
    ) -> List[Dict]:
        entries: Dict[str, Dict] = {}
        video_map = {video.video_id: video for video in analysis.videos}
        all_public_text = [(video, self._public_text_blob(video)) for video in analysis.videos]

        for item in classifications:
            for character in item.characters:
                name = " ".join((character.name or "").strip().split())
                key = self._normalize_label(name)
                if not key or key.startswith("unnamed "):
                    continue
                entry = entries.setdefault(
                    key,
                    {
                        "name": name,
                        "count": 0,
                        "roles": [],
                        "subjects": [],
                        "sample_video_ids": [],
                        "source_examples": [],
                    },
                )
                entry["count"] += 1
                if character.role:
                    entry["roles"].append(character.role)
                if character.animal_or_subject:
                    entry["subjects"].append(character.animal_or_subject)
                if len(entry["sample_video_ids"]) < 3:
                    entry["sample_video_ids"].append(item.video_id)
                video = video_map.get(item.video_id)
                if video is not None and len(entry["source_examples"]) < 3:
                    entry["source_examples"].append(video.title[:140])

        result = []
        for entry in entries.values():
            public_text_video_mentions = sum(
                1 for _, text in all_public_text if self._literal_name_present(entry["name"], text)
            )
            result.append(
                {
                    "name": entry["name"],
                    "count": entry["count"],
                    "public_text_video_mentions": public_text_video_mentions,
                    "roles": self._dedupe_display_labels(entry["roles"])[:6],
                    "subjects": self._dedupe_display_labels(entry["subjects"])[:3],
                    "sample_video_ids": entry["sample_video_ids"],
                    "source_examples": entry["source_examples"],
                }
            )
        return sorted(
            result,
            key=lambda entry: (-entry["public_text_video_mentions"], -entry["count"], entry["name"].casefold()),
        )

    def _build_synthesis_aggregate(
        self,
        classifications: Sequence[VideoContentClassification],
        analysis: AnalysisResult,
    ) -> Dict:
        confident = [item for item in classifications if item.confidence > 0]
        # A small representative set is enough for channel identity. The taxonomy
        # itself comes from aggregate labels across every classified video.
        sample_videos = [
            {
                "video_id": item.video_id,
                "summary": item.summary[:240],
                "themes": item.themes[:3],
                "tones": item.tones[:3],
                "content_intent": item.content_intent,
                "setting": item.setting,
            }
            for item in sorted(confident, key=lambda x: x.confidence, reverse=True)[:16]
        ]
        return {
            "themes": self._aggregate_labels(confident, "themes"),
            "tones": self._aggregate_labels(confident, "tones"),
            "story_patterns": self._aggregate_labels(confident, "story_patterns"),
            "visual_patterns": self._aggregate_labels(confident, "visual_patterns"),
            "content_intents": self._aggregate_scalar(confident, "content_intent"),
            "settings": self._aggregate_scalar(confident, "setting"),
            "characters": self._aggregate_characters(confident, analysis),
            "sample_videos": sample_videos,
        }

    def _ids_for_aliases(
        self,
        classifications: Sequence[VideoContentClassification],
        attribute: str,
        aliases: Sequence[str],
    ) -> List[str]:
        wanted = {self._normalize_label(alias) for alias in aliases if alias}
        if not wanted:
            return []
        ids: List[str] = []
        for item in classifications:
            values = getattr(item, attribute, []) or []
            if any(self._normalize_label(str(value)) in wanted for value in values):
                ids.append(item.video_id)
        return list(dict.fromkeys(ids))

    def _ids_for_character_aliases(
        self,
        classifications: Sequence[VideoContentClassification],
        aliases: Sequence[str],
    ) -> List[str]:
        wanted = {self._normalize_label(alias) for alias in aliases if alias}
        if not wanted:
            return []
        ids: List[str] = []
        for item in classifications:
            if any(self._normalize_label(character.name) in wanted for character in item.characters):
                ids.append(item.video_id)
        return list(dict.fromkeys(ids))

    def _representative_identity_ids(
        self,
        classifications: Sequence[VideoContentClassification],
    ) -> List[str]:
        return [
            item.video_id
            for item in sorted(classifications, key=lambda x: x.confidence, reverse=True)[:8]
            if item.confidence > 0
        ]

    def _merge_ai_groups(self, groups: Sequence[AiGroup]) -> List[AiGroup]:
        merged: Dict[str, AiGroup] = {}
        order: List[str] = []
        for item in groups:
            key = self._semantic_label_key(item.name)
            if not key:
                continue
            if key not in merged:
                merged[key] = item.model_copy(
                    update={
                        "name": " ".join(item.name.split()),
                        "evidence_video_ids": list(dict.fromkeys(item.evidence_video_ids)),
                    }
                )
                order.append(key)
                continue
            current = merged[key]
            merged[key] = current.model_copy(
                update={
                    "name": max([current.name, item.name], key=self._display_label_score),
                    "description": current.description if len(current.description) >= len(item.description) else item.description,
                    "evidence_video_ids": list(dict.fromkeys(current.evidence_video_ids + item.evidence_video_ids)),
                }
            )
        return [merged[key] for key in order]

    def _merge_voice_tones(self, tones: Sequence[AiVoiceTone]) -> List[AiVoiceTone]:
        merged: Dict[str, AiVoiceTone] = {}
        order: List[str] = []
        for item in tones:
            key = self._semantic_label_key(item.label)
            if not key:
                continue
            if key not in merged:
                merged[key] = item.model_copy(
                    update={"evidence_video_ids": list(dict.fromkeys(item.evidence_video_ids))}
                )
                order.append(key)
                continue
            current = merged[key]
            merged[key] = current.model_copy(
                update={
                    "label": max([current.label, item.label], key=self._display_label_score),
                    "explanation": current.explanation if len(current.explanation) >= len(item.explanation) else item.explanation,
                    "confidence": max(current.confidence, item.confidence),
                    "evidence_video_ids": list(dict.fromkeys(current.evidence_video_ids + item.evidence_video_ids)),
                }
            )
        return [merged[key] for key in order]

    def _merge_character_groups(self, characters: Sequence[AiCharacterGroup]) -> List[AiCharacterGroup]:
        merged: List[AiCharacterGroup] = []
        for item in characters:
            item_aliases = self._dedupe_display_labels([item.name, *item.aliases])
            item_keys = {self._normalize_label(alias) for alias in item_aliases if alias}
            match_index = None
            for index, current in enumerate(merged):
                current_keys = {self._normalize_label(alias) for alias in [current.name, *current.aliases] if alias}
                if item_keys & current_keys:
                    match_index = index
                    break
            if match_index is None:
                merged.append(
                    item.model_copy(
                        update={
                            "aliases": [alias for alias in item_aliases if self._normalize_label(alias) != self._normalize_label(item.name)],
                            "roles": self._dedupe_display_labels(item.roles),
                            "evidence_video_ids": list(dict.fromkeys(item.evidence_video_ids)),
                        }
                    )
                )
                continue

            current = merged[match_index]
            canonical_candidates = [current.name, item.name]
            canonical = max(canonical_candidates, key=self._display_label_score)
            all_aliases = self._dedupe_display_labels([current.name, *current.aliases, item.name, *item.aliases])
            aliases = [alias for alias in all_aliases if self._normalize_label(alias) != self._normalize_label(canonical)]
            merged[match_index] = current.model_copy(
                update={
                    "name": canonical,
                    "description": current.description if len(current.description) >= len(item.description) else item.description,
                    "aliases": aliases,
                    "roles": self._dedupe_display_labels([*current.roles, *item.roles]),
                    "evidence_video_ids": list(dict.fromkeys(current.evidence_video_ids + item.evidence_video_ids)),
                }
            )
        return merged

    def _reconnect_synthesis_evidence(
        self,
        *,
        classifications: Sequence[VideoContentClassification],
        identity_voice: AiIdentityVoiceSynthesis,
        themes_characters: AiThemeCharacterSynthesis,
        patterns: AiPatternSynthesis,
    ) -> AiChannelSynthesis:
        identity = AiIdentity(
            **identity_voice.identity.model_dump(),
            evidence_video_ids=self._representative_identity_ids(classifications),
        )
        voice = [
            AiVoiceTone(
                label=item.label,
                explanation=item.explanation,
                confidence=item.confidence,
                evidence_video_ids=self._ids_for_aliases(classifications, "tones", item.aliases),
            )
            for item in identity_voice.voice_tone
        ]
        themes = [
            AiGroup(
                name=item.name,
                description=item.description,
                evidence_video_ids=self._ids_for_aliases(classifications, "themes", item.aliases),
            )
            for item in themes_characters.themes
        ]
        characters = []
        for item in themes_characters.characters:
            aliases = self._dedupe_display_labels([item.name, *item.aliases])
            ids = self._ids_for_character_aliases(classifications, aliases)
            characters.append(
                AiCharacterGroup(
                    name=item.name,
                    description=item.description,
                    aliases=[alias for alias in aliases if self._normalize_label(alias) != self._normalize_label(item.name)],
                    roles=self._dedupe_display_labels(item.roles),
                    evidence_video_ids=ids,
                )
            )
        story_patterns = [
            AiGroup(
                name=item.name,
                description=item.description,
                evidence_video_ids=self._ids_for_aliases(classifications, "story_patterns", item.aliases),
            )
            for item in patterns.story_patterns
        ]
        visual_patterns = [
            AiGroup(
                name=item.name,
                description=item.description,
                evidence_video_ids=self._ids_for_aliases(classifications, "visual_patterns", item.aliases),
            )
            for item in patterns.visual_patterns
        ]
        voice = self._merge_voice_tones([item for item in voice if item.evidence_video_ids])
        themes = self._merge_ai_groups([item for item in themes if item.evidence_video_ids])
        characters = self._merge_character_groups([item for item in characters if item.evidence_video_ids])
        story_patterns = self._merge_ai_groups([item for item in story_patterns if item.evidence_video_ids])
        visual_patterns = self._merge_ai_groups([item for item in visual_patterns if item.evidence_video_ids])
        return AiChannelSynthesis(
            identity=identity,
            voice_tone=voice,
            themes=themes,
            characters=characters,
            story_patterns=story_patterns,
            visual_patterns=visual_patterns,
        )

    async def _generate_structured_with_retry(
        self,
        *,
        client,
        model: str,
        contents,
        config,
        model_cls,
        failure_message: str,
    ):
        attempts = max(1, self.settings.content_dna_retry_attempts)
        last_error: Optional[Exception] = None

        for attempt in range(attempts):
            try:
                self.gemini_calls += 1
                from app.services.channel_intelligence_budget import ChannelIntelligenceBudget
                response = await ChannelIntelligenceBudget().generate(
                    channel_id=self._intelligence_channel_id, category="content_dna", client=client,
                    model=model,
                    contents=contents,
                    config=config,
                )
                return self._parse_response(response, model_cls)
            except Exception as exc:
                from app.services.channel_intelligence_budget import IntelligenceProviderOutcomeUncertain
                if isinstance(exc, IntelligenceProviderOutcomeUncertain):
                    raise
                last_error = exc
                if attempt + 1 >= attempts:
                    break
                await asyncio.sleep(1.2 * (2**attempt))

        raise ContentDnaError(failure_message) from last_error

    @staticmethod
    def _parse_response(response, model_cls):
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, model_cls):
            return parsed
        if parsed is not None:
            try:
                return model_cls.model_validate(parsed)
            except Exception:
                pass

        text = getattr(response, "text", None)
        if not text:
            raise ValueError("Gemini returned an empty structured response.")
        return model_cls.model_validate_json(text)

    async def _download_thumbnail(
        self,
        client: httpx.AsyncClient,
        url: Optional[str],
    ) -> Optional[Tuple[bytes, str]]:
        if not url:
            return None
        try:
            response = await client.get(url)
            response.raise_for_status()
        except Exception:
            return None

        content_type = response.headers.get("content-type", "image/jpeg").split(";")[0].strip().lower()
        if not content_type.startswith("image/"):
            content_type = "image/jpeg"
        if not response.content:
            return None
        return response.content, content_type

    @staticmethod
    def _thumbnail_url(video: VideoSnapshot) -> Optional[str]:
        return (
            video.thumbnails.high
            or video.thumbnails.medium
            or video.thumbnails.standard
            or video.thumbnails.default
        )

    @staticmethod
    def _metadata_prompt(video: VideoSnapshot) -> str:
        tags = ", ".join(video.tags[:20]) if video.tags else "none"
        description = " ".join(video.description.split())[:1600]
        return (
            "\nVIDEO\n"
            f"video_id: {video.video_id}\n"
            f"title: {video.title}\n"
            f"description: {description or 'none'}\n"
            f"tags: {tags}\n"
            f"duration_seconds: {video.duration_seconds}\n"
            f"default_language: {video.default_language or 'unknown'}\n"
            f"default_audio_language: {video.default_audio_language or 'unknown'}\n"
            "Important: no view, like, comment, or performance data is included.\n"
        )

    def _recent_items(
        self,
        videos: Sequence[VideoSnapshot],
        records: Sequence[VideoContentClassification],
    ) -> List[Dict]:
        record_map = {record.video_id: record for record in records}
        items: List[Dict] = []
        for video in videos:
            record = record_map.get(video.video_id)
            if record is None:
                continue
            items.append(
                {
                    "video_id": video.video_id,
                    "title": video.title,
                    "thumbnail_url": self._thumbnail_url(video),
                    "themes": record.themes[:2],
                    "confidence": record.confidence,
                    "visual_evidence_available": record.visual_evidence_available,
                }
            )
        return items[-3:]

    def _compose_result(
        self,
        *,
        analysis: AnalysisResult,
        classifications: Sequence[VideoContentClassification],
        synthesis: AiChannelSynthesis,
        visuals_analyzed: int,
        successful_classifications: int,
    ) -> ContentDnaResult:
        identity_ids = sanitize_video_ids(synthesis.identity.evidence_video_ids, analysis)
        identity = ChannelIdentity(
            summary=synthesis.identity.summary,
            primary_niche=synthesis.identity.primary_niche,
            content_promise=synthesis.identity.content_promise,
            dominant_format=synthesis.identity.dominant_format,
            language_style=synthesis.identity.language_style,
            confidence=_clamp_confidence(synthesis.identity.confidence),
            evidence_video_ids=identity_ids,
        )

        voice_tone = [
            VoiceToneInsight(
                label=item.label,
                explanation=item.explanation,
                confidence=_clamp_confidence(item.confidence),
                evidence_video_ids=(ids := sanitize_video_ids(item.evidence_video_ids, analysis)),
                evidence=build_evidence_metrics(ids, analysis),
            )
            for item in synthesis.voice_tone
        ]

        themes = [
            self._group_insight(item.name, item.description, item.evidence_video_ids, analysis)
            for item in synthesis.themes
        ]
        story_patterns = [
            self._group_insight(item.name, item.description, item.evidence_video_ids, analysis)
            for item in synthesis.story_patterns
        ]
        visual_patterns = [
            self._group_insight(item.name, item.description, item.evidence_video_ids, analysis)
            for item in synthesis.visual_patterns
        ]

        characters = []
        for item in synthesis.characters:
            ids = sanitize_video_ids(item.evidence_video_ids, analysis)
            characters.append(
                CharacterInsight(
                    name=item.name,
                    description=item.description,
                    aliases=self._dedupe_display_labels(item.aliases),
                    roles=self._dedupe_display_labels(item.roles),
                    evidence_video_ids=ids,
                    evidence=build_evidence_metrics(ids, analysis),
                )
            )

        return ContentDnaResult(
            generated_at=datetime.now(timezone.utc),
            model=self.settings.gemini_model,
            videos_classified=successful_classifications,
            visuals_analyzed=visuals_analyzed,
            metadata_only_videos=max(0, len(classifications) - visuals_analyzed),
            unclassified_videos=max(0, len(classifications) - successful_classifications),
            gemini_calls=self.gemini_calls,
            identity=identity,
            voice_tone=_sort_by_evidence_count(voice_tone),
            themes=_sort_by_evidence_count(themes),
            characters=_sort_by_evidence_count(characters),
            story_patterns=_sort_by_evidence_count(story_patterns),
            visual_patterns=_sort_by_evidence_count(visual_patterns),
            video_classifications=list(classifications),
        )

    @staticmethod
    def _group_insight(name, description, video_ids, analysis) -> GroupInsight:
        ids = sanitize_video_ids(video_ids, analysis)
        return GroupInsight(
            name=name,
            description=description,
            evidence_video_ids=ids,
            evidence=build_evidence_metrics(ids, analysis),
        )


def _sort_by_evidence_count(items: Iterable):
    return sorted(items, key=lambda item: item.evidence.video_count, reverse=True)


def _clamp_confidence(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 2)
