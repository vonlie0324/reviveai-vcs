from app.models.content_dna import (
    AiCanonicalGroup,
    AiCharacterSummary,
    AiCharacterSynthesis,
    AiIdentityLite,
    AiIdentityVoiceSynthesis,
    AiThemeSynthesis,
)
from app.services.content_dna_job_service import ContentDnaCheckpointStore
from app.services.content_dna_service import ContentDnaCheckpoint


def test_split_theme_and_character_schemas_are_independent():
    themes = AiThemeSynthesis(
        themes=[AiCanonicalGroup(name="Culinary Pets", description="Pets in cooking scenarios.", aliases=["Pet Cooking"])]
    )
    characters = AiCharacterSynthesis(
        characters=[AiCharacterSummary(name="Chinggay", description="Recurring named dog.", aliases=[], roles=["Barista"])]
    )

    assert themes.themes[0].name == "Culinary Pets"
    assert characters.characters[0].name == "Chinggay"


def test_checkpoint_copy_preserves_completed_synthesis_steps():
    store = ContentDnaCheckpointStore()
    checkpoint = ContentDnaCheckpoint(
        classifications=[],
        visuals_analyzed=89,
        successful_classifications=89,
        total_videos=89,
        identity_voice=AiIdentityVoiceSynthesis(
            identity=AiIdentityLite(
                summary="Pet channel",
                primary_niche="Pets",
                content_promise="Cute pet stories",
                dominant_format="Short-form",
                language_style="Playful",
                confidence=0.9,
            ),
            voice_tone=[],
        ),
        themes=AiThemeSynthesis(
            themes=[AiCanonicalGroup(name="Culinary Pets", description="Pets cooking.", aliases=["Pet Cooking"])]
        ),
    )

    store.put("channel-key", checkpoint)
    restored = store.get("channel-key")

    assert restored is not None
    assert restored.identity_voice is not None
    assert restored.identity_voice.identity.primary_niche == "Pets"
    assert restored.themes is not None
    assert restored.themes.themes[0].name == "Culinary Pets"
    assert restored.characters is None
