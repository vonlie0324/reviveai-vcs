from __future__ import annotations

import asyncio
import json
import math
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from app.core.config import Settings
from app.models.content_dna import ContentDnaResult, EvidenceMetrics, EvidenceVideoRef, GroupInsight, CharacterInsight
from app.models.recovery import (
    AiGapSuggestionBatch,
    AiRecommendationSuggestionBatch,
    AiRevivalSuggestionBatch,
    ArchiveMatch,
    CanonicalRecoveryIdea,
    ChannelOperatingMode,
    ChannelStrategyContext,
    ContentGapOpportunity,
    EvidenceStrength,
    GapOpportunityStrength,
    NextContentRecommendation,
    RecoveryJobStage,
    RecoveryResult,
    RecoverySignal,
    RevivalOpportunity,
)
from app.models.youtube import AnalysisResult, VideoSnapshot
from app.services.content_dna_metrics_service import performance_tier


class RecoveryError(RuntimeError):
    pass


RecoveryStageCallback = Callable[[RecoveryJobStage, str, int, int, Dict], None]


RECOVERY_SYSTEM = """
You are ReviveAI's channel strategy assistant for both active and dormant digital channels.

Use only the supplied evidence-linked Content DNA and public archive context.
Rules:
- Treat historical Content DNA as channel memory, not a timeless prescription.
- Respect the supplied operating mode: DISCOVER, SUSTAIN, RECOVER, or REVIVE.
- For active channels, protect current identity and sustainable production; do not force a comeback narrative.
- For dormant channels, reduce confidence in time-sensitive historical execution patterns and favor controlled re-validation.
- Historical performance is association, not causation. Never promise views, virality, or audience growth.
- Preserve durable identity signals while allowing formats, hooks, packaging, cadence, and topics to evolve.
- Do not invent current-market trends. If current external market evidence was not supplied, explicitly treat recommendations as archive-grounded hypotheses that need fresh validation.
- Keep outputs concise, diverse, and feasible.
- Evidence ingredients must be semantically central to the proposed idea.
""".strip()


class RecoveryService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.gemini_calls = 0
        self._intelligence_channel_id = None

    async def build(
        self,
        analysis: AnalysisResult,
        dna: ContentDnaResult,
        on_stage: RecoveryStageCallback,
    ) -> RecoveryResult:
        self._intelligence_channel_id = analysis.channel.channel_id
        self._validate_configuration()
        client, types = self._create_genai_client()
        total_steps = 5
        strategy = self._diagnose_channel_strategy(analysis)

        on_stage(
            RecoveryJobStage.PREPARING_SIGNALS,
            "Ranking evidence-backed recovery signals",
            0,
            total_steps,
            {"gemini_calls": self.gemini_calls, "step_label": "Prepare recovery signals"},
        )
        signals = self._build_signal_pool(dna)
        top_signals = signals[:10]
        archive_index = self._archive_index(analysis, dna)
        revival_candidates = self._revival_candidates(analysis, dna)

        on_stage(
            RecoveryJobStage.DISCOVERING_GAPS,
            "Finding adjacent content opportunities",
            1,
            total_steps,
            {
                "gemini_calls": self.gemini_calls,
                "step_label": "Discover content gaps",
                "signals_considered": len(signals),
                "archive_videos": len(analysis.videos),
            },
        )
        gap_suggestions = await self._generate_gaps(client, types, analysis, dna, top_signals, strategy)
        gaps = self._materialize_gaps(gap_suggestions, signals, archive_index, analysis)

        on_stage(
            RecoveryJobStage.FINDING_REVIVALS,
            "Identifying archive concepts worth revisiting",
            2,
            total_steps,
            {
                "gemini_calls": self.gemini_calls,
                "step_label": "Find revival opportunities",
                "revival_candidates": len(revival_candidates),
            },
        )
        revival_suggestions = await self._generate_revivals(
            client, types, analysis, dna, top_signals, revival_candidates, strategy
        )
        revivals = self._materialize_revivals(
            revival_suggestions, signals, revival_candidates, analysis, dna
        )

        on_stage(
            RecoveryJobStage.BUILDING_RECOMMENDATIONS,
            "Building evidence-backed next-content directions",
            3,
            total_steps,
            {
                "gemini_calls": self.gemini_calls,
                "step_label": "Build next-content recommendations",
                "validated_gaps": len(gaps),
                "validated_revivals": len(revivals),
            },
        )
        recommendation_suggestions = await self._generate_recommendations(
            client,
            types,
            analysis,
            dna,
            top_signals,
            gaps,
            revivals,
            strategy,
        )
        recommendation_candidates = self._materialize_recommendations(
            recommendation_suggestions, signals, archive_index, analysis
        )

        # M1D.4: normalize equivalent ideas across independent Gemini passes before
        # ranking. This keeps title, concept, novelty and evidence identical wherever
        # the same creative direction appears.
        canonical_ideas = self._canonicalize_recovery_ideas(gaps, recommendation_candidates)
        # M1D.4: re-ground every canonical idea against all available Content DNA signals.
        # A strong signal only survives if it is semantically relevant to the proposed idea.
        self._reground_canonical_ideas(
            canonical_ideas,
            gaps,
            recommendation_candidates,
            signals,
        )
        recommendation_candidates = self._deduplicate_recommendations(recommendation_candidates)
        recommendations = self._diversity_rank_recommendations(recommendation_candidates, limit=5)
        canonical_ideas = self._finalize_canonical_ideas(canonical_ideas, gaps, recommendations)

        on_stage(
            RecoveryJobStage.VALIDATING_EVIDENCE,
            "Validating archive similarity and evidence links",
            4,
            total_steps,
            {
                "gemini_calls": self.gemini_calls,
                "step_label": "Validate evidence",
                "content_gaps": len(gaps),
                "revival_opportunities": len(revivals),
                "recommendations": len(recommendations),
                "canonical_ideas": len(canonical_ideas),
                "diversity_balanced": True,
            },
        )

        return RecoveryResult(
            generated_at=datetime.now(timezone.utc),
            strategy=strategy,
            model=self.settings.gemini_model,
            gemini_calls=self.gemini_calls,
            top_signals=top_signals[:8],
            canonical_ideas=canonical_ideas,
            content_gaps=gaps[:6],
            revival_opportunities=revivals[:5],
            recommendations=recommendations[:5],
        )

    @staticmethod
    def _diagnose_channel_strategy(analysis: AnalysisResult) -> ChannelStrategyContext:
        summary = analysis.summary
        metrics = analysis.metrics
        video_count = len(analysis.videos)
        gap = summary.days_since_latest_upload
        cadence = metrics.cadence
        median_gap = cadence.median_active_day_gap_days
        recency_ratio = metrics.recency.age_normalized_ratio

        if video_count < 6:
            return ChannelStrategyContext(
                mode=ChannelOperatingMode.DISCOVER, label="Discovery",
                reason="The analyzed archive is too small to let historical patterns dominate strategy.",
                days_since_latest_upload=gap, historical_evidence_weight=0.25, fresh_evidence_priority=0.75,
                historical_confidence_label="Low / learning",
                guidance="Use Content DNA as a starting identity hypothesis and deliberately test several content territories.",
            )

        dormant_threshold = max(90, int((median_gap or 30) * 3))
        if gap is not None and gap >= dormant_threshold:
            age_factor = min(1.0, gap / 730.0)
            history_weight = max(0.20, round(0.50 - (0.25 * age_factor), 2))
            return ChannelStrategyContext(
                mode=ChannelOperatingMode.REVIVE, label="Revival",
                reason=f"The latest analyzed upload is {gap} days old, beyond the channel-aware dormancy threshold of {dormant_threshold} days.",
                days_since_latest_upload=gap, historical_evidence_weight=history_weight, fresh_evidence_priority=round(1-history_weight, 2),
                historical_confidence_label="Aged / re-validation required",
                guidance="Preserve durable identity signals, but re-test topics, formats, hooks, packaging, and cadence before scaling them.",
            )

        if recency_ratio is not None and recency_ratio < 0.70:
            return ChannelStrategyContext(
                mode=ChannelOperatingMode.RECOVER, label="Recovery",
                reason=f"Recent age-normalized public performance is {recency_ratio:.2f}x the older comparison baseline.",
                days_since_latest_upload=gap, historical_evidence_weight=0.55, fresh_evidence_priority=0.45,
                historical_confidence_label="Moderate / recent correction prioritized",
                guidance="Protect recognizable channel identity while testing corrective variations and learning from recent evidence.",
            )

        return ChannelStrategyContext(
            mode=ChannelOperatingMode.SUSTAIN, label="Sustainable growth",
            reason="The channel appears active enough that recent evidence should remain central to ongoing content operations.",
            days_since_latest_upload=gap, historical_evidence_weight=0.70, fresh_evidence_priority=0.30,
            historical_confidence_label="Current / continuously monitored",
            guidance="Protect what is currently working, maintain sustainable cadence, and reserve capacity for controlled exploration.",
        )

    @staticmethod
    def _strategy_prompt(strategy: ChannelStrategyContext) -> str:
        return (
            f"Operating mode: {strategy.mode.value} ({strategy.label})\n"
            f"Diagnosis: {strategy.reason}\n"
            f"Historical evidence weight: {strategy.historical_evidence_weight:.0%}\n"
            f"Fresh-evidence priority: {strategy.fresh_evidence_priority:.0%}\n"
            f"Strategy guidance: {strategy.guidance}\n"
            "Current external market/trend intelligence: not supplied in this pass. Do not present archive evidence as proof of today's market demand."
        )

    def _validate_configuration(self) -> None:
        if not self.settings.google_cloud_project:
            raise RecoveryError(
                "GOOGLE_CLOUD_PROJECT is not configured. Add it to backend/.env and authenticate with Application Default Credentials."
            )
        if not self.settings.gemini_model:
            raise RecoveryError("GEMINI_MODEL is not configured.")

    def _create_genai_client(self):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RecoveryError("google-genai is not installed. Run: pip install -r requirements.txt") from exc

        try:
            client = genai.Client(
                vertexai=True,
                project=self.settings.google_cloud_project,
                location=self.settings.google_cloud_location,
                http_options=types.HttpOptions(api_version="v1"),
            )
        except Exception as exc:
            raise RecoveryError(f"Could not initialize Vertex AI: {exc}") from exc
        return client, types

    def _build_signal_pool(self, dna: ContentDnaResult) -> List[RecoverySignal]:
        raw: List[RecoverySignal] = []
        for item in dna.themes:
            raw.append(self._signal("theme", item.name, item.description, item.evidence))
        for item in dna.characters:
            raw.append(self._signal("character", item.name, item.description, item.evidence))
        for item in dna.story_patterns:
            raw.append(self._signal("story_pattern", item.name, item.description, item.evidence))
        for item in dna.visual_patterns:
            raw.append(self._signal("visual_pattern", item.name, item.description, item.evidence))

        useful = [item for item in raw if item.evidence.video_count >= 3 and item.evidence.relative_to_channel_median is not None]
        useful.sort(key=self._signal_rank, reverse=True)
        return useful or raw

    @staticmethod
    def _signal(kind: str, name: str, description: str, evidence: EvidenceMetrics) -> RecoverySignal:
        return RecoverySignal(kind=kind, name=name, description=description, evidence=evidence)

    @staticmethod
    def _signal_rank(signal: RecoverySignal) -> float:
        relative = signal.evidence.relative_to_channel_median or 0.0
        count = max(1, signal.evidence.video_count)
        # Support-aware ranking: high ratios matter, but a 2-video spike should not dominate.
        support = min(2.2, math.log2(count + 1) / 2.0)
        return min(relative, 6.0) * support

    @staticmethod
    def _signal_catalog(signals: Sequence[RecoverySignal], limit: int = 12) -> str:
        rows = []
        for signal in signals[:limit]:
            ev = signal.evidence
            rows.append(
                f"- {signal.name} [{signal.kind}]: {ev.video_count} videos; "
                f"{(ev.relative_to_channel_median or 0):.1f}x channel median; "
                f"{ev.sample_strength}; {ev.performance_signal}. {signal.description}"
            )
        return "\n".join(rows)

    @staticmethod
    def _archive_concepts(dna: ContentDnaResult, limit: int = 70) -> str:
        rows = []
        for item in dna.video_classifications[:limit]:
            labels = list(dict.fromkeys(item.themes + item.story_patterns + item.visual_patterns))[:6]
            chars = [character.name for character in item.characters if character.name][:3]
            extras = ", ".join(labels + chars)
            rows.append(f"- {item.video_id}: {item.summary}" + (f" | {extras}" if extras else ""))
        return "\n".join(rows)

    async def _generate_gaps(self, client, types, analysis, dna, signals, strategy):
        prompt = f"""
Channel: {analysis.channel.title}
{self._strategy_prompt(strategy)}
Channel identity: {dna.identity.summary}
Content promise: {dna.identity.content_promise}
Dominant format: {dna.identity.dominant_format}

Evidence-linked channel signals:
{self._signal_catalog(signals)}

Compact archive concepts already represented:
{self._archive_concepts(dna)}

Propose 8 adjacent content gaps worth exploring. A gap is a concept that fits the channel identity but appears materially different from the supplied archive concepts.
For evidence_ingredients, use exact signal names from the evidence-linked list above. Use 1-4 ingredients per item.
Do not claim a concept is definitely new; the backend will independently validate similarity.
""".strip()
        return await self._structured_call(
            client=client,
            types=types,
            prompt=prompt,
            schema=AiGapSuggestionBatch,
            max_output_tokens=6500,
            failure_message="Gemini could not finish the compact content-gap pass after multiple attempts.",
        )

    async def _generate_revivals(self, client, types, analysis, dna, signals, candidates, strategy):
        candidate_lines = []
        for video, classification, age_days, relative in candidates:
            candidate_lines.append(
                f"- {video.video_id}: {video.title} | {video.view_count or 0} public views | "
                f"{relative:.1f}x channel median | age {age_days if age_days is not None else 'unknown'} days | "
                f"summary: {classification.summary}"
            )
        prompt = f"""
Channel: {analysis.channel.title}
{self._strategy_prompt(strategy)}
Channel identity: {dna.identity.summary}

Evidence-linked channel signals:
{self._signal_catalog(signals)}

Eligible archive sources for revival:
{chr(10).join(candidate_lines)}

Select up to 5 source videos that have a defensible, evidence-linked reason to revisit now. Use historical-association language only; do not call any source proven, popular, successful, winning, best-performing, or high-performing. For each, propose a fresh revival angle rather than simply remaking the same video.
source_video_id must exactly match one of the IDs above.
For evidence_ingredients, use exact signal names from the evidence-linked list when relevant.
""".strip()
        return await self._structured_call(
            client=client,
            types=types,
            prompt=prompt,
            schema=AiRevivalSuggestionBatch,
            max_output_tokens=5000,
            failure_message="Gemini could not finish the compact archive-revival pass after multiple attempts.",
        )

    async def _generate_recommendations(self, client, types, analysis, dna, signals, gaps, revivals, strategy):
        gap_lines = [f"- {item.title}: {item.concept} ({item.novelty_label})" for item in gaps[:6]]
        revival_lines = [
            f"- Revive {item.source_video.title}: {item.revival_angle}" for item in revivals[:5]
        ]
        prompt = f"""
Channel: {analysis.channel.title}
{self._strategy_prompt(strategy)}
Identity: {dna.identity.summary}
Content promise: {dna.identity.content_promise}
Dominant format: {dna.identity.dominant_format}
Language/style: {dna.identity.language_style}

Evidence-linked channel signals:
{self._signal_catalog(signals)}

Validated adjacent opportunities:
{chr(10).join(gap_lines) if gap_lines else '- none validated strongly enough'}

Archive revival directions:
{chr(10).join(revival_lines) if revival_lines else '- none selected'}

Create 10 candidate next-content directions for the creator. Match the supplied operating mode: sustain healthy active channels, correct declining active channels, re-validate dormant channels, and explore broadly when history is insufficient. They should be specific and feasible within the channel's established short-form identity. Intentionally cover multiple strategy lanes when the evidence supports them—for example different characters, themes, milestones, professional-role scenarios, visual settings, or character-introduction formats. Avoid returning many cosmetic variations of one dominant theme.
Use historical-association language only; do not call any signal popular, proven, successful, winning, best-performing, or high-performing.
Use evidence_ingredients to name only exact signals that are semantically relevant to the specific direction. A signal must explain the proposed character, setting, activity, story structure, or visual treatment; do not include a globally strong signal that is unrelated to the idea. Do not claim guaranteed performance.
recommended_characters must use exact character signal names when a recurring character is recommended; otherwise return an empty list.
The backend will independently deduplicate near-equivalent concepts and apply diversity-aware ranking; do not try to predict final ranks.
""".strip()
        return await self._structured_call(
            client=client,
            types=types,
            prompt=prompt,
            schema=AiRecommendationSuggestionBatch,
            max_output_tokens=8000,
            failure_message="Gemini could not finish the compact next-content recommendation pass after multiple attempts.",
        )

    async def _structured_call(self, *, client, types, prompt, schema, max_output_tokens, failure_message):
        attempts = max(1, self.settings.content_dna_retry_attempts)
        last_error: Optional[Exception] = None
        for attempt in range(attempts):
            try:
                self.gemini_calls += 1
                from app.services.channel_intelligence_budget import ChannelIntelligenceBudget
                response = await ChannelIntelligenceBudget().generate(
                    channel_id=self._intelligence_channel_id, category="recovery_intelligence", client=client,
                    model=self.settings.gemini_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=RECOVERY_SYSTEM,
                        temperature=0.35,
                        response_mime_type="application/json",
                        response_schema=schema,
                        max_output_tokens=max_output_tokens,
                    ),
                )
                parsed = getattr(response, "parsed", None)
                if isinstance(parsed, schema):
                    return parsed
                if parsed is not None:
                    return schema.model_validate(parsed)
                text = getattr(response, "text", None)
                if not text:
                    raise ValueError("Gemini returned an empty structured response.")
                return schema.model_validate_json(text)
            except Exception as exc:
                from app.services.channel_intelligence_budget import IntelligenceProviderOutcomeUncertain
                if isinstance(exc, IntelligenceProviderOutcomeUncertain):
                    raise
                last_error = exc
                if attempt + 1 < attempts:
                    await asyncio.sleep(1.2 * (2**attempt))
        raise RecoveryError(failure_message) from last_error

    def _materialize_gaps(self, batch, signals, archive_index, analysis) -> List[ContentGapOpportunity]:
        items: List[ContentGapOpportunity] = []
        for index, suggestion in enumerate(batch.items):
            concept_text = f"{suggestion.title} {suggestion.concept} {suggestion.why_it_fits}"
            novelty_score, closest = self._novelty(concept_text, archive_index, analysis)
            label = self._novelty_label(novelty_score)
            preferred = self._link_signals(suggestion.evidence_ingredients, signals)
            linked = self._ground_signals_for_idea(
                concept_text,
                signals,
                preferred=preferred,
                recommended_characters=[],
                limit=4,
            )
            strength = self._evidence_strength(linked)
            items.append(
                ContentGapOpportunity(
                    gap_id=f"gap_{index + 1}",
                    title=suggestion.title.strip(),
                    concept=suggestion.concept.strip(),
                    why_it_fits=self._safe_claim_text(suggestion.why_it_fits),
                    novelty_label=label,
                    novelty_score=round(novelty_score, 2),
                    evidence_strength=strength,
                    opportunity_strength=self._gap_opportunity_strength(strength, label),
                    evidence_signals=linked,
                    closest_archive_matches=closest[:3],
                    caution=(
                        "No close semantic match was detected in the analyzed public archive; this is not proof the creator has never explored the idea elsewhere."
                        if label == "No close match detected"
                        else "This direction overlaps with existing archive concepts, so differentiation should be deliberate."
                    ),
                )
            )
        items.sort(key=lambda item: (item.novelty_score, self._linked_strength_score(item.evidence_signals)), reverse=True)
        return items

    def _materialize_revivals(self, batch, signals, candidates, analysis, dna) -> List[RevivalOpportunity]:
        candidate_map = {video.video_id: (video, cls, age, relative) for video, cls, age, relative in candidates}
        items: List[RevivalOpportunity] = []
        for index, suggestion in enumerate(batch.items):
            source = candidate_map.get(suggestion.source_video_id)
            if source is None:
                continue
            video, classification, age_days, _relative = source
            linked = self._link_signals(suggestion.evidence_ingredients, signals)
            if not linked:
                linked = self._signals_for_classification(classification, signals)[:3]
            items.append(
                RevivalOpportunity(
                    revival_id=f"revival_{index + 1}",
                    source_video=self._evidence_ref(video, analysis),
                    source_age_days=age_days,
                    source_summary=classification.summary,
                    revival_angle=suggestion.revival_angle.strip(),
                    why_revive=self._safe_claim_text(suggestion.why_revive),
                    evidence_strength=self._evidence_strength(linked),
                    evidence_signals=linked[:4],
                )
            )
        return items

    def _materialize_recommendations(self, batch, signals, archive_index, analysis) -> List[NextContentRecommendation]:
        items: List[NextContentRecommendation] = []
        character_names = {signal.name.casefold(): signal.name for signal in signals if signal.kind == "character"}
        for index, suggestion in enumerate(batch.items):
            novelty_score, closest = self._novelty(
                f"{suggestion.title} {suggestion.concept} {suggestion.hook}", archive_index, analysis
            )
            characters = []
            for raw in suggestion.recommended_characters:
                canonical = character_names.get(raw.strip().casefold())
                if canonical and canonical not in characters:
                    characters.append(canonical)
            preferred = self._link_signals(suggestion.evidence_ingredients, signals)
            idea_text = " ".join(
                [suggestion.title, suggestion.concept, suggestion.hook, suggestion.why_this_fits]
            )
            linked = self._ground_signals_for_idea(
                idea_text,
                signals,
                preferred=preferred,
                recommended_characters=characters,
                limit=5,
            )
            items.append(
                NextContentRecommendation(
                    rank=index + 1,
                    recommendation_id=f"recommendation_{index + 1}",
                    title=suggestion.title.strip(),
                    concept=suggestion.concept.strip(),
                    hook=suggestion.hook.strip(),
                    format=suggestion.format.strip() or "Short-form video",
                    why_this_fits=self._safe_claim_text(suggestion.why_this_fits),
                    recommended_characters=characters,
                    evidence_strength=self._evidence_strength(linked),
                    evidence_signals=linked,
                    novelty_label=self._novelty_label(novelty_score),
                    novelty_score=round(novelty_score, 2),
                    closest_archive_matches=closest[:3],
                )
            )
        # Keep Gemini's intended order but re-number after dropping invalid items.
        for rank, item in enumerate(items, start=1):
            item.rank = rank
        return items

    def _revival_candidates(self, analysis: AnalysisResult, dna: ContentDnaResult):
        classification_map = {item.video_id: item for item in dna.video_classifications}
        channel_median = analysis.metrics.views.median or 0
        snapshot = analysis.summary.analysis_snapshot_at
        rows = []
        for video in analysis.videos:
            classification = classification_map.get(video.video_id)
            if classification is None or video.view_count is None:
                continue
            tier = performance_tier(video, analysis)
            if tier not in {"strong", "exceptional"}:
                continue
            age_days = None
            if snapshot and video.published_at:
                age_days = max(0, (snapshot.date() - video.published_at.date()).days)
            if age_days is not None and age_days < 30:
                continue
            relative = (video.view_count / channel_median) if channel_median else 0
            rows.append((video, classification, age_days, relative))
        rows.sort(key=lambda row: (row[3], row[0].view_count or 0), reverse=True)
        return rows[:12]

    @staticmethod
    def _archive_index(analysis: AnalysisResult, dna: ContentDnaResult):
        video_map = {video.video_id: video for video in analysis.videos}
        rows = []
        for cls in dna.video_classifications:
            video = video_map.get(cls.video_id)
            if video is None:
                continue
            characters = []
            for item in cls.characters:
                characters.extend([item.name or "", item.role or ""])
            text = " ".join(
                [
                    video.title,
                    cls.summary,
                    " ".join(cls.themes),
                    " ".join(cls.story_patterns),
                    " ".join(cls.visual_patterns),
                    " ".join(characters),
                    cls.setting or "",
                ]
            )
            rows.append((video, text))
        return rows

    def _novelty(self, candidate: str, archive_index, analysis: AnalysisResult) -> Tuple[float, List[ArchiveMatch]]:
        scored: List[Tuple[float, VideoSnapshot]] = []
        for video, archive_text in archive_index:
            score = self._similarity(candidate, archive_text)
            scored.append((score, video))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        max_similarity = scored[0][0] if scored else 0.0
        novelty = max(0.0, min(1.0, 1.0 - max_similarity))
        matches = [
            ArchiveMatch(
                video=self._evidence_ref(video, analysis),
                similarity=round(score, 2),
                similarity_label=self._similarity_label(score),
            )
            for score, video in scored[:3]
        ]
        return novelty, matches

    @classmethod
    def _similarity(cls, left: str, right: str) -> float:
        a = cls._normalized_tokens(left)
        b = cls._normalized_tokens(right)
        if not a or not b:
            return 0.0
        set_a, set_b = set(a), set(b)
        jaccard = len(set_a & set_b) / max(1, len(set_a | set_b))
        seq = SequenceMatcher(None, " ".join(a), " ".join(b)).ratio()
        containment = len(set_a & set_b) / max(1, min(len(set_a), len(set_b)))
        return max(jaccard, 0.65 * seq + 0.35 * containment)

    @staticmethod
    def _normalized_tokens(value: str) -> List[str]:
        generic = {
            "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "from",
            "dog", "dogs", "pet", "pets", "cute", "short", "shorts", "video", "pawshionista",
            "meet", "our", "this", "that", "is", "are", "at", "as", "their", "your",
        }
        tokens = re.findall(r"[a-z0-9]+", (value or "").casefold())
        return [token for token in tokens if token not in generic and len(token) > 1]

    @staticmethod
    def _novelty_label(score: float) -> str:
        if score >= 0.7:
            return "No close match detected"
        if score >= 0.5:
            return "Adjacent to archive"
        return "Possible overlap"

    @staticmethod
    def _similarity_label(score: float) -> str:
        if score >= 0.55:
            return "Close archive match"
        if score >= 0.35:
            return "Related archive concept"
        return "Loose similarity"

    @staticmethod
    def _link_signals(names: Iterable[str], signals: Sequence[RecoverySignal]) -> List[RecoverySignal]:
        lookup = {signal.name.casefold(): signal for signal in signals}
        linked = []
        for raw in names:
            signal = lookup.get((raw or "").strip().casefold())
            if signal is not None and all(existing.name != signal.name for existing in linked):
                linked.append(signal)
        return linked

    @staticmethod
    def _signals_for_classification(classification, signals: Sequence[RecoverySignal]) -> List[RecoverySignal]:
        labels = {value.casefold() for value in classification.themes + classification.story_patterns + classification.visual_patterns}
        labels.update({item.name.casefold() for item in classification.characters if item.name})
        return [signal for signal in signals if signal.name.casefold() in labels]

    @classmethod
    def _ground_signals_for_idea(
        cls,
        idea_text: str,
        signals: Sequence[RecoverySignal],
        *,
        preferred: Sequence[RecoverySignal] = (),
        recommended_characters: Sequence[str] = (),
        limit: int = 5,
    ) -> List[RecoverySignal]:
        """Return only evidence that is semantically relevant to a proposed idea.

        Gemini may nominate globally strong signals that are not actually about the proposed
        concept. M1D.4 treats those nominations as candidates, not proof. The backend scores
        semantic relevance first, then uses historical evidence strength only as a secondary
        ordering signal.
        """
        preferred_keys = {(item.kind.casefold(), item.name.casefold()) for item in preferred}
        scored: List[Tuple[float, float, RecoverySignal]] = []
        for signal in signals:
            relevance = cls._signal_relevance_score(
                signal,
                idea_text,
                recommended_characters=recommended_characters,
            )
            if relevance < 0.28:
                continue
            key = (signal.kind.casefold(), signal.name.casefold())
            preferred_bonus = 0.12 if key in preferred_keys else 0.0
            evidence_score = min(8.0, cls._signal_rank(signal))
            scored.append((relevance + preferred_bonus, evidence_score, signal))

        scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
        result: List[RecoverySignal] = []
        seen = set()
        for _relevance, _evidence, signal in scored:
            key = (signal.kind.casefold(), signal.name.casefold())
            if key in seen:
                continue
            result.append(signal)
            seen.add(key)
            if len(result) >= limit:
                break
        return result

    @classmethod
    def _signal_relevance_score(
        cls,
        signal: RecoverySignal,
        idea_text: str,
        *,
        recommended_characters: Sequence[str] = (),
    ) -> float:
        idea_tokens = set(cls._semantic_tokens(idea_text))
        name_tokens = set(cls._semantic_tokens(signal.name))
        description_tokens = set(cls._semantic_tokens(signal.description))
        if not idea_tokens or not name_tokens:
            return 0.0

        if signal.kind == "character":
            canonical = signal.name.casefold()
            if canonical in {name.casefold() for name in recommended_characters}:
                return 1.0
            if name_tokens & idea_tokens:
                return 0.95
            return 0.0

        name_intersection = idea_tokens & name_tokens
        name_containment = len(name_intersection) / max(1, len(name_tokens))
        name_jaccard = len(name_intersection) / max(1, len(idea_tokens | name_tokens))
        lexical_name = min(1.0, 0.78 * name_containment + 0.22 * name_jaccard)

        # Semantic-family matching is intentionally based on the signal name, not its
        # explanatory description. This prevents a kitchen signal from matching an unrelated
        # wedding merely because its description happens to mention a chef/professional role.
        family_overlap = cls._semantic_family_overlap(idea_tokens, name_tokens)

        description_intersection = idea_tokens & description_tokens
        description_containment = (
            len(description_intersection) / max(1, len(description_tokens))
            if description_tokens
            else 0.0
        )
        # Description-only matches are supporting context and cannot cross the relevance
        # threshold by themselves.
        lexical_description = min(0.24, 0.4 * description_containment)

        return min(1.0, max(lexical_name, family_overlap, lexical_description))

    @staticmethod
    def _semantic_tokens(value: str) -> List[str]:
        generic = {
            "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "from",
            "dog", "dogs", "pet", "pets", "cute", "short", "shorts", "video", "pawshionista",
            "meet", "our", "this", "that", "is", "are", "at", "as", "their", "your", "tiny",
            "miniature", "content", "channel", "story", "stories", "scenario", "scenarios",
            "theme", "themes", "pattern", "patterns", "featuring", "themed", "setting", "settings",
        }
        raw = re.findall(r"[a-z0-9]+", (value or "").casefold())
        normalized: List[str] = []
        for token in raw:
            if token in generic or len(token) <= 1:
                continue
            # Lightweight normalization is intentionally conservative; it helps match
            # celebration/celebrations and role/roles without fuzzy-merging proper names.
            if token.endswith("ies") and len(token) > 4:
                token = token[:-3] + "y"
            elif token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
                token = token[:-1]
            normalized.append(token)
        return normalized

    @staticmethod
    def _semantic_family_overlap(idea_tokens: set[str], signal_tokens: set[str]) -> float:
        families = [
            {"culinary", "cooking", "kitchen", "chef", "bake", "baker", "pastry", "food", "dining", "meal", "pizza", "sushi", "cake", "restaurant", "breakfast"},
            {"celebration", "celebrate", "party", "birthday", "wedding", "graduation", "ceremony", "milestone", "festive", "retirement"},
            {"job", "professional", "profession", "workplace", "work", "worker", "occupation", "uniform", "roleplay", "role", "officiant", "chef", "critic", "conductor", "curator", "reception", "receptionist", "teacher", "doctor", "nurse", "cashier", "butler", "service"},
            {"fashion", "runway", "model", "outfit", "costume", "clothing", "stylish", "designer"},
            {"travel", "train", "conductor", "flight", "pilot", "cabin", "safari", "journey", "adventure"},
            {"medical", "doctor", "nurse", "medic", "rescue", "clinic", "spa", "health"},
            {"school", "graduation", "student", "teacher", "classroom", "lesson", "diploma", "education"},
            {"art", "museum", "gallery", "curator", "painting", "cultural", "culture"},
            {"hotel", "reception", "receptionist", "hospitality", "service", "butler"},
        ]
        for family in families:
            if idea_tokens & family and signal_tokens & family:
                return 0.72
        return 0.0

    @classmethod
    def _reground_canonical_ideas(
        cls,
        canonical_ideas: Sequence[CanonicalRecoveryIdea],
        gaps: Sequence[ContentGapOpportunity],
        recommendations: Sequence[NextContentRecommendation],
        signals: Sequence[RecoverySignal],
    ) -> None:
        members_by_id: Dict[str, List[object]] = {}
        for item in [*gaps, *recommendations]:
            if item.canonical_idea_id:
                members_by_id.setdefault(item.canonical_idea_id, []).append(item)

        idea_by_id = {item.idea_id: item for item in canonical_ideas}
        for idea_id, members in members_by_id.items():
            idea = idea_by_id.get(idea_id)
            if idea is None:
                continue
            extra_text = []
            recommended_characters: List[str] = []
            preferred: List[RecoverySignal] = []
            for member in members:
                extra_text.extend(
                    [
                        getattr(member, "title", ""),
                        getattr(member, "concept", ""),
                        getattr(member, "why_it_fits", ""),
                        getattr(member, "hook", ""),
                    ]
                )
                recommended_characters.extend(getattr(member, "recommended_characters", []) or [])
                preferred.extend(getattr(member, "evidence_signals", []) or [])
            idea_text = " ".join([idea.canonical_title, idea.concept, *extra_text])
            grounded = cls._ground_signals_for_idea(
                idea_text,
                signals,
                preferred=preferred,
                recommended_characters=list(dict.fromkeys(recommended_characters)),
                limit=5,
            )
            strength = cls._evidence_strength(grounded)
            lanes = cls._strategy_lanes_for_members(members, grounded)
            idea.evidence_signals = grounded
            idea.evidence_strength = strength
            idea.strategy_lanes = lanes
            for member in members:
                member.evidence_strength = strength
                member.evidence_signals = grounded[:4] if isinstance(member, ContentGapOpportunity) else grounded
                grounded_rationale = cls._grounded_rationale(grounded)
                if isinstance(member, ContentGapOpportunity):
                    member.opportunity_strength = cls._gap_opportunity_strength(strength, member.novelty_label)
                    member.why_it_fits = grounded_rationale
                else:
                    member.strategy_lanes = lanes
                    member.why_this_fits = grounded_rationale

    @staticmethod
    def _grounded_rationale(signals: Sequence[RecoverySignal]) -> str:
        if not signals:
            return (
                "This direction fits the channel identity, but ReviveAI found limited idea-specific "
                "historical evidence. Treat it as an exploratory creative hypothesis."
            )
        names = [signal.name for signal in signals[:3]]
        if len(names) == 1:
            joined = names[0]
        elif len(names) == 2:
            joined = f"{names[0]} and {names[1]}"
        else:
            joined = f"{names[0]}, {names[1]}, and {names[2]}"
        return (
            f"This direction is grounded in {joined}, which are semantically relevant Content DNA "
            "signals with traceable historical evidence in the analyzed archive."
        )

    @classmethod
    def _evidence_strength(cls, signals: Sequence[RecoverySignal]) -> EvidenceStrength:
        if not signals:
            return EvidenceStrength.EXPLORATORY
        strong = sum(
            1
            for signal in signals
            if (signal.evidence.relative_to_channel_median or 0) >= 1.5
            and signal.evidence.video_count >= 6
        )
        positive = sum(1 for signal in signals if (signal.evidence.relative_to_channel_median or 0) >= 1.0)
        if strong >= 2:
            return EvidenceStrength.STRONG
        if strong >= 1 or positive >= 2:
            return EvidenceStrength.SUPPORTED
        return EvidenceStrength.EXPLORATORY

    @staticmethod
    def _gap_opportunity_strength(
        evidence_strength: EvidenceStrength, novelty_label: str
    ) -> GapOpportunityStrength:
        if evidence_strength == EvidenceStrength.STRONG and novelty_label == "No close match detected":
            return GapOpportunityStrength.EVIDENCE_BACKED_GAP
        if evidence_strength in {EvidenceStrength.STRONG, EvidenceStrength.SUPPORTED}:
            return GapOpportunityStrength.ADJACENT_OPPORTUNITY
        return GapOpportunityStrength.EMERGING_OPPORTUNITY

    @classmethod
    def _canonicalize_recovery_ideas(
        cls,
        gaps: Sequence[ContentGapOpportunity],
        recommendations: Sequence[NextContentRecommendation],
    ) -> List[CanonicalRecoveryIdea]:
        """Create one deterministic identity for semantically equivalent recovery ideas.

        Gap discovery and recommendation generation are intentionally separate Gemini passes.
        This pass prevents small wording differences (for example "Outdoor Pizza Party" vs
        "Backyard Pizza Party") from becoming two apparently different ideas with conflicting
        evidence. Recommendations are used as the canonical wording when a cross-surface match
        exists because they are the action-oriented surface used by the creator.
        """
        groups: List[Dict[str, object]] = []

        def place(kind: str, item) -> None:
            best_group = None
            best_score = 0.0
            for group in groups:
                representative = group["representative"]
                score = cls._idea_similarity(item, representative)
                if score > best_score:
                    best_group, best_score = group, score
            if best_group is not None and best_score >= 0.68:
                best_group[kind].append(item)
                # Prefer an actual next-direction as the canonical wording.
                if kind == "recommendations" and best_group["representative_kind"] != "recommendations":
                    best_group["representative"] = item
                    best_group["representative_kind"] = kind
                return
            groups.append(
                {
                    "representative": item,
                    "representative_kind": kind,
                    "gaps": [item] if kind == "gaps" else [],
                    "recommendations": [item] if kind == "recommendations" else [],
                }
            )

        # Recommendations first gives final-plan wording precedence.
        for item in recommendations:
            place("recommendations", item)
        for item in gaps:
            place("gaps", item)

        canonical: List[CanonicalRecoveryIdea] = []
        for index, group in enumerate(groups, start=1):
            recs: List[NextContentRecommendation] = group["recommendations"]  # type: ignore[assignment]
            group_gaps: List[ContentGapOpportunity] = group["gaps"]  # type: ignore[assignment]
            representative = cls._best_group_representative(recs, group_gaps)
            members = [*recs, *group_gaps]
            combined_signals = cls._merge_signals(*(item.evidence_signals for item in members))
            strength = cls._evidence_strength(combined_signals)
            novelty_score = min((item.novelty_score for item in members), default=1.0)
            novelty_label = cls._novelty_label(novelty_score)
            matches = cls._merge_matches(*(item.closest_archive_matches for item in members))
            title = representative.title.strip()
            concept = representative.concept.strip()
            slug = re.sub(r"[^a-z0-9]+", "_", title.casefold()).strip("_")[:42] or f"idea_{index}"
            idea_id = f"idea_{index:02d}_{slug}"
            lanes = cls._strategy_lanes_for_members(members, combined_signals)

            for item in members:
                item.title = title
                item.concept = concept
                item.evidence_strength = strength
                item.evidence_signals = combined_signals[:5]
                item.novelty_score = round(novelty_score, 2)
                item.novelty_label = novelty_label
                item.closest_archive_matches = matches[:3]
                item.canonical_idea_id = idea_id
                if isinstance(item, ContentGapOpportunity):
                    item.opportunity_strength = cls._gap_opportunity_strength(strength, novelty_label)
                else:
                    item.strategy_lanes = lanes

            canonical.append(
                CanonicalRecoveryIdea(
                    idea_id=idea_id,
                    canonical_title=title,
                    concept=concept,
                    evidence_strength=strength,
                    evidence_signals=combined_signals[:5],
                    novelty_label=novelty_label,
                    novelty_score=round(novelty_score, 2),
                    closest_archive_matches=matches[:3],
                    roles=[],
                    strategy_lanes=lanes,
                )
            )
        return canonical

    @classmethod
    def _best_group_representative(
        cls,
        recommendations: Sequence[NextContentRecommendation],
        gaps: Sequence[ContentGapOpportunity],
    ):
        if recommendations:
            return max(recommendations, key=cls._recommendation_base_score)
        return max(gaps, key=lambda item: cls._linked_strength_score(item.evidence_signals) + item.novelty_score)

    @classmethod
    def _idea_similarity(cls, left, right) -> float:
        title_score = cls._similarity(left.title, right.title)
        concept_score = cls._similarity(
            f"{left.title} {left.concept}",
            f"{right.title} {right.concept}",
        )
        left_signals = {(s.kind.casefold(), s.name.casefold()) for s in left.evidence_signals}
        right_signals = {(s.kind.casefold(), s.name.casefold()) for s in right.evidence_signals}
        signal_overlap = 0.0
        if left_signals and right_signals:
            signal_overlap = len(left_signals & right_signals) / max(1, len(left_signals | right_signals))
        # A high title match is the strongest duplicate signal. Signal overlap helps bridge
        # small wording changes without collapsing every idea that happens to be culinary.
        return max(title_score, 0.72 * concept_score + 0.28 * signal_overlap)

    @staticmethod
    def _merge_signals(*signal_groups: Sequence[RecoverySignal]) -> List[RecoverySignal]:
        merged: List[RecoverySignal] = []
        seen = set()
        for group in signal_groups:
            for signal in group:
                key = (signal.kind.casefold(), signal.name.casefold())
                if key not in seen:
                    merged.append(signal)
                    seen.add(key)
        merged.sort(
            key=lambda signal: (
                -((signal.evidence.relative_to_channel_median or 0.0) * math.log2(signal.evidence.video_count + 1)),
                signal.kind,
                signal.name.casefold(),
            )
        )
        return merged

    @staticmethod
    def _merge_matches(*match_groups: Sequence[ArchiveMatch]) -> List[ArchiveMatch]:
        best_by_video: Dict[str, ArchiveMatch] = {}
        for group in match_groups:
            for match in group:
                existing = best_by_video.get(match.video.video_id)
                if existing is None or match.similarity > existing.similarity:
                    best_by_video[match.video.video_id] = match
        return sorted(best_by_video.values(), key=lambda item: item.similarity, reverse=True)

    @classmethod
    def _deduplicate_recommendations(
        cls, recommendations: Sequence[NextContentRecommendation]
    ) -> List[NextContentRecommendation]:
        by_idea: Dict[str, NextContentRecommendation] = {}
        ungrouped: List[NextContentRecommendation] = []
        for item in recommendations:
            key = item.canonical_idea_id
            if key:
                current = by_idea.get(key)
                if current is None or cls._recommendation_base_score(item) > cls._recommendation_base_score(current):
                    by_idea[key] = item
            else:
                # Defensive fallback if a caller uses the helper independently.
                duplicate_index = next(
                    (i for i, existing in enumerate(ungrouped) if cls._idea_similarity(item, existing) >= 0.72),
                    None,
                )
                if duplicate_index is None:
                    ungrouped.append(item)
                elif cls._recommendation_base_score(item) > cls._recommendation_base_score(ungrouped[duplicate_index]):
                    ungrouped[duplicate_index] = item
        return [*by_idea.values(), *ungrouped]

    @classmethod
    def _diversity_rank_recommendations(
        cls,
        recommendations: Sequence[NextContentRecommendation],
        limit: int = 5,
    ) -> List[NextContentRecommendation]:
        """Rank evidence-fit ideas while enforcing hard diversity caps.

        M1D.4 keeps the soft overlap penalty from M1D.3, then adds deterministic caps:
        no recurring character, dominant theme, or primary non-character strategy lane may
        occupy more than two slots in the final recovery plan. If the candidate pool cannot
        fill all requested slots without breaking a cap, ReviveAI returns fewer ideas rather
        than pretending that five near-duplicates constitute a diverse strategy.
        """
        remaining = list(recommendations)
        selected: List[NextContentRecommendation] = []
        character_counts: Dict[str, int] = {}
        theme_counts: Dict[str, int] = {}
        lane_counts: Dict[str, int] = {}

        while remaining and len(selected) < limit:
            eligible = [
                item
                for item in remaining
                if cls._within_diversity_caps(item, character_counts, theme_counts, lane_counts)
            ]
            if not eligible:
                break

            best_item = None
            best_adjusted = float("-inf")
            best_overlap = 0.0
            for item in eligible:
                base = cls._recommendation_base_score(item)
                overlap = max((cls._recommendation_overlap(item, chosen) for chosen in selected), default=0.0)
                adjusted = base - (5.0 * overlap)
                if adjusted > best_adjusted:
                    best_item, best_adjusted, best_overlap = item, adjusted, overlap
            assert best_item is not None
            selected.append(best_item)
            remaining.remove(best_item)
            cls._increment_diversity_counts(best_item, character_counts, theme_counts, lane_counts)

            if len(selected) == 1:
                best_item.diversity_note = "Highest evidence-fit candidate before diversity balancing."
            elif best_overlap < 0.35:
                best_item.diversity_note = "Selected to add a distinct strategy lane while staying within diversity caps."
            else:
                best_item.diversity_note = "Selected after balancing evidence fit, overlap, and diversity caps."

        for rank, item in enumerate(selected, start=1):
            item.rank = rank
            if not item.strategy_lanes:
                item.strategy_lanes = cls._strategy_lanes_for_members([item], item.evidence_signals)
        return selected

    @classmethod
    def _within_diversity_caps(
        cls,
        item: NextContentRecommendation,
        character_counts: Dict[str, int],
        theme_counts: Dict[str, int],
        lane_counts: Dict[str, int],
        cap: int = 2,
    ) -> bool:
        for character in cls._recommendation_characters(item):
            if character_counts.get(character, 0) >= cap:
                return False
        theme = cls._dominant_theme_key(item)
        if theme and theme_counts.get(theme, 0) >= cap:
            return False
        lane = cls._primary_strategy_key(item)
        if lane and lane_counts.get(lane, 0) >= cap:
            return False
        return True

    @classmethod
    def _increment_diversity_counts(
        cls,
        item: NextContentRecommendation,
        character_counts: Dict[str, int],
        theme_counts: Dict[str, int],
        lane_counts: Dict[str, int],
    ) -> None:
        for character in cls._recommendation_characters(item):
            character_counts[character] = character_counts.get(character, 0) + 1
        theme = cls._dominant_theme_key(item)
        if theme:
            theme_counts[theme] = theme_counts.get(theme, 0) + 1
        lane = cls._primary_strategy_key(item)
        if lane:
            lane_counts[lane] = lane_counts.get(lane, 0) + 1

    @staticmethod
    def _recommendation_characters(item: NextContentRecommendation) -> set[str]:
        values = {name.casefold() for name in item.recommended_characters if name}
        values.update(
            signal.name.casefold()
            for signal in item.evidence_signals
            if signal.kind == "character" and signal.name
        )
        return values

    @classmethod
    def _dominant_theme_key(cls, item: NextContentRecommendation) -> Optional[str]:
        themes = [signal for signal in item.evidence_signals if signal.kind == "theme"]
        if not themes:
            return None
        best = max(themes, key=cls._signal_rank)
        return best.name.casefold()

    @classmethod
    def _primary_strategy_key(cls, item: NextContentRecommendation) -> Optional[str]:
        non_character = [signal for signal in item.evidence_signals if signal.kind != "character"]
        if not non_character:
            return None
        best = max(non_character, key=cls._signal_rank)
        return f"{best.kind.casefold()}::{best.name.casefold()}"

    @classmethod
    def _recommendation_base_score(cls, item: NextContentRecommendation) -> float:
        strength_weight = {
            EvidenceStrength.STRONG: 4.0,
            EvidenceStrength.SUPPORTED: 2.5,
            EvidenceStrength.EXPLORATORY: 1.0,
        }[item.evidence_strength]
        evidence = min(8.0, cls._linked_strength_score(item.evidence_signals) / 4.0)
        novelty = max(0.0, min(1.0, item.novelty_score)) * 1.5
        # Keep Gemini's original ordering as a very small tie-breaker only.
        order_bonus = max(0.0, 0.25 - (max(1, item.rank) - 1) * 0.03)
        return strength_weight + evidence + novelty + order_bonus

    @classmethod
    def _recommendation_overlap(
        cls, left: NextContentRecommendation, right: NextContentRecommendation
    ) -> float:
        semantic = cls._similarity(f"{left.title} {left.concept}", f"{right.title} {right.concept}")
        left_signals = {(s.kind.casefold(), s.name.casefold()) for s in left.evidence_signals}
        right_signals = {(s.kind.casefold(), s.name.casefold()) for s in right.evidence_signals}
        signal_jaccard = (
            len(left_signals & right_signals) / max(1, len(left_signals | right_signals))
            if left_signals and right_signals
            else 0.0
        )
        left_chars = {name.casefold() for name in left.recommended_characters}
        right_chars = {name.casefold() for name in right.recommended_characters}
        character_overlap = 1.0 if left_chars and right_chars and left_chars & right_chars else 0.0
        return min(1.0, 0.45 * signal_jaccard + 0.40 * semantic + 0.15 * character_overlap)

    @staticmethod
    def _strategy_lanes_for_members(members, signals: Sequence[RecoverySignal]) -> List[str]:
        lanes: List[str] = []
        for item in members:
            for character in getattr(item, "recommended_characters", []) or []:
                label = f"Character · {character}"
                if label not in lanes:
                    lanes.append(label)
        kind_labels = {
            "theme": "Theme",
            "story_pattern": "Story",
            "visual_pattern": "Visual",
            "character": "Character",
        }
        for signal in signals:
            label = f"{kind_labels.get(signal.kind, 'Signal')} · {signal.name}"
            if label not in lanes:
                lanes.append(label)
            if len(lanes) >= 3:
                break
        return lanes[:3]

    @classmethod
    def _finalize_canonical_ideas(
        cls,
        canonical_ideas: Sequence[CanonicalRecoveryIdea],
        gaps: Sequence[ContentGapOpportunity],
        recommendations: Sequence[NextContentRecommendation],
    ) -> List[CanonicalRecoveryIdea]:
        selected_ids = {item.canonical_idea_id for item in recommendations if item.canonical_idea_id}
        gap_ids = {item.canonical_idea_id for item in gaps if item.canonical_idea_id}
        for gap in gaps:
            gap.selected_for_recovery_plan = bool(gap.canonical_idea_id in selected_ids)
        output: List[CanonicalRecoveryIdea] = []
        for idea in canonical_ideas:
            roles: List[str] = []
            if idea.idea_id in gap_ids:
                roles.append("CONTENT_GAP")
            if idea.idea_id in selected_ids:
                roles.append("RECOVERY_PLAN")
            if not roles:
                continue
            idea.roles = roles
            output.append(idea)
        return output

    @classmethod
    def _canonicalize_shared_strengths(
        cls,
        gaps: Sequence[ContentGapOpportunity],
        recommendations: Sequence[NextContentRecommendation],
    ) -> None:
        """Give the same creative direction one deterministic strength everywhere it appears.

        Gap discovery and next-content generation are separate Gemini passes, so an identical
        title can arrive with slightly different ingredient lists. We union the exact linked
        evidence for matching titles, calculate strength once, and reuse it in both surfaces.
        """
        gaps_by_key = {cls._concept_key(item.title): item for item in gaps}
        for recommendation in recommendations:
            gap = gaps_by_key.get(cls._concept_key(recommendation.title))
            if gap is None:
                continue
            combined: List[RecoverySignal] = []
            seen = set()
            for signal in [*gap.evidence_signals, *recommendation.evidence_signals]:
                key = (signal.kind.casefold(), signal.name.casefold())
                if key not in seen:
                    combined.append(signal)
                    seen.add(key)
            canonical = cls._evidence_strength(combined)
            gap.evidence_strength = canonical
            recommendation.evidence_strength = canonical
            # Keep the evidence shown in every surface aligned with the canonical badge.
            gap.evidence_signals = combined[:4]
            recommendation.evidence_signals = combined[:5]
            gap.opportunity_strength = cls._gap_opportunity_strength(canonical, gap.novelty_label)

    @staticmethod
    def _concept_key(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", (value or "").casefold()))

    @staticmethod
    def _safe_claim_text(value: str) -> str:
        """Remove causal/overconfident performance language from Gemini rationale text."""
        text = (value or "").strip()
        replacements = [
            (r"\bhighly successful\b", "historically strong"),
            (r"\bbest[- ]performing\b", "historically above-baseline"),
            (r"\bhigh[- ]performing\b", "historically above-baseline"),
            (r"\bsuccessful\b", "historically strong"),
            (r"\bproven\b", "historically supported"),
            (r"\bpopularity\b", "historically above-baseline performance"),
            (r"\bwinning\b", "historically supported"),
        ]
        for pattern, replacement in replacements:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text

    @staticmethod
    def _linked_strength_score(signals: Sequence[RecoverySignal]) -> float:
        return sum((signal.evidence.relative_to_channel_median or 0) * math.log2(signal.evidence.video_count + 1) for signal in signals)

    @staticmethod
    def _evidence_ref(video: VideoSnapshot, analysis: AnalysisResult) -> EvidenceVideoRef:
        thumbnail = video.thumbnails.medium or video.thumbnails.high or video.thumbnails.default
        return EvidenceVideoRef(
            video_id=video.video_id,
            title=video.title,
            views=video.view_count,
            performance_tier=performance_tier(video, analysis),
            thumbnail_url=thumbnail,
            watch_url=video.watch_url,
        )
