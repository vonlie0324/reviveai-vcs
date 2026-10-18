from datetime import datetime, timezone

from app.core.config import Settings
from app.models.content_dna import EvidenceMetrics, VideoContentClassification
from app.models.recovery import (
    ContentGapOpportunity,
    EvidenceStrength,
    GapOpportunityStrength,
    NextContentRecommendation,
    RecoverySignal,
)
from app.models.youtube import (
    AnalysisResult,
    ChannelMetrics,
    ChannelSnapshot,
    DistributionMetrics,
    EngagementMetrics,
    CadenceMetrics,
    IngestionSummary,
    RecencyComparison,
    ThumbnailSet,
    VideoSnapshot,
)
from app.services.recovery_service import RecoveryService


def make_service():
    return RecoveryService(Settings(google_cloud_project="test-project"))


def test_similarity_detects_related_concepts():
    service = make_service()
    close = service._similarity("Chinggay bakes pastries in a kitchen", "Chef Chinggay cooks pancakes in the kitchen")
    far = service._similarity("Chinggay bakes pastries in a kitchen", "Dior flies a rescue helicopter")
    assert close > far


def test_novelty_labels_are_conservative():
    service = make_service()
    assert service._novelty_label(0.8) == "No close match detected"
    assert service._novelty_label(0.6) == "Adjacent to archive"
    assert service._novelty_label(0.3) == "Possible overlap"


def test_evidence_strength_requires_support():
    service = make_service()
    strong = RecoverySignal(
        kind="theme",
        name="Kitchen",
        evidence=EvidenceMetrics(video_count=10, relative_to_channel_median=4.0),
    )
    other = RecoverySignal(
        kind="character",
        name="Chinggay",
        evidence=EvidenceMetrics(video_count=6, relative_to_channel_median=2.9),
    )
    weak = RecoverySignal(
        kind="theme",
        name="Fashion",
        evidence=EvidenceMetrics(video_count=20, relative_to_channel_median=0.8),
    )
    assert service._evidence_strength([strong, other]) == EvidenceStrength.STRONG
    assert service._evidence_strength([strong]) == EvidenceStrength.SUPPORTED
    assert service._evidence_strength([weak]) == EvidenceStrength.EXPLORATORY


def test_signal_linking_uses_exact_canonical_names():
    service = make_service()
    signals = [
        RecoverySignal(kind="theme", name="Culinary Pets"),
        RecoverySignal(kind="character", name="Chinggay"),
    ]
    linked = service._link_signals(["culinary pets", "Chinggay", "Unknown"], signals)
    assert [item.name for item in linked] == ["Culinary Pets", "Chinggay"]


def test_token_normalization_removes_generic_channel_words():
    tokens = RecoveryService._normalized_tokens("Cute pet dog short video: Chef Chinggay in the kitchen")
    assert "pet" not in tokens
    assert "dog" not in tokens
    assert "short" not in tokens
    assert "chef" in tokens
    assert "chinggay" in tokens
    assert "kitchen" in tokens


def test_gap_opportunity_uses_gap_specific_vocabulary():
    service = make_service()
    assert service._gap_opportunity_strength(EvidenceStrength.STRONG, "No close match detected") == GapOpportunityStrength.EVIDENCE_BACKED_GAP
    assert service._gap_opportunity_strength(EvidenceStrength.SUPPORTED, "No close match detected") == GapOpportunityStrength.ADJACENT_OPPORTUNITY
    assert service._gap_opportunity_strength(EvidenceStrength.EXPLORATORY, "Adjacent to archive") == GapOpportunityStrength.EMERGING_OPPORTUNITY


def test_safe_claim_text_removes_overconfident_language():
    service = make_service()
    text = service._safe_claim_text("Leverages Chinggay's popularity and a proven, highly successful format.")
    lowered = text.lower()
    assert "popularity" not in lowered
    assert "proven" not in lowered
    assert "successful" not in lowered
    assert "historically above-baseline performance" in lowered
    assert "historically supported" in lowered
    assert "historically strong" in lowered


def test_shared_title_uses_one_canonical_evidence_strength():
    service = make_service()
    strong = RecoverySignal(
        kind="theme",
        name="Kitchen",
        evidence=EvidenceMetrics(video_count=10, relative_to_channel_median=4.0),
    )
    other = RecoverySignal(
        kind="character",
        name="Chinggay",
        evidence=EvidenceMetrics(video_count=6, relative_to_channel_median=2.9),
    )
    gap = ContentGapOpportunity(
        gap_id="gap_1",
        title="Chinggay's Graduation Celebration",
        concept="A graduation scene",
        why_it_fits="Supported by the archive",
        novelty_label="No close match detected",
        novelty_score=0.8,
        evidence_strength=EvidenceStrength.SUPPORTED,
        opportunity_strength=GapOpportunityStrength.ADJACENT_OPPORTUNITY,
        evidence_signals=[strong],
    )
    recommendation = NextContentRecommendation(
        rank=1,
        recommendation_id="recommendation_1",
        title="Chinggay's Graduation Celebration",
        concept="A graduation scene",
        hook="Chinggay adjusts a cap",
        format="Short-form video",
        why_this_fits="Supported by the archive",
        evidence_strength=EvidenceStrength.SUPPORTED,
        evidence_signals=[other],
        novelty_label="No close match detected",
        novelty_score=0.8,
    )
    service._canonicalize_shared_strengths([gap], [recommendation])
    assert gap.evidence_strength == EvidenceStrength.STRONG
    assert recommendation.evidence_strength == EvidenceStrength.STRONG
    assert gap.opportunity_strength == GapOpportunityStrength.EVIDENCE_BACKED_GAP


def _signal(name: str, kind: str = "theme", ratio: float = 2.0, count: int = 8) -> RecoverySignal:
    return RecoverySignal(
        kind=kind,
        name=name,
        evidence=EvidenceMetrics(video_count=count, relative_to_channel_median=ratio),
    )


def _recommendation(title: str, concept: str, signals, rank: int = 1, chars=None):
    return NextContentRecommendation(
        rank=rank,
        recommendation_id=f"r{rank}_{title}",
        title=title,
        concept=concept,
        hook=concept,
        format="Short-form video",
        why_this_fits="Supported by the archive",
        recommended_characters=chars or [],
        evidence_strength=EvidenceStrength.STRONG,
        evidence_signals=list(signals),
        novelty_label="No close match detected",
        novelty_score=0.8,
    )


def test_canonicalizes_semantically_equivalent_gap_and_recommendation():
    service = make_service()
    kitchen = _signal("Kitchen and Cooking Themes", "visual_pattern", 5.4, 10)
    culinary = _signal("Culinary & Dining Pets", "theme", 4.4, 9)
    dior = _signal("Dior", "character", 2.9, 6)

    gap = ContentGapOpportunity(
        gap_id="gap_1",
        title="Dior's Outdoor Pizza Party",
        concept="Dior acts as a backyard pizza chef using a miniature outdoor pizza oven.",
        why_it_fits="Supported by the archive",
        novelty_label="No close match detected",
        novelty_score=0.82,
        evidence_strength=EvidenceStrength.SUPPORTED,
        opportunity_strength=GapOpportunityStrength.ADJACENT_OPPORTUNITY,
        evidence_signals=[kitchen, culinary],
    )
    recommendation = _recommendation(
        "Dior's Backyard Pizza Party",
        "Dior acts as a backyard pizza chef using a tiny outdoor oven to serve miniature pizzas.",
        [kitchen, culinary, dior],
        chars=["Dior"],
    )

    ideas = service._canonicalize_recovery_ideas([gap], [recommendation])

    assert len(ideas) == 1
    assert gap.canonical_idea_id == recommendation.canonical_idea_id
    assert gap.title == recommendation.title == "Dior's Backyard Pizza Party"
    assert [s.name for s in gap.evidence_signals] == [s.name for s in recommendation.evidence_signals]
    assert gap.novelty_label == recommendation.novelty_label


def test_deduplicate_recommendations_uses_canonical_idea_id():
    service = make_service()
    kitchen = _signal("Kitchen and Cooking Themes", "visual_pattern", 5.4, 10)
    first = _recommendation("Dior Pizza Party", "Dior makes pizza outdoors.", [kitchen], rank=1)
    second = _recommendation("Dior Backyard Pizza", "Dior makes pizza in a backyard oven.", [kitchen], rank=2)
    first.canonical_idea_id = "idea_pizza"
    second.canonical_idea_id = "idea_pizza"

    result = service._deduplicate_recommendations([first, second])
    assert len(result) == 1
    assert result[0].canonical_idea_id == "idea_pizza"


def test_diversity_ranking_prefers_distinct_strategy_lane_over_near_duplicate():
    service = make_service()
    kitchen = _signal("Kitchen and Cooking Themes", "visual_pattern", 5.4, 10)
    culinary = _signal("Culinary & Dining Pets", "theme", 4.4, 9)
    dior = _signal("Dior", "character", 2.9, 6)
    roleplay = _signal("Roleplay and Professional Scenarios", "story_pattern", 1.3, 27)
    chinggay = _signal("Chinggay", "character", 2.9, 6)
    celebration = _signal("Celebrations and Parties", "story_pattern", 2.1, 5)

    pizza = _recommendation(
        "Dior's Backyard Pizza Party",
        "Dior cooks miniature pizzas in a backyard oven.",
        [kitchen, culinary, dior],
        rank=1,
        chars=["Dior"],
    )
    pizza2 = _recommendation(
        "Dior's Miniature Pizza Masterclass",
        "Dior teaches a puppy apprentice to make miniature pizzas.",
        [kitchen, culinary, dior],
        rank=2,
        chars=["Dior"],
    )
    graduation = _recommendation(
        "Chinggay's Graduation Celebration",
        "Chinggay celebrates graduation in a classroom party.",
        [chinggay, celebration, roleplay],
        rank=3,
        chars=["Chinggay"],
    )

    ranked = service._diversity_rank_recommendations([pizza, pizza2, graduation], limit=2)
    assert ranked[0].title == "Dior's Backyard Pizza Party"
    assert ranked[1].title == "Chinggay's Graduation Celebration"
    assert "distinct strategy lane" in ranked[1].diversity_note.lower()


def test_finalize_marks_gap_when_same_canonical_idea_is_selected():
    service = make_service()
    signal = _signal("Kitchen", ratio=3.0, count=10)
    gap = ContentGapOpportunity(
        gap_id="g",
        canonical_idea_id="idea_shared",
        title="Shared idea",
        concept="Concept",
        why_it_fits="Why",
        novelty_label="No close match detected",
        novelty_score=0.8,
        evidence_strength=EvidenceStrength.STRONG,
        opportunity_strength=GapOpportunityStrength.EVIDENCE_BACKED_GAP,
        evidence_signals=[signal],
    )
    rec = _recommendation("Shared idea", "Concept", [signal])
    rec.canonical_idea_id = "idea_shared"
    from app.models.recovery import CanonicalRecoveryIdea
    idea = CanonicalRecoveryIdea(
        idea_id="idea_shared",
        canonical_title="Shared idea",
        concept="Concept",
        evidence_strength=EvidenceStrength.STRONG,
        evidence_signals=[signal],
        novelty_label="No close match detected",
        novelty_score=0.8,
    )
    result = service._finalize_canonical_ideas([idea], [gap], [rec])
    assert gap.selected_for_recovery_plan is True
    assert result[0].roles == ["CONTENT_GAP", "RECOVERY_PLAN"]


def test_idea_specific_grounding_removes_globally_strong_but_irrelevant_culinary_signals():
    service = make_service()
    kitchen = _signal("Kitchen and Cooking Themes", "visual_pattern", 5.4, 10)
    culinary = _signal("Culinary & Dining Pets", "theme", 4.4, 9)
    chinggay = _signal("Chinggay", "character", 2.9, 6)
    celebration = _signal("Celebrations and Parties", "story_pattern", 2.1, 5)
    roleplay = _signal("Roleplay and Professional Scenarios", "story_pattern", 1.3, 27)

    grounded = service._ground_signals_for_idea(
        "Officiant Chinggay conducts a tiny wedding ceremony and celebration at a floral altar.",
        [kitchen, culinary, chinggay, celebration, roleplay],
        preferred=[kitchen, culinary, chinggay],
        recommended_characters=["Chinggay"],
        limit=5,
    )
    names = [item.name for item in grounded]
    assert "Chinggay" in names
    assert "Celebrations and Parties" in names
    assert "Roleplay and Professional Scenarios" in names
    assert "Kitchen and Cooking Themes" not in names
    assert "Culinary & Dining Pets" not in names


def test_idea_specific_grounding_keeps_culinary_signals_for_food_concept():
    service = make_service()
    kitchen = _signal("Kitchen and Cooking Themes", "visual_pattern", 5.4, 10)
    culinary = _signal("Culinary & Dining Pets", "theme", 4.4, 9)
    jobs = _signal("Pets Performing Human Jobs", "story_pattern", 3.9, 7)
    dior = _signal("Dior", "character", 2.9, 6)

    grounded = service._ground_signals_for_idea(
        "Dior runs a miniature sushi bar as a master chef preparing food for diners.",
        [kitchen, culinary, jobs, dior],
        preferred=[kitchen, culinary, jobs, dior],
        recommended_characters=["Dior"],
        limit=5,
    )
    names = [item.name for item in grounded]
    assert "Kitchen and Cooking Themes" in names
    assert "Culinary & Dining Pets" in names
    assert "Pets Performing Human Jobs" in names
    assert "Dior" in names


def test_diversity_caps_limit_same_character_theme_and_primary_lane_to_two():
    service = make_service()
    kitchen = _signal("Kitchen and Cooking Themes", "visual_pattern", 5.4, 10)
    culinary = _signal("Culinary & Dining Pets", "theme", 4.4, 9)
    jobs = _signal("Pets Performing Human Jobs", "story_pattern", 3.9, 7)
    dior = _signal("Dior", "character", 2.9, 6)
    chinggay = _signal("Chinggay", "character", 2.9, 6)
    celebration = _signal("Celebrations and Parties", "story_pattern", 2.1, 5)
    roleplay = _signal("Roleplay and Professional Scenarios", "story_pattern", 1.3, 27)
    fashion = _signal("Pet Fashion & Cosplay", "theme", 0.9, 46)

    candidates = [
        _recommendation("Dior Sushi", "Dior makes sushi as a chef.", [kitchen, culinary, jobs, dior], rank=1, chars=["Dior"]),
        _recommendation("Dior Pizza", "Dior bakes pizza as a chef.", [kitchen, culinary, jobs, dior], rank=2, chars=["Dior"]),
        _recommendation("Dior Cake", "Dior bakes a birthday cake.", [kitchen, culinary, celebration, dior], rank=3, chars=["Dior"]),
        _recommendation("Chinggay Wedding", "Chinggay acts as a wedding officiant.", [chinggay, celebration, roleplay], rank=4, chars=["Chinggay"]),
        _recommendation("Chinggay Train", "Chinggay works as a train conductor.", [chinggay, jobs, roleplay], rank=5, chars=["Chinggay"]),
        _recommendation("Fashion Curator", "A new pet curates a fashion museum.", [fashion, roleplay], rank=6),
    ]

    ranked = service._diversity_rank_recommendations(candidates, limit=5)
    assert len(ranked) == 5

    char_counts = {}
    theme_counts = {}
    lane_counts = {}
    for item in ranked:
        for character in service._recommendation_characters(item):
            char_counts[character] = char_counts.get(character, 0) + 1
        theme = service._dominant_theme_key(item)
        if theme:
            theme_counts[theme] = theme_counts.get(theme, 0) + 1
        lane = service._primary_strategy_key(item)
        if lane:
            lane_counts[lane] = lane_counts.get(lane, 0) + 1

    assert max(char_counts.values(), default=0) <= 2
    assert max(theme_counts.values(), default=0) <= 2
    assert max(lane_counts.values(), default=0) <= 2
