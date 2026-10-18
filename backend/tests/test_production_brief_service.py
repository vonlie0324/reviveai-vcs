from datetime import datetime, timezone

from app.core.config import Settings
from app.models.content_dna import (
    ChannelIdentity,
    ContentDnaResult,
    EvidenceMetrics,
    VoiceToneInsight,
)
from app.models.production_brief import ProductionFidelityMode, ProductionIdentity, PublishingPackage, StoryboardPlan, StoryboardShot
from app.models.recovery import EvidenceStrength, NextContentRecommendation, RecoverySignal
from app.models.youtube import (
    AnalysisResult,
    ChannelSnapshot,
    IngestionSummary,
    ThumbnailSet,
)
from app.services.channel_metrics_service import ChannelMetricsService
from app.services.production_brief_service import ProductionBriefService


def make_analysis() -> AnalysisResult:
    now = datetime(2026, 9, 22, tzinfo=timezone.utc)
    channel = ChannelSnapshot(
        channel_id="UCtest",
        title="Pawshionista",
        thumbnails=ThumbnailSet(),
        uploads_playlist_id="UUtest",
        channel_url="https://youtube.com/channel/UCtest",
    )
    return AnalysisResult(
        channel=channel,
        summary=IngestionSummary(retrieved_videos=0, analysis_snapshot_at=now),
        metrics=ChannelMetricsService().build([], now=now),
        videos=[],
    )


def make_dna() -> ContentDnaResult:
    return ContentDnaResult(
        generated_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
        model="gemini-test",
        videos_classified=89,
        visuals_analyzed=89,
        metadata_only_videos=0,
        unclassified_videos=0,
        gemini_calls=5,
        identity=ChannelIdentity(
            summary="Cute dogs in miniature roleplay scenarios.",
            primary_niche="Pet roleplay",
            content_promise="Short visual stories with dressed-up pets.",
            dominant_format="Short-form video",
            language_style="Playful and concise",
            confidence=0.9,
        ),
        voice_tone=[
            VoiceToneInsight(label="Playful", explanation="Lighthearted", confidence=0.9),
            VoiceToneInsight(label="Wholesome", explanation="Family-friendly", confidence=0.8),
        ],
    )


def make_recommendation() -> NextContentRecommendation:
    signal = RecoverySignal(
        kind="character",
        name="Dior",
        description="Recurring dog character in professional roles.",
        evidence=EvidenceMetrics(video_count=6, relative_to_channel_median=2.9),
    )
    return NextContentRecommendation(
        rank=1,
        recommendation_id="recommendation_1",
        title="Dior's Whimsical Wedding Chapel",
        concept="Dior acts as a tiny wedding officiant.",
        hook="Dior opens a tiny ceremony book.",
        format="Short-form video",
        why_this_fits="Grounded in Dior and professional-role signals.",
        recommended_characters=["Dior"],
        evidence_strength=EvidenceStrength.STRONG,
        evidence_signals=[signal],
        novelty_label="No close match detected",
        novelty_score=0.8,
        strategy_lanes=["Character · Dior", "Story · Pets Performing Human Jobs"],
    )


def make_identity() -> ProductionIdentity:
    return ProductionIdentity(
        character_name="Dior",
        identity_source="existing_character",
        species_or_subject="small dog",
        appearance="fluffy cream coat",
        wardrobe="formal miniature tuxedo",
        personality=["calm", "helpful"],
        primary_prop="tiny ceremony book",
        setting_anchor="miniature wedding chapel",
        lighting_style="warm soft commercial lighting",
        anatomy_rule="Use Dior's own canine paws; no visible human hand or arm may stand in for Dior.",
    )


def test_creative_context_excludes_performance_values():
    service = ProductionBriefService(Settings())
    contract = service._build_direction_fidelity_contract(make_recommendation())
    context = service._creative_context(make_analysis(), make_dna(), make_recommendation(), contract, ProductionFidelityMode.STANDARD)

    assert "2.9" not in context["evidence_labels"]
    assert "median" not in context["evidence_labels"].lower()
    assert "Dior" in context["evidence_labels"]
    assert context["recommended_characters"] == "Dior"


def test_hashtags_are_normalized_and_deduplicated():
    values = ProductionBriefService._normalize_hashtags(["Pawshionista", "#Pets", "pets", "Tiny Wedding"])
    assert values == ["#Pawshionista", "#Pets", "#TinyWedding"]


def test_storyboard_shots_are_renumbered_and_duration_clamped():
    shots = [
        StoryboardShot(
            shot_number=8,
            duration_seconds=0.2,
            purpose="Hook",
            visual_action="Dior opens a tiny book.",
            camera_direction="Close-up",
            generation_prompt="Prompt 1",
        ),
        StoryboardShot(
            shot_number=3,
            duration_seconds=19.9,
            purpose="Payoff",
            visual_action="Dior smiles.",
            camera_direction="Medium shot",
            generation_prompt="Prompt 2",
        ),
    ]
    result = ProductionBriefService._normalize_shots(shots)
    assert [shot.shot_number for shot in result] == [1, 2]
    assert result[0].duration_seconds == 0.5
    assert result[1].duration_seconds == 19.9


def test_storyboard_outline_and_prompt_pack_are_merged_by_shot_number():
    from app.models.production_brief import AiShotPrompt, AiStoryboardOutline, AiStoryboardOutlineShot, AiStoryboardPromptPack

    outline = AiStoryboardOutline(
        shots=[
            AiStoryboardOutlineShot(
                shot_number=1,
                duration_seconds=3,
                purpose="Hook",
                visual_action="Dior opens a tiny ceremony book.",
                camera_direction="Close-up",
            ),
            AiStoryboardOutlineShot(
                shot_number=2,
                duration_seconds=4,
                purpose="Setup",
                visual_action="Dior stands behind the altar.",
                camera_direction="Medium shot",
            ),
            AiStoryboardOutlineShot(
                shot_number=3,
                duration_seconds=4,
                purpose="Action",
                visual_action="Dior gestures toward two plush guests.",
                camera_direction="Wide shot",
            ),
            AiStoryboardOutlineShot(
                shot_number=4,
                duration_seconds=4,
                purpose="Payoff",
                visual_action="Dior closes the book and smiles.",
                camera_direction="Close-up",
            ),
        ]
    )
    prompts = AiStoryboardPromptPack(
        prompts=[
            AiShotPrompt(shot_number=1, generation_prompt="Prompt one"),
            AiShotPrompt(shot_number=2, generation_prompt="Prompt two"),
            AiShotPrompt(shot_number=3, generation_prompt="Prompt three"),
            AiShotPrompt(shot_number=4, generation_prompt="Prompt four"),
        ]
    )

    result = ProductionBriefService._merge_storyboard(outline, prompts, identity=make_identity())
    assert len(result.shots) == 4
    assert result.shots[0].generation_prompt.endswith("SHOT: Prompt one")
    assert result.shots[3].generation_prompt.endswith("SHOT: Prompt four")
    assert "CONTINUITY LOCK" in result.shots[0].generation_prompt
    assert result.estimated_duration_seconds == 15


def test_storyboard_merge_uses_safe_fallback_if_prompt_number_is_missing():
    from app.models.production_brief import AiShotPrompt, AiStoryboardOutline, AiStoryboardOutlineShot, AiStoryboardPromptPack

    outline = AiStoryboardOutline(
        shots=[
            AiStoryboardOutlineShot(shot_number=1, duration_seconds=2, purpose="A", visual_action="Action A", camera_direction="Close"),
            AiStoryboardOutlineShot(shot_number=2, duration_seconds=2, purpose="B", visual_action="Action B", camera_direction="Wide"),
            AiStoryboardOutlineShot(shot_number=3, duration_seconds=2, purpose="C", visual_action="Action C", camera_direction="Medium"),
            AiStoryboardOutlineShot(shot_number=4, duration_seconds=2, purpose="D", visual_action="Action D", camera_direction="Close"),
        ]
    )
    prompts = AiStoryboardPromptPack(
        prompts=[
            AiShotPrompt(shot_number=1, generation_prompt="Prompt A"),
            AiShotPrompt(shot_number=2, generation_prompt="Prompt B"),
            AiShotPrompt(shot_number=3, generation_prompt="Prompt C"),
            AiShotPrompt(shot_number=7, generation_prompt="Wrong number"),
        ]
    )

    result = ProductionBriefService._merge_storyboard(outline, prompts, identity=make_identity())
    assert "Action D" in result.shots[3].generation_prompt
    assert "continuity" in result.shots[3].generation_prompt.lower()


def test_storyboard_prompts_receive_canonical_identity_lock():
    from app.models.production_brief import AiShotPrompt, AiStoryboardOutline, AiStoryboardOutlineShot, AiStoryboardPromptPack

    outline = AiStoryboardOutline(
        shots=[
            AiStoryboardOutlineShot(shot_number=i, duration_seconds=3, purpose=f"P{i}", visual_action=f"Action {i}", camera_direction="Close")
            for i in range(1, 5)
        ]
    )
    prompts = AiStoryboardPromptPack(
        prompts=[AiShotPrompt(shot_number=i, generation_prompt=f"Prompt {i}") for i in range(1, 5)]
    )
    result = ProductionBriefService._merge_storyboard(outline, prompts, identity=make_identity())
    assert all("CONTINUITY LOCK" in shot.generation_prompt for shot in result.shots)
    assert all("Dior" in shot.generation_prompt for shot in result.shots)
    assert all("no visible human hand" in shot.generation_prompt.lower() for shot in result.shots)


def test_consistency_report_passes_when_identity_is_reused():
    identity = make_identity()
    creative = __import__("app.models.production_brief", fromlist=["CreativeDirection"]).CreativeDirection(
        working_title="Tiny Wedding",
        creative_objective="Create a short",
        one_sentence_promise="A tiny ceremony",
        opening_hook="Dior opens the ceremony book with a canine paw.",
        narrative_arc="Hook to payoff",
        target_duration_seconds=12,
        format="Short-form vertical video",
        production_identity=identity,
        character_direction="Keep Dior consistent",
        setting="miniature wedding chapel",
    )
    storyboard = StoryboardPlan(
        shots=[
            StoryboardShot(
                shot_number=i, duration_seconds=3, purpose="Beat", visual_action="Dior performs the ceremony with canine paws.",
                camera_direction="Medium", generation_prompt=ProductionBriefService._apply_identity_lock_to_prompt("Dior performs the ceremony.", identity)
            ) for i in range(1,5)
        ],
        estimated_duration_seconds=12,
    )
    publishing = PublishingPackage(
        youtube_title="Dior's Tiny Wedding", description="Dior hosts a tiny ceremony.", social_caption="Dior is ready.",
        thumbnail_concept="Dior at the altar", audio_direction="Whimsical bells", accessibility_alt_text="Dior at a miniature chapel"
    )
    report = ProductionBriefService._build_consistency_report(
        creative=creative, storyboard=storyboard, publishing=publishing,
        publishing_identity_echo=(identity.character_name, identity.setting_anchor, identity.primary_prop),
    )
    assert report.status == "PASS"
    assert not report.blocking_issues


def test_consistency_report_blocks_visible_human_hand_conflict():
    identity = make_identity()
    creative = __import__("app.models.production_brief", fromlist=["CreativeDirection"]).CreativeDirection(
        working_title="Tiny Wedding", creative_objective="Create a short", one_sentence_promise="A tiny ceremony",
        opening_hook="A visible human hand turns Dior's ceremony book.", narrative_arc="Hook to payoff",
        target_duration_seconds=12, format="Short-form vertical video", production_identity=identity,
        character_direction="Keep Dior consistent", setting="miniature wedding chapel",
    )
    storyboard = StoryboardPlan(
        shots=[StoryboardShot(shot_number=i, duration_seconds=3, purpose="Beat", visual_action="Dior stands at the altar.", camera_direction="Medium", generation_prompt=ProductionBriefService._apply_identity_lock_to_prompt("Dior stands at the altar.", identity)) for i in range(1,5)],
        estimated_duration_seconds=12,
    )
    publishing = PublishingPackage(youtube_title="Dior's Tiny Wedding", description="Dior hosts a tiny ceremony.", social_caption="Dior is ready.", thumbnail_concept="Dior at the altar", audio_direction="Whimsical bells", accessibility_alt_text="Dior at a miniature chapel")
    report = ProductionBriefService._build_consistency_report(
        creative=creative, storyboard=storyboard, publishing=publishing,
        publishing_identity_echo=(identity.character_name, identity.setting_anchor, identity.primary_prop),
    )
    assert report.status == "REVIEW_REQUIRED"
    assert any("human hand" in item.lower() for item in report.blocking_issues)


def test_storyboard_outline_schema_avoids_unsupported_exclusive_minimum():
    from app.models.production_brief import AiStoryboardOutline
    import json

    schema_text = json.dumps(AiStoryboardOutline.model_json_schema())
    assert 'exclusiveMinimum' not in schema_text
    assert '"minimum": 0.5' in schema_text


def _walk_schema_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_schema_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_schema_keys(child)


def test_gemini_json_schema_sanitizes_unsupported_pydantic_keywords():
    from pydantic import BaseModel, Field
    from app.services.production_brief_service import ProductionBriefService

    class ConstrainedItem(BaseModel):
        value: float = Field(gt=0, lt=20)
        name: str = Field(min_length=2, max_length=12)

    schema = ProductionBriefService._gemini_response_json_schema(ConstrainedItem)
    keys = set(_walk_schema_keys(schema))

    assert "exclusiveMinimum" not in keys
    assert "exclusiveMaximum" not in keys
    assert "minLength" not in keys
    assert "maxLength" not in keys
    assert "default" not in keys
    assert schema["properties"]["value"]["minimum"] == 0
    assert schema["properties"]["value"]["maximum"] == 20


def test_storyboard_schema_is_safe_for_response_json_schema():
    from app.models.production_brief import AiStoryboardOutline
    from app.services.production_brief_service import ProductionBriefService

    schema = ProductionBriefService._gemini_response_json_schema(AiStoryboardOutline)
    keys = set(_walk_schema_keys(schema))

    unsupported = {"exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength", "default"}
    assert not (keys & unsupported)
    duration = schema["$defs"]["AiStoryboardOutlineShot"]["properties"]["duration_seconds"]
    assert duration["minimum"] == 0.5
    assert duration["maximum"] == 20


def test_direction_fidelity_contract_detects_explicit_two_subjects():
    rec = make_recommendation().model_copy(update={
        "title": "The Royal Afternoon Tea Party",
        "concept": "Two dogs dressed in elegant Victorian-era attire sit at a miniature table sipping water from tiny teacups.",
        "recommended_characters": [],
    })
    contract = ProductionBriefService._build_direction_fidelity_contract(rec)
    assert contract.explicit_subject_count == 2
    assert "royal" in contract.core_terms
    assert "tea" in contract.core_terms


def test_direction_fidelity_blocks_subject_count_drift():
    rec = make_recommendation().model_copy(update={
        "title": "The Royal Afternoon Tea Party",
        "concept": "Two dogs dressed in elegant Victorian-era attire sit at a miniature table sipping water from tiny teacups.",
        "recommended_characters": [],
    })
    contract = ProductionBriefService._build_direction_fidelity_contract(rec)
    identity = make_identity().model_copy(update={
        "character_name": "The Victorian Duchess Dog",
        "subject_count": 1,
        "supporting_subjects": [],
        "setting_anchor": "miniature Victorian parlor",
        "primary_prop": "porcelain teacup",
    })
    from app.models.production_brief import CreativeDirection
    creative = CreativeDirection(
        working_title="The Royal Afternoon Tea Party",
        creative_objective="Create a Victorian afternoon tea short.",
        one_sentence_promise="One elegant dog hosts afternoon tea.",
        opening_hook="A dog sniffs a porcelain teacup.",
        narrative_arc="Tea setup to polite finale.",
        target_duration_seconds=15,
        format="Short-form vertical video",
        tone=["Whimsical", "Elegant"],
        production_identity=identity,
        character_direction="One duchess dog hosts the tea.",
        setting="Victorian parlor",
    )
    storyboard = StoryboardPlan(shots=[
        StoryboardShot(shot_number=1, duration_seconds=3, purpose="Hook", visual_action="One dog sniffs a teacup.", camera_direction="Close-up", generation_prompt="x"),
        StoryboardShot(shot_number=2, duration_seconds=4, purpose="Setup", visual_action="The dog sits at afternoon tea.", camera_direction="Medium", generation_prompt="x"),
        StoryboardShot(shot_number=3, duration_seconds=4, purpose="Action", visual_action="The dog sips water.", camera_direction="Wide", generation_prompt="x"),
        StoryboardShot(shot_number=4, duration_seconds=4, purpose="Payoff", visual_action="The dog bows politely.", camera_direction="Close-up", generation_prompt="x"),
    ], estimated_duration_seconds=15)
    publishing = PublishingPackage(
        youtube_title="Royal Afternoon Tea", description="One dog hosts tea.", social_caption="Tea time.",
        hashtags=["#tea"], thumbnail_concept="One dog at tea", audio_direction="Classical",
        accessibility_alt_text="One dog at a Victorian tea table."
    )
    report = ProductionBriefService._build_direction_fidelity_report(
        contract=contract, recommendation=rec, creative=creative, storyboard=storyboard, publishing=publishing
    )
    assert report.status == "REVIEW_REQUIRED"
    assert any(check.key == "subject_count" and check.status == "BLOCK" for check in report.checks)


def test_consistency_anchor_validation_allows_natural_paraphrases():
    identity = make_identity().model_copy(update={
        "setting_anchor": "A miniature wooden sushi bar counter with tiny bamboo mats and decorative plastic grass",
        "primary_prop": "Miniature clay salmon sushi roll on a tiny wooden sushi serving board geta",
    })
    from app.models.production_brief import CreativeDirection
    creative = CreativeDirection(
        working_title="Chinggay's Sushi Bar",
        creative_objective="Create a sushi short",
        one_sentence_promise="A tiny sushi presentation",
        opening_hook="Chinggay presents the roll.",
        narrative_arc="Prepare to present",
        target_duration_seconds=12,
        format="Short-form vertical video",
        tone=["Playful"],
        production_identity=identity,
        character_direction="Keep Chinggay consistent",
        setting="A cozy miniature Japanese sushi bar",
    )
    storyboard = StoryboardPlan(
        shots=[
            StoryboardShot(
                shot_number=i,
                duration_seconds=3,
                purpose="Beat",
                visual_action="Chinggay presents sushi with canine paws.",
                camera_direction="Medium",
                generation_prompt=ProductionBriefService._apply_identity_lock_to_prompt("Chinggay presents sushi.", identity),
            ) for i in range(1, 5)
        ],
        estimated_duration_seconds=12,
    )
    publishing = PublishingPackage(
        youtube_title="Chinggay's Sushi Bar",
        description="Chinggay serves a miniature salmon sushi roll inside a cozy sushi bar.",
        social_caption="Tiny sushi bar opening!",
        thumbnail_concept="Chinggay behind a sushi bar with a salmon roll",
        audio_direction="Light music",
        accessibility_alt_text="A dog at a miniature sushi bar with a salmon roll",
    )
    report = ProductionBriefService._build_consistency_report(
        creative=creative,
        storyboard=storyboard,
        publishing=publishing,
        publishing_identity_echo=(
            identity.character_name,
            "cozy miniature Japanese sushi bar with wooden counter",
            "miniature salmon sushi roll on a wooden serving board",
        ),
    )
    assert report.status == "PASS"
    assert report.anchors is not None
    assert "sushi" in report.anchors.setting_terms
    assert "salmon" in report.anchors.primary_prop_terms
