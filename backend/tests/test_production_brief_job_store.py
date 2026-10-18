from datetime import datetime, timezone

import pytest

from app.models.production_brief import (
    ConsistencyCheck,
    CreativeDirection,
    DirectionFidelityContract,
    DirectionFidelityReport,
    DirectionFidelityStatus,
    ProductionBriefResult,
    ProductionConsistencyReport,
    ProductionConsistencyStatus,
    ProductionIdentity,
    ProductionReviewStatus,
    PublishingPackage,
    SourceDirectionSnapshot,
    StoryboardPlan,
)
from app.models.recovery import EvidenceStrength, NextContentRecommendation
from app.services.production_brief_job_service import ProductionBriefJobStore


def recommendation():
    return NextContentRecommendation(
        rank=1,
        recommendation_id="recommendation_1",
        title="Test idea",
        concept="Test concept",
        hook="Test hook",
        format="Short-form video",
        why_this_fits="Evidence backed",
        evidence_strength=EvidenceStrength.STRONG,
        novelty_label="No close match detected",
        novelty_score=0.8,
    )


def snapshot(rec=None):
    rec = rec or recommendation()
    return SourceDirectionSnapshot(
        snapshot_id="source_test",
        captured_at=datetime.now(timezone.utc),
        recovery_job_id="r1",
        channel_id="channel-1",
        channel_title="Test Channel",
        source_hash="abc123",
        immutable=True,
        recommendation=rec,
    )


def result(source_snapshot=None):
    return ProductionBriefResult(
        generated_at=datetime.now(timezone.utc),
        source_snapshot=source_snapshot or snapshot(),
        model="gemini-test",
        gemini_calls=3,
        selected_recommendation=recommendation(),
        creative_direction=CreativeDirection(
            working_title="Test",
            creative_objective="Create a short",
            one_sentence_promise="A clear story",
            opening_hook="Open strong",
            narrative_arc="Hook to payoff",
            target_duration_seconds=15,
            format="Short-form video",
            tone=["Playful"],
            production_identity=ProductionIdentity(
                character_name="Dior", identity_source="existing_character", species_or_subject="small dog",
                appearance="fluffy cream coat", wardrobe="formal tuxedo", personality=["calm"],
                primary_prop="tiny book", setting_anchor="miniature set", lighting_style="warm lighting",
                anatomy_rule="Use canine paws; no visible human hand or arm."
            ),
            character_direction="Keep character consistent",
            setting="Miniature set",
        ),
        storyboard=StoryboardPlan(shots=[], estimated_duration_seconds=0),
        publishing=PublishingPackage(
            youtube_title="Test title",
            description="Test description",
            social_caption="Test caption",
            hashtags=["#Test"],
            thumbnail_concept="Test thumbnail",
            audio_direction="Light music",
            accessibility_alt_text="A dog in a miniature set",
        ),
        consistency_report=ProductionConsistencyReport(
            status=ProductionConsistencyStatus.PASS,
            checks=[ConsistencyCheck(key="identity", label="Identity", status="PASS", detail="OK")],
        ),
        direction_fidelity=DirectionFidelityReport(
            status=DirectionFidelityStatus.PASS,
            contract=DirectionFidelityContract(
                source_title="Test idea", source_concept="Test concept", source_summary="Test idea"
            ),
        ),
    )


def make_job(store: ProductionBriefJobStore):
    rec = recommendation()
    return store.create(
        recovery_job_id="r1",
        content_dna_job_id="d1",
        analysis_job_id="a1",
        channel_id="channel-1",
        channel_title="Test Channel",
        recommendation=rec,
        recovery_generated_at=datetime.now(timezone.utc),
    )


def test_store_records_human_approval(tmp_path):
    store = ProductionBriefJobStore(str(tmp_path))
    job = make_job(store)
    store.complete(job.job_id, result(job.source_snapshot))
    approved = store.approve(job.job_id)
    assert approved.result is not None
    assert approved.result.review_status == ProductionReviewStatus.APPROVED
    assert approved.result.reviewed_at is not None


def test_approval_requires_completed_result(tmp_path):
    store = ProductionBriefJobStore(str(tmp_path))
    job = make_job(store)
    with pytest.raises(ValueError):
        store.approve(job.job_id)


def test_approval_blocks_consistency_failure(tmp_path):
    store = ProductionBriefJobStore(str(tmp_path))
    job = make_job(store)
    failed = result(job.source_snapshot)
    failed.consistency_report.status = ProductionConsistencyStatus.REVIEW_REQUIRED
    failed.consistency_report.blocking_issues = ["Character name mismatch"]
    store.complete(job.job_id, failed)
    with pytest.raises(ValueError, match="consistency"):
        store.approve(job.job_id)


def test_approval_blocks_unreviewed_direction_drift(tmp_path):
    store = ProductionBriefJobStore(str(tmp_path))
    job = make_job(store)
    drifted = result(job.source_snapshot)
    drifted.direction_fidelity.status = DirectionFidelityStatus.REVIEW_REQUIRED
    drifted.direction_fidelity.blocking_issues = ["Source specifies two subjects, brief has one."]
    store.complete(job.job_id, drifted)
    with pytest.raises(ValueError, match="Direction Fidelity"):
        store.approve(job.job_id)


def test_creator_can_accept_adaptation_then_approve(tmp_path):
    store = ProductionBriefJobStore(str(tmp_path))
    job = make_job(store)
    drifted = result(job.source_snapshot)
    drifted.direction_fidelity.status = DirectionFidelityStatus.REVIEW_REQUIRED
    drifted.direction_fidelity.blocking_issues = ["Source specifies two subjects, brief has one."]
    store.complete(job.job_id, drifted)
    accepted = store.accept_adaptation(job.job_id)
    assert accepted.result is not None
    assert accepted.result.direction_fidelity.status == DirectionFidelityStatus.ADAPTATION_ACCEPTED
    approved = store.approve(job.job_id)
    assert approved.result.review_status == ProductionReviewStatus.APPROVED


def test_source_snapshot_is_reused_when_retrying_after_recovery_changes(tmp_path):
    store = ProductionBriefJobStore(str(tmp_path))
    original = make_job(store)
    original_title = original.source_snapshot.recommendation.title
    retried = store.create_from_snapshot(original, fidelity_mode=original.fidelity_mode)
    assert retried.source_snapshot.snapshot_id == original.source_snapshot.snapshot_id
    assert retried.source_snapshot.source_hash == original.source_snapshot.source_hash
    assert retried.source_snapshot.recommendation.title == original_title


def test_completed_job_is_discoverable_from_disk_history(tmp_path):
    first_store = ProductionBriefJobStore(str(tmp_path))
    job = make_job(first_store)
    first_store.complete(job.job_id, result(job.source_snapshot))

    second_store = ProductionBriefJobStore(str(tmp_path))
    restored = second_store.get(job.job_id)
    history = second_store.list_history(channel_id="channel-1")

    assert restored.source_snapshot.recommendation.title == "Test idea"
    assert history
    assert history[0].job_id == job.job_id
    assert history[0].source_snapshot.immutable is True
