import asyncio

from app.core.config import Settings
from app.models.content_dna import AiVideoClassificationBatch, VideoContentClassification
from app.services.content_dna_job_service import ContentDnaCheckpointStore
from app.services.content_dna_service import ContentDnaCheckpoint, ContentDnaService


class FakeResponse:
    def __init__(self, text):
        self.text = text
        self.parsed = None


class FakeModels:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def generate_content(self, **kwargs):
        response = self.responses[self.calls]
        self.calls += 1
        return response


class FakeAio:
    def __init__(self, responses):
        self.models = FakeModels(responses)


class FakeClient:
    def __init__(self, responses):
        self.aio = FakeAio(responses)


def test_structured_generation_retries_invalid_json_then_succeeds(monkeypatch):
    from app.services.channel_intelligence_budget import ChannelIntelligenceBudget

    async def fake_budget_generate(self, *, client, model, contents, config, **kwargs):
        return await client.aio.models.generate_content(model=model, contents=contents, config=config)

    monkeypatch.setattr(ChannelIntelligenceBudget, "generate", fake_budget_generate)
    settings = Settings(content_dna_retry_attempts=2)
    service = ContentDnaService(settings)
    client = FakeClient([
        FakeResponse('{"classifications":[{"video_id":"abc"'),
        FakeResponse('{"classifications":[{"video_id":"abc","summary":"ok","themes":[],"characters":[],"story_patterns":[],"visual_patterns":[],"tones":[],"content_intent":"entertainment","setting":null,"human_like_activity":null,"confidence":0.9,"evidence_notes":[]}]}'),
    ])

    result = asyncio.run(service._generate_structured_with_retry(
        client=client,
        model="fake-model",
        contents="prompt",
        config=object(),
        model_cls=AiVideoClassificationBatch,
        failure_message="failed",
    ))

    assert result.classifications[0].video_id == "abc"
    assert client.aio.models.calls == 2
    assert service.gemini_calls == 2


def test_checkpoint_store_returns_deep_copy():
    store = ContentDnaCheckpointStore()
    checkpoint = ContentDnaCheckpoint(
        classifications=[
            VideoContentClassification(
                video_id="abc",
                summary="first",
                confidence=0.9,
            )
        ],
        visuals_analyzed=1,
        successful_classifications=1,
        total_videos=1,
    )
    store.put("analysis-1", checkpoint)

    loaded = store.get("analysis-1")
    assert loaded is not None
    loaded.classifications[0].summary = "changed"

    loaded_again = store.get("analysis-1")
    assert loaded_again is not None
    assert loaded_again.classifications[0].summary == "first"


def test_compact_alias_reconnects_all_supporting_video_ids():
    from app.models.content_dna import (
        AiCanonicalGroup,
        AiCanonicalTone,
        AiCharacterSummary,
        AiIdentityLite,
        AiIdentityVoiceSynthesis,
        AiPatternSynthesis,
        AiThemeCharacterSynthesis,
        CharacterMention,
    )

    service = ContentDnaService(Settings())
    classifications = [
        VideoContentClassification(
            video_id="v1",
            summary="dog cooks breakfast",
            themes=["Pet cooking", "Human-like pets"],
            characters=[CharacterMention(name="Fendi", animal_or_subject="dog", role="chef")],
            story_patterns=["Pet does a human job"],
            visual_patterns=["Pet in costume"],
            tones=["Wholesome"],
            confidence=0.95,
        ),
        VideoContentClassification(
            video_id="v2",
            summary="another kitchen story",
            themes=["Pet cooking"],
            characters=[CharacterMention(name="Fendi", animal_or_subject="dog", role="cook")],
            story_patterns=["Pet does a human job"],
            visual_patterns=["Pet in costume"],
            tones=["Wholesome"],
            confidence=0.9,
        ),
    ]

    result = service._reconnect_synthesis_evidence(
        classifications=classifications,
        identity_voice=AiIdentityVoiceSynthesis(
            identity=AiIdentityLite(
                summary="AI pet stories",
                primary_niche="AI pet storytelling",
                content_promise="cute pet stories",
                dominant_format="short-form",
                language_style="playful English",
                confidence=0.9,
            ),
            voice_tone=[AiCanonicalTone(label="Wholesome", explanation="Warm and gentle", aliases=["Wholesome"], confidence=0.9)],
        ),
        themes_characters=AiThemeCharacterSynthesis(
            themes=[AiCanonicalGroup(name="Pet cooking", description="Pets prepare food", aliases=["Pet cooking"])],
            characters=[AiCharacterSummary(name="Fendi", description="Recurring dog character", roles=["chef"])],
        ),
        patterns=AiPatternSynthesis(
            story_patterns=[AiCanonicalGroup(name="Human jobs", description="Pets perform human jobs", aliases=["Pet does a human job"])],
            visual_patterns=[AiCanonicalGroup(name="Costumed pets", description="Pets wear role-specific costumes", aliases=["Pet in costume"])],
        ),
    )

    assert result.themes[0].evidence_video_ids == ["v1", "v2"]
    assert result.characters[0].evidence_video_ids == ["v1", "v2"]
    assert result.voice_tone[0].evidence_video_ids == ["v1", "v2"]
    assert result.story_patterns[0].evidence_video_ids == ["v1", "v2"]
    assert result.visual_patterns[0].evidence_video_ids == ["v1", "v2"]


def test_character_aliases_merge_spelling_variants_without_fuzzy_merging_distinct_names():
    from app.models.content_dna import (
        AiCanonicalGroup,
        AiCharacterSummary,
        AiIdentityLite,
        AiIdentityVoiceSynthesis,
        AiPatternSynthesis,
        AiThemeCharacterSynthesis,
        CharacterMention,
    )

    service = ContentDnaService(Settings())
    classifications = [
        VideoContentClassification(
            video_id="v1",
            summary="Fudge at work",
            characters=[CharacterMention(name="Fudge", role="barista")],
            confidence=0.9,
        ),
        VideoContentClassification(
            video_id="v2",
            summary="Fudgee in the kitchen",
            characters=[CharacterMention(name="Fudgee", role="Barista")],
            confidence=0.9,
        ),
        VideoContentClassification(
            video_id="v3",
            summary="Choco party",
            characters=[CharacterMention(name="Choco", role="party host")],
            confidence=0.9,
        ),
        VideoContentClassification(
            video_id="v4",
            summary="Coco camping",
            characters=[CharacterMention(name="Coco", role="camper")],
            confidence=0.9,
        ),
    ]

    result = service._reconnect_synthesis_evidence(
        classifications=classifications,
        identity_voice=AiIdentityVoiceSynthesis(
            identity=AiIdentityLite(
                summary="Pet characters",
                primary_niche="Pet stories",
                content_promise="Cute pet shorts",
                dominant_format="short-form",
                language_style="playful",
                confidence=0.9,
            ),
            voice_tone=[],
        ),
        themes_characters=AiThemeCharacterSynthesis(
            themes=[],
            characters=[
                AiCharacterSummary(
                    name="Fudgee",
                    description="Recurring dog character",
                    aliases=["Fudgee", "Fudge"],
                    roles=["Barista", "barista"],
                ),
                AiCharacterSummary(name="Choco", description="Choco", aliases=["Choco"], roles=["party host"]),
                AiCharacterSummary(name="Coco", description="Coco", aliases=["Coco"], roles=["camper"]),
            ],
        ),
        patterns=AiPatternSynthesis(story_patterns=[], visual_patterns=[]),
    )

    by_name = {item.name: item for item in result.characters}
    assert by_name["Fudgee"].evidence_video_ids == ["v1", "v2"]
    assert by_name["Fudgee"].roles == ["Barista"]
    assert "Fudge" in by_name["Fudgee"].aliases
    assert by_name["Choco"].evidence_video_ids == ["v3"]
    assert by_name["Coco"].evidence_video_ids == ["v4"]


def test_semantic_label_cleanup_deduplicates_case_and_simple_plural_variants():
    service = ContentDnaService(Settings())
    labels = service._dedupe_display_labels([
        "Barista",
        "barista",
        "Kitchen Themes",
        "Kitchen Theme",
        "Pet Costumes",
        "Pet Costume",
    ])

    assert labels == ["Barista", "Kitchen Themes", "Pet Costumes"]
