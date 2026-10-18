from types import SimpleNamespace as Obj
import pytest
from fastapi import HTTPException
from app.api.routes.ai_review import _require_complete_creator_review_chain
from app.models.media_studio import MediaAssetReviewStatus, KeyframeFidelityStatus
from app.models.final_assembly import FinalAssemblyJobStage


def node(**kwargs):
    return Obj(**kwargs)


def approved_chain():
    frame = node(review_status=MediaAssetReviewStatus.APPROVED, fidelity_report=node(status=KeyframeFidelityStatus.PASS))
    clip = node(shot_number=1, asset_id="clip1", review_status=MediaAssetReviewStatus.APPROVED)
    plan = node(job_id="plan", result=node(review_status=node(value="APPROVED")))
    media = node(job_id="media", result=node(reference_approved=True,
        reference_asset=node(review_status=MediaAssetReviewStatus.APPROVED),
        required_keyframes=1, keyframes=[frame], required_clips=1, video_clips=[clip]))
    assembly = node(job_id="assembly", media_job_id="media", production_brief_job_id="plan",
        stage=FinalAssemblyJobStage.DELIVERED,
        result=node(review_status=node(value="APPROVED"), timeline=[node(shot_number=1,source_clip_asset_id="clip1")]))
    audio = node(assembly_job_id="assembly")
    return dict(audio_job=audio, assembly_job=assembly, media_job=media, production_job=plan)


def test_creator_chain_accepts_approved_current_assets():
    _require_complete_creator_review_chain(**approved_chain())


def test_creator_chain_rejects_stale_clip_lineage():
    chain=approved_chain()
    chain["assembly_job"].result.timeline[0].source_clip_asset_id="old"
    with pytest.raises(HTTPException, match="outdated"):
        _require_complete_creator_review_chain(**chain)


def test_creator_chain_rejects_unapproved_keyframe():
    chain=approved_chain()
    chain["media_job"].result.keyframes[0].review_status=MediaAssetReviewStatus.NEEDS_REVIEW
    with pytest.raises(HTTPException, match="keyframes"):
        _require_complete_creator_review_chain(**chain)
