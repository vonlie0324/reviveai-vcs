from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, Iterable, Optional

from app.core.config import Settings, get_settings
from app.core.tenant import TenantScopedDict, tenant_scoped_root
from app.models.audio_finishing import (
    BackgroundMusicPreset,
    MusicSource,
    YouTubeAudioLibraryLicenseType,
)
from app.models.final_assembly import FinalAssemblyReviewStatus
from app.models.music_match import (
    AiMusicMatchPack,
    MusicMatchContext,
    MusicMatchPacing,
    MusicMatchRecommendation,
    MusicMatchResult,
)
from app.services.audio_finishing_job_service import audio_finishing_job_store
from app.services.final_assembly_job_service import FinalAssemblyJobNotFoundError, final_assembly_job_store
from app.services.production_brief_job_service import ProductionBriefJobNotFoundError, production_brief_job_store
from app.services.trending_music_service import TrendingMusicCatalogError, trending_music_catalog
from app.services.youtube_audio_library_service import YouTubeAudioLibraryError, youtube_audio_library

logger = logging.getLogger(__name__)


class MusicMatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class _Candidate:
    candidate_key: str
    source: MusicSource
    title: str
    artist: str
    genre: str
    moods: tuple[str, ...]
    description: str
    energy: float
    rights_summary: str
    preview_available: bool
    render_ready: bool
    preset: Optional[BackgroundMusicPreset] = None
    track_id: Optional[str] = None
    duration_seconds: Optional[float] = None


_PRESET_META: dict[BackgroundMusicPreset, dict] = {
    BackgroundMusicPreset.CINEMATIC_AMBIENT: {
        "title": "Cinematic ambient",
        "genre": "Cinematic",
        "moods": ("cinematic", "atmospheric", "restrained", "spacious"),
        "description": "Spacious, restrained, filmic underscore that stays out of the way of narration.",
        "energy": 1.35,
    },
    BackgroundMusicPreset.WARM_INSPIRATIONAL: {
        "title": "Warm inspirational",
        "genre": "Inspirational",
        "moods": ("warm", "inspirational", "uplifting", "hopeful", "optimistic"),
        "description": "Optimistic, warm bed with a gentle emotional lift and moderate movement.",
        "energy": 2.05,
    },
    BackgroundMusicPreset.MODERN_PULSE: {
        "title": "Modern pulse",
        "genre": "Electronic",
        "moods": ("modern", "rhythmic", "energetic", "driving", "contemporary"),
        "description": "Clean contemporary pulse with stronger rhythmic momentum.",
        "energy": 2.9,
    },
    BackgroundMusicPreset.REFLECTIVE: {
        "title": "Reflective",
        "genre": "Ambient",
        "moods": ("reflective", "calm", "gentle", "intimate", "soft"),
        "description": "Calm, intimate, understated atmosphere designed to leave room for speech.",
        "energy": 1.0,
    },
    BackgroundMusicPreset.BRIGHT_UPBEAT: {
        "title": "Bright upbeat",
        "genre": "Upbeat",
        "moods": ("bright", "upbeat", "playful", "happy", "positive"),
        "description": "Light, positive, energetic momentum for playful or celebratory pacing.",
        "energy": 3.0,
    },
}

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "your", "their", "then", "while",
    "video", "music", "audio", "story", "shot", "short", "scene", "tone", "feel", "style", "using",
}


def _tokens(*values: str) -> set[str]:
    output: set[str] = set()
    for value in values:
        for token in re.findall(r"[a-z0-9]+", (value or "").lower()):
            if len(token) >= 3 and token not in _STOPWORDS:
                output.add(token)
    return output


def _tag_list(value: str) -> tuple[str, ...]:
    values = [item.strip() for item in re.split(r"[,/|;]+", value or "") if item.strip()]
    return tuple(dict.fromkeys(values))


def _energy_from_metadata(genre: str, moods: Iterable[str]) -> float:
    text = " ".join([genre, *moods]).lower()
    high = ("upbeat", "energetic", "dance", "rock", "driving", "pulse", "happy", "bright", "sport", "action")
    low = ("calm", "ambient", "reflective", "gentle", "soft", "meditation", "sad", "intimate", "cinematic")
    if any(word in text for word in high):
        return 2.8
    if any(word in text for word in low):
        return 1.2
    return 2.0


def _pacing_from_shots(total: float, shot_count: int) -> tuple[MusicMatchPacing, float]:
    average = total / shot_count if total > 0 and shot_count > 0 else 0.0
    if average and average <= 2.6:
        return MusicMatchPacing.FAST, average
    if average and average >= 4.5:
        return MusicMatchPacing.CALM, average
    return MusicMatchPacing.BALANCED, average




def _estimate_spoken_seconds(text: str, cue_limit: float) -> float:
    """Estimate active speech time instead of treating a whole shot as narrated.

    Historical audio versions did not persist raw TTS clip duration before padding, so
    this uses the actual approved cue text and a conservative conversational speech
    rate. Newer audio jobs can still be matched without falsely reporting 100% density
    simply because every shot contains a short line.
    """
    words = re.findall(r"[A-Za-z0-9']+", text or "")
    if not words or cue_limit <= 0:
        return 0.0
    punctuation_pauses = len(re.findall(r"[,;:!?]\s*|\.\s*", text or "")) * 0.12
    # ~2.45 words/s is a natural short-form narration pace. Add a small onset/offset
    # allowance, then clamp to the shot/cue duration so density can never exceed 100%.
    estimate = (len(words) / 2.45) + punctuation_pauses + 0.12
    return max(0.0, min(float(cue_limit), estimate))


def _narration_seconds_for_assembly(assembly_job_id: str, timeline: Iterable[object]) -> float:
    """Prefer the latest rendered cue text/timing, then fall back to assembly cues."""
    try:
        latest_audio = audio_finishing_job_store.latest_for_assembly_job(assembly_job_id)
    except Exception:
        latest_audio = None
    if latest_audio and latest_audio.result and latest_audio.result.voiceover_cues:
        seconds = 0.0
        for cue in latest_audio.result.voiceover_cues:
            text = (cue.text or "").strip()
            if text:
                seconds += _estimate_spoken_seconds(text, float(cue.duration_seconds or 0.0))
        if seconds > 0:
            return seconds

    seconds = 0.0
    for item in timeline:
        text = (getattr(item, "voiceover_or_dialogue", "") or "").strip()
        if text:
            seconds += _estimate_spoken_seconds(text, float(getattr(item, "output_duration_seconds", 0.0) or 0.0))
    return seconds

def _desired_energy(context: MusicMatchContext) -> float:
    base = {
        MusicMatchPacing.CALM: 1.2,
        MusicMatchPacing.BALANCED: 2.0,
        MusicMatchPacing.FAST: 2.8,
    }[context.pacing]
    # Dense narration benefits from a less assertive bed regardless of edit pace.
    if context.narration_density >= 0.70:
        base -= 0.75
    elif context.narration_density >= 0.45:
        base -= 0.4
    return max(0.8, min(3.0, base))


def _deterministic_score(context: MusicMatchContext, candidate: _Candidate) -> tuple[int, list[str]]:
    context_tokens = _tokens(
        " ".join(context.tone),
        context.audio_direction,
        context.narrative_arc,
        context.working_title,
    )
    candidate_tokens = _tokens(candidate.genre, " ".join(candidate.moods), candidate.description, candidate.title)
    overlap = len(context_tokens & candidate_tokens)
    overlap_score = min(18.0, overlap * 4.5)

    desired_energy = _desired_energy(context)
    energy_gap = abs(desired_energy - candidate.energy)
    energy_score = max(0.0, 18.0 - energy_gap * 9.0)

    narration_score = 10.0
    reasons: list[str] = []
    if context.narration_density >= 0.55:
        if candidate.energy <= 2.1:
            narration_score = 16.0
            reasons.append("Leaves useful space for the narration-heavy timeline.")
        elif candidate.energy >= 2.7:
            narration_score = 5.0
            reasons.append("Higher energy may need stronger ducking under dense narration.")
    elif context.narration_density <= 0.25 and candidate.energy >= 2.2:
        narration_score = 14.0
        reasons.append("The lighter narration load can support more musical movement.")

    if candidate.duration_seconds and context.total_duration_seconds > 0:
        if candidate.duration_seconds >= context.total_duration_seconds:
            reasons.append(
                f"Its {candidate.duration_seconds:.0f}s source duration comfortably covers the {context.total_duration_seconds:.0f}s master."
            )
        else:
            reasons.append(
                f"Its {candidate.duration_seconds:.0f}s source is shorter than the {context.total_duration_seconds:.0f}s master and will require looping."
            )

    metadata_score = 8.0 if candidate.moods or candidate.genre else 3.0
    score = 45.0 + overlap_score + energy_score + narration_score + metadata_score
    score = int(round(max(35.0, min(96.0, score))))

    if overlap:
        shared = sorted(context_tokens & candidate_tokens)[:3]
        reasons.insert(0, f"Matches approved direction cues: {', '.join(shared)}.")
    if not reasons:
        reasons.append("Energy and pacing are compatible with the approved edit rhythm.")
    if candidate.source != MusicSource.REVIVEAI and not candidate.moods and not candidate.genre:
        reasons.append("Limited mood metadata makes this match less certain; preview before choosing.")
    return score, reasons[:3]


class MusicMatchStore:
    def __init__(self, checkpoint_root: str):
        self._root = Path(checkpoint_root) / "music_match"
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._cache: TenantScopedDict[str, MusicMatchResult] = TenantScopedDict()

    def _path(self, assembly_job_id: str) -> Path:
        return tenant_scoped_root(self._root) / assembly_job_id / "latest.json"

    def save(self, result: MusicMatchResult) -> None:
        path = self._path(result.assembly_job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        with self._lock:
            temp.replace(path)
            self._cache[result.assembly_job_id] = result.model_copy(deep=True)

    def get_latest(self, assembly_job_id: str) -> Optional[MusicMatchResult]:
        with self._lock:
            cached = self._cache.get(assembly_job_id)
            if cached:
                return cached.model_copy(deep=True)
        path = self._path(assembly_job_id)
        if not path.exists():
            return None
        try:
            result = MusicMatchResult.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Could not load music match checkpoint for %s", assembly_job_id)
            return None
        with self._lock:
            self._cache[assembly_job_id] = result
        return result.model_copy(deep=True)


music_match_store = MusicMatchStore(get_settings().content_dna_checkpoint_dir)


class MusicMatchService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _context(self, assembly_job_id: str) -> tuple[object, object, MusicMatchContext]:
        try:
            assembly = final_assembly_job_store.get(assembly_job_id)
        except FinalAssemblyJobNotFoundError as exc:
            raise MusicMatchError("Final assembly job not found.") from exc
        if not assembly.result or assembly.result.review_status != FinalAssemblyReviewStatus.APPROVED:
            raise MusicMatchError("Approve the visual master before asking ReviveAI to match music.")
        try:
            production = production_brief_job_store.get(assembly.production_brief_job_id)
        except ProductionBriefJobNotFoundError as exc:
            raise MusicMatchError("The approved production brief is unavailable.") from exc
        if not production.result:
            raise MusicMatchError("The approved production brief is incomplete.")

        result = production.result
        total = float(assembly.result.total_duration_seconds or result.storyboard.estimated_duration_seconds or 0.0)
        timeline = assembly.result.timeline
        narration_seconds = _narration_seconds_for_assembly(assembly_job_id, timeline)
        density = (narration_seconds / total) if total > 0 else 0.0
        pacing, average = _pacing_from_shots(total, len(timeline))
        context = MusicMatchContext(
            working_title=result.creative_direction.working_title,
            tone=list(result.creative_direction.tone),
            audio_direction=result.publishing.audio_direction,
            narrative_arc=result.creative_direction.narrative_arc,
            total_duration_seconds=round(total, 3),
            narration_seconds=round(narration_seconds, 3),
            narration_density=round(max(0.0, min(1.0, density)), 3),
            shot_count=len(timeline),
            average_shot_seconds=round(average, 3),
            pacing=pacing,
        )
        return assembly, production, context

    def _candidates(self) -> list[_Candidate]:
        """Return only creator-saved, render-ready soundtrack candidates.

        ReviveAI no longer proposes procedural or external trending music during
        production. The reusable Soundtrack Library is the single source of truth.
        """
        candidates: list[_Candidate] = []
        try:
            youtube_tracks = youtube_audio_library.list(self.settings).tracks
        except YouTubeAudioLibraryError as exc:
            logger.warning("Music Match could not read Saved soundtrack catalog: %s", exc)
            youtube_tracks = []
        for track in youtube_tracks:
            if not track.render_ready:
                continue
            moods = _tag_list(track.mood)
            rights = (
                "Saved soundtrack · Creative Commons · attribution required"
                if track.license_type == YouTubeAudioLibraryLicenseType.CREATIVE_COMMONS or track.attribution_required
                else "Saved soundtrack · rights metadata saved"
            )
            candidates.append(_Candidate(
                candidate_key=f"youtube:{track.track_id}",
                source=MusicSource.YOUTUBE_AUDIO_LIBRARY,
                title=track.title,
                artist=track.artist,
                genre=track.genre,
                moods=moods,
                description=" ".join(filter(None, [track.genre, track.mood])),
                energy=_energy_from_metadata(track.genre, moods),
                rights_summary=rights,
                preview_available=track.preview_available,
                render_ready=track.render_ready,
                track_id=track.track_id,
                duration_seconds=track.duration_seconds,
            ))
        return candidates

    def _client(self):
        if not self.settings.google_cloud_project:
            return None
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            logger.warning("google-genai is unavailable; Music Match will use deterministic fallback scoring.")
            return None
        return (
            genai.Client(
                vertexai=True,
                project=self.settings.google_cloud_project,
                location=self.settings.google_cloud_location,
                http_options=types.HttpOptions(api_version="v1"),
            ),
            types,
        )

    @staticmethod
    def _sanitize_schema(value):
        if isinstance(value, list):
            return [MusicMatchService._sanitize_schema(item) for item in value]
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
                cleaned[key] = {name: MusicMatchService._sanitize_schema(child) for name, child in item.items()}
            elif key == "items" and isinstance(item, dict):
                cleaned[key] = MusicMatchService._sanitize_schema(item)
            elif key in {"prefixItems", "anyOf", "oneOf"} and isinstance(item, list):
                cleaned[key] = [MusicMatchService._sanitize_schema(child) for child in item]
            elif key == "additionalProperties" and isinstance(item, dict):
                cleaned[key] = MusicMatchService._sanitize_schema(item)
            else:
                cleaned[key] = item
        return cleaned

    async def _ai_rank(self, context: MusicMatchContext, candidates: list[_Candidate], deterministic: dict[str, tuple[int, list[str]]], *, production_id: str, channel_id: str) -> Optional[AiMusicMatchPack]:
        client_data = self._client()
        if client_data is None:
            return None
        client, types = client_data

        # Keep the prompt bounded while retaining every likely finalist. This is metadata only;
        # ReviveAI never uploads licensed audio to Gemini for ranking.
        shortlisted = sorted(candidates, key=lambda item: deterministic[item.candidate_key][0], reverse=True)[:30]
        candidate_lines = []
        for candidate in shortlisted:
            base_score = deterministic[candidate.candidate_key][0]
            candidate_lines.append({
                "candidate_key": candidate.candidate_key,
                "source": candidate.source.value,
                "title": candidate.title,
                "artist": candidate.artist,
                "genre": candidate.genre,
                "moods": list(candidate.moods),
                "description": candidate.description,
                "estimated_energy_1_to_3": round(candidate.energy, 2),
                "duration_seconds": candidate.duration_seconds,
                "deterministic_fit_score": base_score,
            })
        prompt = f"""
You are ReviveAI's music-fit assistant. Rank soundtrack candidates for an already-approved short-form video.

Do not predict views, virality, engagement, or commercial performance. Do not prefer a track merely because it is trending or popular. Rights clearance is already handled by ReviveAI and every candidate below is render-ready. Evaluate only creative compatibility: approved tone, narrative arc, edit pacing, narration density, duration, energy, mood, and how much room the music leaves for speech.

PROJECT CONTEXT
{json.dumps(context.model_dump(mode='json'), ensure_ascii=False, indent=2)}

CANDIDATES
{json.dumps(candidate_lines, ensure_ascii=False, indent=2)}

Return up to 8 strongest candidates. candidate_key must exactly match one supplied above. Score 0-100 means creative fit only. Give a concise fit_summary and 1-3 concrete reasons. Avoid generic praise.
""".strip()

        schema = self._sanitize_schema(AiMusicMatchPack.model_json_schema())
        last_error: Optional[Exception] = None
        for attempt in range(max(1, min(3, self.settings.content_dna_retry_attempts))):
            try:
                from uuid import uuid4
                from app.services.ai_review_budget import review_cost_reservation_usd
                from app.services.firestore_budget_service import FirestoreBudgetService
                from app.services.channel_autonomy_policy import channel_policy_store
                budget = FirestoreBudgetService()
                reserve_usd = review_cost_reservation_usd()
                budget.ensure_production_budget(
                    production_id, channel_id,
                    channel_policy_store.get(channel_id).max_total_production_cost_usd,
                )
                op_id = f"gemini_music_match_{uuid4().hex}"
                claim = budget.reserve(production_id, reserve_usd, op_id)
                if not claim.get("allowed"):
                    logger.warning("Music match budget denied; using deterministic scores: %s", claim.get("reason"))
                    return None
                # Never automatically retry when provider billing or reconciliation is uncertain.
                try:
                    response = await client.aio.models.generate_content(
                        model=self.settings.gemini_model,
                        contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction="Rank only supplied music candidates for creative fit. Return structured JSON only.",
                        temperature=0.18,
                        candidate_count=1,
                        response_mime_type="application/json",
                        response_json_schema=schema,
                        max_output_tokens=4000,
                    ),
                    )
                    budget.complete(op_id, reserve_usd)
                except Exception as uncertain_exc:
                    logger.warning("Music match provider outcome uncertain operation=%s; no retry: %s", op_id, uncertain_exc)
                    return None
                parsed = getattr(response, "parsed", None)
                if isinstance(parsed, AiMusicMatchPack):
                    return parsed
                if parsed is not None:
                    return AiMusicMatchPack.model_validate(parsed)
                text = getattr(response, "text", None)
                if not text:
                    raise ValueError("Gemini returned an empty Music Match response.")
                return AiMusicMatchPack.model_validate_json(text)
            except Exception as exc:
                last_error = exc
                logger.warning("Music Match Gemini ranking failed attempt %s: %s", attempt + 1, exc)
                if attempt + 1 < max(1, min(3, self.settings.content_dna_retry_attempts)):
                    await asyncio.sleep(0.75 * (2**attempt))
        logger.warning("Music Match is using deterministic fallback after Gemini failure: %s", last_error)
        return None

    async def generate(self, assembly_job_id: str) -> MusicMatchResult:
        assembly, production, context = self._context(assembly_job_id)
        candidates = self._candidates()
        if not candidates:
            raise MusicMatchError("No render-ready music candidates are available.")

        deterministic = {candidate.candidate_key: _deterministic_score(context, candidate) for candidate in candidates}
        ai_pack = await self._ai_rank(
            context, candidates, deterministic,
            production_id=production.job_id, channel_id=production.channel_id,
        )
        ai_by_key = {item.candidate_key: item for item in (ai_pack.recommendations if ai_pack else [])}
        candidate_by_key = {item.candidate_key: item for item in candidates}

        recommendations: list[MusicMatchRecommendation] = []
        for candidate in candidates:
            base_score, base_reasons = deterministic[candidate.candidate_key]
            ai_item = ai_by_key.get(candidate.candidate_key)
            if ai_item:
                # AI adds semantic judgment while the deterministic score anchors pacing/narration fit.
                score = int(round((ai_item.score * 0.72) + (base_score * 0.28)))
                fit_summary = ai_item.fit_summary.strip() or "Strong creative fit for the approved direction."
                reasons = [item.strip() for item in ai_item.reasons if item.strip()][:3] or base_reasons
            else:
                score = base_score
                if candidate.moods or candidate.genre:
                    fit_summary = f"Fits the {context.pacing.value.lower()} edit pace and the approved audio direction."
                elif candidate.source == MusicSource.YOUTUBE_AUDIO_LIBRARY:
                    fit_summary = (
                        f"Imported YouTube track with sparse mood tags; ranking leans on the {context.pacing.value.lower()} edit pace, "
                        f"≈{round(context.narration_density * 100)}% active narration, duration, and available title/artist metadata."
                    )
                elif candidate.source == MusicSource.TRENDING_LICENSED:
                    fit_summary = (
                        f"Rights-cleared track with limited creative tags; ranking leans on pacing, active narration, duration, and catalog metadata."
                    )
                else:
                    fit_summary = "Usable match based on pacing and available metadata; preview before choosing."
                reasons = base_reasons
            recommendations.append(MusicMatchRecommendation(
                rank=1,
                candidate_key=candidate.candidate_key,
                source=candidate.source,
                title=candidate.title,
                artist=candidate.artist,
                score=max(0, min(100, score)),
                fit_summary=fit_summary,
                reasons=reasons[:3],
                rights_summary=candidate.rights_summary,
                preview_available=candidate.preview_available,
                render_ready=candidate.render_ready,
                preset=candidate.preset,
                track_id=candidate.track_id,
                genre=candidate.genre,
                moods=list(candidate.moods),
                duration_seconds=candidate.duration_seconds,
            ))

        recommendations.sort(key=lambda item: (-item.score, item.title.lower(), item.candidate_key))
        recommendations = recommendations[:8]
        for index, recommendation in enumerate(recommendations, start=1):
            recommendation.rank = index

        result = MusicMatchResult(
            assembly_job_id=assembly.job_id,
            production_brief_job_id=assembly.production_brief_job_id,
            generated_at=datetime.now(timezone.utc),
            model=self.settings.gemini_model if ai_pack else "deterministic-fallback",
            context=context,
            evaluated_candidates=len(candidates),
            recommendations=recommendations,
        )
        music_match_store.save(result)
        return result


music_match_service = MusicMatchService(get_settings())
