from datetime import datetime, timezone

from app.core.config import Settings
from app.models.content_dna import ChannelIdentity, ContentDnaResult
from app.models.production_brief import CreativeDirection, ProductionBriefCheckpoint, ProductionFidelityMode, ProductionIdentity
from app.models.recovery import EvidenceStrength, NextContentRecommendation
from app.models.youtube import AnalysisResult, ChannelSnapshot, IngestionSummary, ThumbnailSet
from app.services.channel_metrics_service import ChannelMetricsService
from app.services.production_brief_service import ProductionBriefService


def _analysis():
    now = datetime(2026, 9, 22, tzinfo=timezone.utc)
    return AnalysisResult(
        channel=ChannelSnapshot(
            channel_id="UCtest",
            title="Pawshionista",
            thumbnails=ThumbnailSet(),
            uploads_playlist_id="UUtest",
            channel_url="https://youtube.com/channel/UCtest",
        ),
        summary=IngestionSummary(retrieved_videos=0, analysis_snapshot_at=now),
        metrics=ChannelMetricsService().build([], now=now),
        videos=[],
    )


def _dna():
    return ContentDnaResult(
        generated_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
        model="gemini-test",
        videos_classified=1,
        visuals_analyzed=1,
        metadata_only_videos=0,
        unclassified_videos=0,
        gemini_calls=1,
        identity=ChannelIdentity(
            summary="Pet roleplay",
            primary_niche="Pets",
            content_promise="Short pet stories",
            dominant_format="Shorts",
            language_style="Playful",
            confidence=0.9,
        ),
    )


def _recommendation():
    return NextContentRecommendation(
        rank=1,
        recommendation_id="recommendation_1",
        title="Dior's Wedding",
        concept="Dior officiates a tiny wedding.",
        hook="Dior opens a tiny book.",
        format="Short-form video",
        why_this_fits="Evidence backed",
        evidence_strength=EvidenceStrength.STRONG,
        novelty_label="No close match detected",
        novelty_score=0.8,
    )


def test_production_checkpoint_round_trip(tmp_path):
    settings = Settings(content_dna_checkpoint_dir=str(tmp_path))
    service = ProductionBriefService(settings)
    key = service._checkpoint_key(_analysis(), _dna(), _recommendation(), ProductionFidelityMode.STANDARD)
    checkpoint = ProductionBriefCheckpoint(
        creative_direction=CreativeDirection(
            working_title="Tiny Wedding",
            creative_objective="Create a short",
            one_sentence_promise="A tiny ceremony",
            opening_hook="Open the book",
            narrative_arc="Hook to payoff",
            target_duration_seconds=15,
            format="Short-form video",
            production_identity=ProductionIdentity(
                character_name="Dior", identity_source="existing_character", species_or_subject="small dog",
                appearance="fluffy cream coat", wardrobe="formal tuxedo", personality=["calm"],
                primary_prop="tiny ceremony book", setting_anchor="miniature chapel",
                lighting_style="warm soft lighting", anatomy_rule="Use Dior's canine paws; no visible human hand or arm."
            ),
            character_direction="Keep Dior consistent",
            setting="Miniature chapel",
        )
    )
    service._save_checkpoint(key, checkpoint)
    loaded = service._load_checkpoint(key)
    assert loaded.creative_direction is not None
    assert loaded.creative_direction.working_title == "Tiny Wedding"
    assert service._checkpoint_stage(loaded) == "creative-direction"
