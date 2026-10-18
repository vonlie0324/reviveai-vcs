from datetime import datetime, timezone

import pytest

from app.core.config import Settings
from app.models.media_studio import FidelityCheckStatus, KeyframeFidelityCheck, KeyframeFidelityReport, KeyframeFidelityStatus, MediaAsset, MediaAssetKind, MediaAssetReviewStatus, MediaStudioJobStage, ShotOperationStatus, ClipOperationStatus, VideoClipAsset
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
    PublishingPackage,
    StoryboardPlan,
    StoryboardShot,
)
from app.models.recovery import EvidenceStrength, NextContentRecommendation
from app.services.media_generation_service import MediaGenerationService
from app.services.media_studio_job_service import MediaStudioJobStore
from app.services.production_brief_job_service import ProductionBriefJobStore


def recommendation():
    return NextContentRecommendation(
        rank=1,
        recommendation_id="rec-1",
        title="Chinggay's Retro Cabin Crew Service",
        concept="Chinggay pushes a miniature beverage cart down a mock airplane aisle.",
        hook="A tiny beverage cart rolls forward.",
        format="Short-form video",
        why_this_fits="Roleplay signal",
        evidence_strength=EvidenceStrength.STRONG,
        novelty_label="No close match detected",
        novelty_score=0.9,
    )



def fidelity_report(shot_number: int, status: KeyframeFidelityStatus = KeyframeFidelityStatus.PASS):
    return KeyframeFidelityReport(
        shot_number=shot_number,
        status=status,
        checks=[KeyframeFidelityCheck(key="camera_framing", label="Camera framing", status=FidelityCheckStatus.PASS if status == KeyframeFidelityStatus.PASS else FidelityCheckStatus.REVIEW, detail="Test")],
        issues=[] if status == KeyframeFidelityStatus.PASS else ["Framing mismatch"],
        corrective_instruction=None if status == KeyframeFidelityStatus.PASS else "Preserve identity; change only to the requested close-up framing.",
        evaluated_at=datetime.now(timezone.utc),
        model="gemini-test",
    )

def identity():
    return ProductionIdentity(
        character_name="Chinggay",
        identity_source="existing_character",
        subject_count=1,
        supporting_subjects=["plush bunny passenger"],
        species_or_subject="Pomeranian dog",
        appearance="fluffy light-tan Pomeranian",
        wardrobe="teal vintage flight attendant uniform",
        personality=["charming", "attentive"],
        primary_prop="miniature beverage cart",
        setting_anchor="miniature airplane cabin",
        lighting_style="soft warm studio lighting",
        anatomy_rule="Only natural paws; no visible human hands or arms.",
    )


def approved_production_job(tmp_path):
    store = ProductionBriefJobStore(str(tmp_path))
    rec = recommendation()
    job = store.create(
        recovery_job_id="r1",
        content_dna_job_id="d1",
        analysis_job_id="a1",
        channel_id="UCtest",
        channel_title="Pawshionista",
        recommendation=rec,
        recovery_generated_at=datetime.now(timezone.utc),
    )
    result = ProductionBriefResult(
        generated_at=datetime.now(timezone.utc),
        source_snapshot=job.source_snapshot,
        model="gemini-test",
        gemini_calls=4,
        selected_recommendation=rec,
        creative_direction=CreativeDirection(
            working_title="Chinggay's Retro Cabin Crew Service",
            creative_objective="Create a short",
            one_sentence_promise="A playful cabin service scene",
            opening_hook="Cart rolls in",
            narrative_arc="Hook to payoff",
            target_duration_seconds=15,
            format="9:16 short",
            tone=["playful"],
            production_identity=identity(),
            character_direction="Keep Chinggay consistent",
            setting="miniature airplane cabin",
        ),
        storyboard=StoryboardPlan(
            shots=[
                StoryboardShot(
                    shot_number=1,
                    duration_seconds=3,
                    purpose="Hook",
                    visual_action="Chinggay pushes the cart.",
                    camera_direction="Close tracking shot",
                    generation_prompt="Shot one prompt",
                ),
                StoryboardShot(
                    shot_number=2,
                    duration_seconds=4,
                    purpose="Serve",
                    visual_action="Chinggay serves a plush passenger.",
                    camera_direction="Medium shot",
                    generation_prompt="Shot two prompt",
                ),
            ],
            estimated_duration_seconds=7,
        ),
        publishing=PublishingPackage(
            youtube_title="Cabin Crew Chinggay",
            description="Test",
            social_caption="Test",
            hashtags=["#Test"],
            thumbnail_concept="Test",
            audio_direction="Test",
            accessibility_alt_text="Test",
        ),
        consistency_report=ProductionConsistencyReport(
            status=ProductionConsistencyStatus.PASS,
            checks=[ConsistencyCheck(key="identity", label="Identity", status="PASS", detail="OK")],
        ),
        direction_fidelity=DirectionFidelityReport(
            status=DirectionFidelityStatus.PASS,
            contract=DirectionFidelityContract(
                source_title=rec.title,
                source_concept=rec.concept,
                source_summary=rec.title,
            ),
        ),
    )
    store.complete(job.job_id, result)
    return store, store.approve(job.job_id)


def test_media_job_requires_approved_production_brief(tmp_path):
    pstore = ProductionBriefJobStore(str(tmp_path))
    rec = recommendation()
    unapproved = pstore.create(
        recovery_job_id="r1", content_dna_job_id="d1", analysis_job_id="a1",
        channel_id="UCtest", channel_title="Pawshionista", recommendation=rec,
        recovery_generated_at=datetime.now(timezone.utc),
    )
    mstore = MediaStudioJobStore(str(tmp_path))
    with pytest.raises(ValueError, match="Approve"):
        mstore.create(unapproved, Settings())


def test_media_job_snapshots_identity_and_storyboard(tmp_path):
    _, production = approved_production_job(tmp_path)
    mstore = MediaStudioJobStore(str(tmp_path))
    job = mstore.create(production, Settings())
    assert job.result is not None
    assert job.result.source_snapshot.production_identity.character_name == "Chinggay"
    assert job.result.required_keyframes == 2
    assert job.result.source_snapshot.source_hash == production.result.source_snapshot.source_hash


def test_approving_reference_unlocks_keyframe_generation(tmp_path):
    _, production = approved_production_job(tmp_path)
    mstore = MediaStudioJobStore(str(tmp_path))
    job = mstore.create(production, Settings())
    job.result.reference_asset = MediaAsset(
        asset_id="ref1", kind=MediaAssetKind.CHARACTER_REFERENCE,
        created_at=datetime.now(timezone.utc), model="image-test", mime_type="image/png",
        filename="ref1.png", asset_url="/asset/ref1", prompt="prompt",
    )
    mstore.save(job)
    approved = mstore.approve_reference(job.job_id)
    assert approved.result.reference_approved is True
    assert approved.result.reference_asset.review_status == MediaAssetReviewStatus.APPROVED
    assert approved.stage == MediaStudioJobStage.GENERATING_KEYFRAMES


def test_all_approved_keyframes_unlock_animation(tmp_path):
    _, production = approved_production_job(tmp_path)
    mstore = MediaStudioJobStore(str(tmp_path))
    job = mstore.create(production, Settings())
    job.result.reference_asset = MediaAsset(
        asset_id="ref1", kind=MediaAssetKind.CHARACTER_REFERENCE,
        created_at=datetime.now(timezone.utc), model="image-test", mime_type="image/png",
        filename="ref1.png", asset_url="/asset/ref1", prompt="prompt",
        review_status=MediaAssetReviewStatus.APPROVED,
    )
    job.result.reference_approved = True
    job.result.keyframes = [
        MediaAsset(asset_id="kf1", kind=MediaAssetKind.KEYFRAME, shot_number=1, created_at=datetime.now(timezone.utc), model="image-test", mime_type="image/png", filename="kf1.png", asset_url="/asset/kf1", prompt="p1", fidelity_report=fidelity_report(1)),
        MediaAsset(asset_id="kf2", kind=MediaAssetKind.KEYFRAME, shot_number=2, created_at=datetime.now(timezone.utc), model="image-test", mime_type="image/png", filename="kf2.png", asset_url="/asset/kf2", prompt="p2", fidelity_report=fidelity_report(2)),
    ]
    job.stage = MediaStudioJobStage.AWAITING_KEYFRAME_REVIEW
    mstore.save(job)
    mstore.approve_keyframe(job.job_id, 1)
    final = mstore.approve_keyframe(job.job_id, 2)
    assert final.result.animation_ready is True
    assert final.result.approved_keyframes == 2
    assert final.stage == MediaStudioJobStage.READY_FOR_ANIMATION


def test_keyframe_prompt_carries_reference_first_continuity(tmp_path):
    service = MediaGenerationService(Settings())
    _, production = approved_production_job(tmp_path)
    source = MediaStudioJobStore._source_snapshot(production)
    prompt = service.keyframe_prompt(source, source.storyboard.shots[0])
    assert "approved character reference" in prompt.lower()
    assert "Do not redesign the character" in prompt
    assert "Chinggay" in prompt


def test_fidelity_review_required_blocks_approval(tmp_path):
    _, production = approved_production_job(tmp_path)
    mstore = MediaStudioJobStore(str(tmp_path))
    job = mstore.create(production, Settings())
    job.result.reference_asset = MediaAsset(
        asset_id="ref1", kind=MediaAssetKind.CHARACTER_REFERENCE, created_at=datetime.now(timezone.utc),
        model="image-test", mime_type="image/png", filename="ref1.png", asset_url="/asset/ref1", prompt="prompt",
        review_status=MediaAssetReviewStatus.APPROVED,
    )
    job.result.reference_approved = True
    job.result.keyframes = [MediaAsset(
        asset_id="kf1", kind=MediaAssetKind.KEYFRAME, shot_number=1, created_at=datetime.now(timezone.utc),
        model="image-test", mime_type="image/png", filename="kf1.png", asset_url="/asset/kf1", prompt="p1",
        fidelity_report=fidelity_report(1, KeyframeFidelityStatus.REVIEW_REQUIRED),
    )]
    job.result.required_keyframes = 1
    job.stage = MediaStudioJobStage.AWAITING_KEYFRAME_REVIEW
    mstore.save(job)
    with pytest.raises(ValueError, match="fidelity issues"):
        mstore.approve_keyframe(job.job_id, 1)


def test_accepting_adaptation_allows_human_approval(tmp_path):
    _, production = approved_production_job(tmp_path)
    mstore = MediaStudioJobStore(str(tmp_path))
    job = mstore.create(production, Settings())
    job.result.reference_asset = MediaAsset(
        asset_id="ref1", kind=MediaAssetKind.CHARACTER_REFERENCE, created_at=datetime.now(timezone.utc),
        model="image-test", mime_type="image/png", filename="ref1.png", asset_url="/asset/ref1", prompt="prompt",
        review_status=MediaAssetReviewStatus.APPROVED,
    )
    job.result.reference_approved = True
    job.result.keyframes = [MediaAsset(
        asset_id="kf1", kind=MediaAssetKind.KEYFRAME, shot_number=1, created_at=datetime.now(timezone.utc),
        model="image-test", mime_type="image/png", filename="kf1.png", asset_url="/asset/kf1", prompt="p1",
        fidelity_report=fidelity_report(1, KeyframeFidelityStatus.REVIEW_REQUIRED),
    )]
    job.result.required_keyframes = 1
    job.stage = MediaStudioJobStage.AWAITING_KEYFRAME_REVIEW
    mstore.save(job)
    adapted = mstore.accept_keyframe_adaptation(job.job_id, 1)
    assert adapted.result.keyframes[0].fidelity_report.status == KeyframeFidelityStatus.ADAPTATION_ACCEPTED
    final = mstore.approve_keyframe(job.job_id, 1)
    assert final.result.animation_ready is True
    assert final.stage == MediaStudioJobStage.READY_FOR_ANIMATION


def test_legacy_approved_keyframes_without_fidelity_are_relocked(tmp_path):
    _, production = approved_production_job(tmp_path)
    mstore = MediaStudioJobStore(str(tmp_path))
    job = mstore.create(production, Settings())
    job.result.reference_asset = MediaAsset(
        asset_id="ref1", kind=MediaAssetKind.CHARACTER_REFERENCE, created_at=datetime.now(timezone.utc),
        model="image-test", mime_type="image/png", filename="ref1.png", asset_url="/asset/ref1", prompt="prompt",
        review_status=MediaAssetReviewStatus.APPROVED,
    )
    job.result.reference_approved = True
    job.result.keyframes = [MediaAsset(
        asset_id="kf1", kind=MediaAssetKind.KEYFRAME, shot_number=1, created_at=datetime.now(timezone.utc),
        model="image-test", mime_type="image/png", filename="kf1.png", asset_url="/asset/kf1", prompt="p1",
        review_status=MediaAssetReviewStatus.APPROVED,
    )]
    job.result.required_keyframes = 1
    job.result.animation_ready = True
    job.stage = MediaStudioJobStage.READY_FOR_ANIMATION
    mstore.save(job)
    loaded = mstore.get(job.job_id)
    assert loaded.result.animation_ready is False
    assert loaded.result.fidelity_reviewed_keyframes == 0
    assert loaded.stage == MediaStudioJobStage.AWAITING_KEYFRAME_REVIEW


def test_targeted_keyframe_prompt_preserves_identity_and_changes_only_mismatch(tmp_path):
    service = MediaGenerationService(Settings())
    _, production = approved_production_job(tmp_path)
    source = MediaStudioJobStore._source_snapshot(production)
    prompt = service.keyframe_prompt(source, source.storyboard.shots[0], corrective_instruction="Use an extreme low-angle close-up.")
    assert "TARGETED CORRECTION" in prompt
    assert "Use an extreme low-angle close-up" in prompt
    assert "Do not redesign the character" in prompt
    assert "Change only what is necessary" in prompt


def test_local_regeneration_keeps_other_shots_visible_and_approved(tmp_path):
    _, production = approved_production_job(tmp_path)
    mstore = MediaStudioJobStore(str(tmp_path))
    job = mstore.create(production, Settings())
    job.result.reference_asset = MediaAsset(
        asset_id="ref1", kind=MediaAssetKind.CHARACTER_REFERENCE, created_at=datetime.now(timezone.utc),
        model="image-test", mime_type="image/png", filename="ref1.png", asset_url="/asset/ref1", prompt="prompt",
        review_status=MediaAssetReviewStatus.APPROVED,
    )
    job.result.reference_approved = True
    job.result.keyframes = [
        MediaAsset(asset_id="kf1", kind=MediaAssetKind.KEYFRAME, shot_number=1, created_at=datetime.now(timezone.utc), model="image-test", mime_type="image/png", filename="kf1.png", asset_url="/asset/kf1", prompt="p1", review_status=MediaAssetReviewStatus.APPROVED, fidelity_report=fidelity_report(1)),
        MediaAsset(asset_id="kf2", kind=MediaAssetKind.KEYFRAME, shot_number=2, created_at=datetime.now(timezone.utc), model="image-test", mime_type="image/png", filename="kf2.png", asset_url="/asset/kf2", prompt="p2", review_status=MediaAssetReviewStatus.APPROVED, fidelity_report=fidelity_report(2)),
    ]
    job.result.required_keyframes = 2
    job.stage = MediaStudioJobStage.READY_FOR_ANIMATION
    mstore.save(job)

    localized = mstore.begin_keyframe_regeneration(job.job_id, 1)

    assert localized.stage == MediaStudioJobStage.AWAITING_KEYFRAME_REVIEW
    assert localized.result.animation_ready is False
    assert localized.result.keyframes[0].review_status == MediaAssetReviewStatus.NEEDS_REVIEW
    assert localized.result.keyframes[1].review_status == MediaAssetReviewStatus.APPROVED
    assert localized.result.shot_operations[1].status == ShotOperationStatus.REGENERATING
    assert localized.result.shot_operations[1].target_generation_attempt == 2


def test_local_regeneration_failure_restores_previous_target_approval(tmp_path):
    _, production = approved_production_job(tmp_path)
    mstore = MediaStudioJobStore(str(tmp_path))
    job = mstore.create(production, Settings())
    job.result.reference_asset = MediaAsset(
        asset_id="ref1", kind=MediaAssetKind.CHARACTER_REFERENCE, created_at=datetime.now(timezone.utc),
        model="image-test", mime_type="image/png", filename="ref1.png", asset_url="/asset/ref1", prompt="prompt",
        review_status=MediaAssetReviewStatus.APPROVED,
    )
    job.result.reference_approved = True
    job.result.keyframes = [MediaAsset(
        asset_id="kf1", kind=MediaAssetKind.KEYFRAME, shot_number=1, created_at=datetime.now(timezone.utc),
        model="image-test", mime_type="image/png", filename="kf1.png", asset_url="/asset/kf1", prompt="p1",
        review_status=MediaAssetReviewStatus.APPROVED, fidelity_report=fidelity_report(1),
    )]
    job.result.required_keyframes = 1
    job.stage = MediaStudioJobStage.READY_FOR_ANIMATION
    mstore.save(job)

    mstore.begin_keyframe_regeneration(job.job_id, 1)
    failed = mstore.update_shot_operation(
        job.job_id, 1, status=ShotOperationStatus.FAILED,
        message="Shot 1 regeneration failed; previous image preserved", error="test failure",
    )

    assert failed.result.keyframes[0].review_status == MediaAssetReviewStatus.APPROVED
    assert failed.result.shot_operations[1].status == ShotOperationStatus.FAILED
    assert failed.result.shot_operations[1].error == "test failure"
    assert failed.result.animation_ready is True


def test_active_shot_operation_blocks_animation_gate(tmp_path):
    _, production = approved_production_job(tmp_path)
    mstore = MediaStudioJobStore(str(tmp_path))
    job = mstore.create(production, Settings())
    job.result.reference_asset = MediaAsset(
        asset_id="ref1", kind=MediaAssetKind.CHARACTER_REFERENCE, created_at=datetime.now(timezone.utc),
        model="image-test", mime_type="image/png", filename="ref1.png", asset_url="/asset/ref1", prompt="prompt",
        review_status=MediaAssetReviewStatus.APPROVED,
    )
    job.result.reference_approved = True
    job.result.keyframes = [MediaAsset(
        asset_id="kf1", kind=MediaAssetKind.KEYFRAME, shot_number=1, created_at=datetime.now(timezone.utc),
        model="image-test", mime_type="image/png", filename="kf1.png", asset_url="/asset/kf1", prompt="p1",
        review_status=MediaAssetReviewStatus.APPROVED, fidelity_report=fidelity_report(1),
    )]
    job.result.required_keyframes = 1
    job.stage = MediaStudioJobStage.READY_FOR_ANIMATION
    mstore.save(job)

    active = mstore.begin_keyframe_regeneration(job.job_id, 1)
    assert active.result.animation_ready is False
    assert active.stage == MediaStudioJobStage.AWAITING_KEYFRAME_REVIEW


def _ready_for_animation_job(tmp_path):
    _, production = approved_production_job(tmp_path)
    mstore = MediaStudioJobStore(str(tmp_path))
    job = mstore.create(production, Settings())
    job.result.reference_asset = MediaAsset(
        asset_id="ref1", kind=MediaAssetKind.CHARACTER_REFERENCE, created_at=datetime.now(timezone.utc),
        model="image-test", mime_type="image/png", filename="ref1.png", asset_url="/asset/ref1", prompt="prompt",
        review_status=MediaAssetReviewStatus.APPROVED,
    )
    job.result.reference_approved = True
    job.result.keyframes = [
        MediaAsset(asset_id="kf1", kind=MediaAssetKind.KEYFRAME, shot_number=1, created_at=datetime.now(timezone.utc), model="image-test", mime_type="image/png", filename="kf1.png", asset_url="/asset/kf1", prompt="p1", review_status=MediaAssetReviewStatus.APPROVED, fidelity_report=fidelity_report(1)),
        MediaAsset(asset_id="kf2", kind=MediaAssetKind.KEYFRAME, shot_number=2, created_at=datetime.now(timezone.utc), model="image-test", mime_type="image/png", filename="kf2.png", asset_url="/asset/kf2", prompt="p2", review_status=MediaAssetReviewStatus.APPROVED, fidelity_report=fidelity_report(2)),
    ]
    job.result.required_keyframes = 2
    job.stage = MediaStudioJobStage.READY_FOR_ANIMATION
    mstore.save(job)
    return mstore, mstore.get(job.job_id)


def test_veo_duration_mapping_uses_supported_lengths():
    service = MediaGenerationService(Settings())
    assert service.supported_video_duration(3) == 4
    assert service.supported_video_duration(4) == 4
    assert service.supported_video_duration(5) == 6
    assert service.supported_video_duration(7) == 8


def test_video_prompt_keeps_identity_and_motion_plan(tmp_path):
    service = MediaGenerationService(Settings())
    _, production = approved_production_job(tmp_path)
    source = MediaStudioJobStore._source_snapshot(production)
    prompt = service.video_prompt(source, source.storyboard.shots[0])
    assert "LOCKED VISUAL IDENTITY" in prompt
    assert "Chinggay" in prompt
    assert "Start from the attached approved keyframe" in prompt
    assert "Camera direction" in prompt


def test_starting_animation_queues_only_missing_shots(tmp_path):
    mstore, job = _ready_for_animation_job(tmp_path)
    started = mstore.begin_clip_generation(job.job_id)
    assert started.stage == MediaStudioJobStage.GENERATING_CLIPS
    assert started.result.clip_operations[1].status == ClipOperationStatus.QUEUED
    assert started.result.clip_operations[2].status == ClipOperationStatus.QUEUED


def test_clip_approval_unlocks_assembly_when_all_clips_approved(tmp_path):
    mstore, job = _ready_for_animation_job(tmp_path)
    now = datetime.now(timezone.utc)
    job.result.video_clips = [
        VideoClipAsset(asset_id="c1", shot_number=1, created_at=now, model="veo-test", filename="c1.mp4", asset_url="/c1", prompt="p", intended_duration_seconds=3, generated_duration_seconds=4, source_keyframe_asset_id="kf1"),
        VideoClipAsset(asset_id="c2", shot_number=2, created_at=now, model="veo-test", filename="c2.mp4", asset_url="/c2", prompt="p", intended_duration_seconds=4, generated_duration_seconds=4, source_keyframe_asset_id="kf2"),
    ]
    job.stage = MediaStudioJobStage.AWAITING_CLIP_REVIEW
    mstore.save(job)
    mstore.approve_clip(job.job_id, 1)
    final = mstore.approve_clip(job.job_id, 2)
    assert final.result.assembly_ready is True
    assert final.stage == MediaStudioJobStage.READY_FOR_ASSEMBLY


def test_local_clip_regeneration_preserves_other_clip_approval(tmp_path):
    mstore, job = _ready_for_animation_job(tmp_path)
    now = datetime.now(timezone.utc)
    job.result.video_clips = [
        VideoClipAsset(asset_id="c1", shot_number=1, created_at=now, model="veo-test", filename="c1.mp4", asset_url="/c1", prompt="p", intended_duration_seconds=3, generated_duration_seconds=4, source_keyframe_asset_id="kf1", review_status=MediaAssetReviewStatus.APPROVED),
        VideoClipAsset(asset_id="c2", shot_number=2, created_at=now, model="veo-test", filename="c2.mp4", asset_url="/c2", prompt="p", intended_duration_seconds=4, generated_duration_seconds=4, source_keyframe_asset_id="kf2", review_status=MediaAssetReviewStatus.APPROVED),
    ]
    job.stage = MediaStudioJobStage.READY_FOR_ASSEMBLY
    mstore.save(job)
    local = mstore.begin_clip_regeneration(job.job_id, 1)
    clips = {clip.shot_number: clip for clip in local.result.video_clips}
    assert clips[1].review_status == MediaAssetReviewStatus.NEEDS_REVIEW
    assert clips[2].review_status == MediaAssetReviewStatus.APPROVED
    assert local.result.clip_operations[1].status == ClipOperationStatus.GENERATING
    assert local.stage == MediaStudioJobStage.AWAITING_CLIP_REVIEW


def _animation_ready_job(tmp_path):
    _, production = approved_production_job(tmp_path)
    mstore = MediaStudioJobStore(str(tmp_path))
    job = mstore.create(production, Settings())
    job.result.reference_asset = MediaAsset(
        asset_id="ref1", kind=MediaAssetKind.CHARACTER_REFERENCE, created_at=datetime.now(timezone.utc),
        model="image-test", mime_type="image/png", filename="ref1.png", asset_url="/asset/ref1", prompt="prompt",
        review_status=MediaAssetReviewStatus.APPROVED,
    )
    job.result.reference_approved = True
    job.result.keyframes = [
        MediaAsset(asset_id="kf1", kind=MediaAssetKind.KEYFRAME, shot_number=1, created_at=datetime.now(timezone.utc), model="image-test", mime_type="image/png", filename="kf1.png", asset_url="/asset/kf1", prompt="p1", fidelity_report=fidelity_report(1), review_status=MediaAssetReviewStatus.APPROVED),
        MediaAsset(asset_id="kf2", kind=MediaAssetKind.KEYFRAME, shot_number=2, created_at=datetime.now(timezone.utc), model="image-test", mime_type="image/png", filename="kf2.png", asset_url="/asset/kf2", prompt="p2", fidelity_report=fidelity_report(2), review_status=MediaAssetReviewStatus.APPROVED),
    ]
    job.result.required_keyframes = 2
    job.result.approved_keyframes = 2
    job.result.fidelity_reviewed_keyframes = 2
    job.result.fidelity_passed_keyframes = 2
    job.result.animation_ready = True
    job.stage = MediaStudioJobStage.READY_FOR_ANIMATION
    mstore.save(job)
    return mstore, mstore.get(job.job_id)


def test_failed_initial_clip_stays_in_clip_review_instead_of_bouncing_to_animation(tmp_path):
    mstore, job = _animation_ready_job(tmp_path)
    started = mstore.begin_clip_generation(job.job_id)
    assert started.stage == MediaStudioJobStage.GENERATING_CLIPS
    mstore.update_clip_operation(
        job.job_id, 1,
        status=ClipOperationStatus.FAILED,
        message="Shot 1 failed",
        error="regional endpoint mismatch",
    )
    # Mark the other queued shot failed too so no active operations remain.
    mstore.update_clip_operation(
        job.job_id, 2,
        status=ClipOperationStatus.FAILED,
        message="Shot 2 failed",
        error="regional endpoint mismatch",
    )
    refreshed = mstore.get(job.job_id)
    assert refreshed.stage == MediaStudioJobStage.AWAITING_CLIP_REVIEW
    assert "failed" in refreshed.message.lower()


def test_failed_initial_clip_can_be_retried_without_existing_video_asset(tmp_path):
    mstore, job = _animation_ready_job(tmp_path)
    started = mstore.begin_clip_generation(job.job_id)
    mstore.update_clip_operation(
        job.job_id, 1,
        status=ClipOperationStatus.FAILED,
        message="Shot 1 failed",
        error="regional endpoint mismatch",
    )
    # Shot 2 remains queued; stop it for an isolated retry test.
    mstore.update_clip_operation(
        job.job_id, 2,
        status=ClipOperationStatus.FAILED,
        message="Shot 2 failed",
        error="regional endpoint mismatch",
    )
    retry = mstore.begin_clip_regeneration(job.job_id, 1)
    op = retry.result.clip_operations[1]
    assert op.status == ClipOperationStatus.GENERATING
    assert op.target_generation_attempt == 2
    assert not retry.result.video_clips


def test_latest_media_job_for_production_brief_survives_store_restart(tmp_path):
    _, production = approved_production_job(tmp_path)
    first_store = MediaStudioJobStore(str(tmp_path))
    first = first_store.create(production, Settings())
    second = first_store.create(production, Settings())

    restarted = MediaStudioJobStore(str(tmp_path))
    latest = restarted.latest_for_production_brief(production.job_id)
    assert latest is not None
    assert latest.job_id == second.job_id
    assert latest.production_brief_job_id == production.job_id
    assert latest.job_id != first.job_id


def test_contact_critical_regeneration_prompt_requires_visible_contact_and_exact_count(tmp_path):
    service = MediaGenerationService(Settings())
    _, production = approved_production_job(tmp_path)
    source = MediaStudioJobStore._source_snapshot(production)
    shot = source.storyboard.shots[0].model_copy(update={
        "visual_action": "Chinggay nudges one of two miniature treat bags with her snout.",
        "camera_direction": "Medium-close shot of snout and bags",
        "generation_prompt": "Exactly two colorful bags near the cabin window.",
    })
    prompt = service.keyframe_prompt(
        source,
        shot,
        corrective_instruction="Snout is hovering beside the treat bags; make direct contact.",
    )
    assert "Change only what is necessary" in prompt
    assert "Do not redesign the character" in prompt
    assert "INSTANT OF CONTACT" in prompt
    assert "NO AIR GAP" in prompt
    assert "exact stated count" in prompt
    assert "one of two miniature treat bags" in prompt
    assert "Snout is hovering" in prompt


def test_contact_critical_instructions_preserve_standard_prompt(tmp_path):
    service = MediaGenerationService(Settings())
    _, production = approved_production_job(tmp_path)
    source = MediaStudioJobStore._source_snapshot(production)
    prompt = service.keyframe_prompt(source, source.storyboard.shots[0])
    assert "LOCK" in prompt
    assert "Chinggay" in prompt
    assert "PRIMARY ACTION" in prompt
    assert "FINAL FRAME VALIDATION" in prompt
