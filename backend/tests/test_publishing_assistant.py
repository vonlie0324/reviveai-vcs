from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.models.publishing_assistant import (
    InstagramPublishingCopy,
    PublishingDraft,
    PublishingDraftContent,
    PublishingDraftStatus,
    TikTokPublishingCopy,
    YouTubePublishingCopy,
)
from app.services import publishing_assistant_service as svc


class _MemoryDraftCloud:
    """Strictly local repository for publishing-version unit tests."""
    def __init__(self):
        self.rows = {}
    def save(self, key, payload):
        self.rows[key] = payload
    def load(self, key):
        return self.rows.get(key)
    def stream(self):
        return iter(self.rows.items())


def _isolated_store(root):
    store = svc.PublishingDraftStore(root)
    store._cloud = _MemoryDraftCloud()
    return store


def _content(title: str = "Title", description: str = "Description") -> PublishingDraftContent:
    return PublishingDraftContent(
        youtube=YouTubePublishingCopy(
            title=title,
            description=description,
            hashtags=["#ReviveAI"],
            tags=["pets"],
            thumbnail_text_suggestions=["Welcome aboard"],
        ),
        tiktok=TikTokPublishingCopy(
            hook="POV: cutest flight crew",
            caption="Welcome aboard.",
            hashtags=["#PetTok"],
            cta="Would you board?",
        ),
        instagram=InstagramPublishingCopy(
            caption_short="Welcome aboard!",
            caption_long="A tiny flight attendant welcomes everyone aboard.",
            hashtags=["#PetReels"],
            alt_text="A small dog dressed as a flight attendant inside an airplane cabin.",
            cta="Save this for your next smile.",
        ),
    )


def _draft(draft_id: str = "draft_1", version: int = 1, status: PublishingDraftStatus = PublishingDraftStatus.DRAFT) -> PublishingDraft:
    now = datetime.now(timezone.utc)
    return PublishingDraft(
        draft_id=draft_id,
        assembly_job_id="assembly_1",
        audio_job_id="audio_1",
        audio_version=10,
        source_package_id="pkg_1",
        source_package_version=1,
        qc_report_id="qc_1",
        version_number=version,
        generated_at=now,
        updated_at=now,
        model="gemini-test",
        content=_content(),
        status=status,
    )


def test_publishing_draft_store_persists_and_orders_versions(tmp_path, monkeypatch):
    store = _isolated_store(str(tmp_path / "checkpoints"))
    monkeypatch.setattr(svc.audio_finishing_job_store, "get", lambda _job_id: SimpleNamespace(assembly_job_id="assembly_1"))
    store.save(_draft("draft_1", 1))
    store.save(_draft("draft_2", 2))

    items = store.list_for_audio_job("audio_1")
    assert [item.version_number for item in items] == [2, 1]
    assert store.get("draft_1").content.youtube.title == "Title"


def test_manual_edit_creates_new_version_without_overwriting_base(tmp_path, monkeypatch):
    store = _isolated_store(str(tmp_path / "checkpoints"))
    monkeypatch.setattr(svc, "publishing_draft_store", store)
    monkeypatch.setattr(svc.audio_finishing_job_store, "get", lambda _job_id: SimpleNamespace(assembly_job_id="assembly_1"))
    base = _draft()
    store.save(base)
    service = svc.PublishingAssistantService(Settings(content_dna_checkpoint_dir=str(tmp_path / "checkpoints")))
    source = (
        SimpleNamespace(assembly_job_id="assembly_1", job_id="audio_1", version_number=10),
        SimpleNamespace(report_id="qc_1"),
        SimpleNamespace(package_id="pkg_1", package_version=1),
        SimpleNamespace(),
    )
    monkeypatch.setattr(service, "_validate_source", lambda _audio_job_id: source)

    edited = _content(title="Creator title")
    next_draft = service.update(base.draft_id, edited)

    assert next_draft.version_number == 2
    assert next_draft.based_on_draft_id == base.draft_id
    assert next_draft.content.youtube.title == "Creator title"
    assert store.get(base.draft_id).content.youtube.title == "Title"


@pytest.mark.asyncio
async def test_selective_regeneration_preserves_unselected_fields(tmp_path, monkeypatch):
    store = _isolated_store(str(tmp_path / "checkpoints"))
    monkeypatch.setattr(svc, "publishing_draft_store", store)
    monkeypatch.setattr(svc.audio_finishing_job_store, "get", lambda _job_id: SimpleNamespace(assembly_job_id="assembly_1"))
    base = _draft()
    store.save(base)
    service = svc.PublishingAssistantService(Settings(content_dna_checkpoint_dir=str(tmp_path / "checkpoints")))
    source = (
        SimpleNamespace(assembly_job_id="assembly_1", job_id="audio_1", version_number=10),
        SimpleNamespace(report_id="qc_1"),
        SimpleNamespace(package_id="pkg_1", package_version=1),
        SimpleNamespace(),
    )
    monkeypatch.setattr(service, "_validate_source", lambda _audio_job_id: source)
    monkeypatch.setattr(service, "_prompt", lambda *args, **kwargs: "prompt")
    source[0].production_brief_job_id = "brief_1"
    source[0].channel_id = "channel_test"

    candidate = _content(title="New AI title", description="AI replaced description")

    async def fake_generate(_prompt: str, *, production_id: str, channel_id: str):
        assert production_id == "brief_1"
        assert channel_id == "channel_test"
        return candidate

    monkeypatch.setattr(service, "_generate", fake_generate)
    next_draft = await service.regenerate(base.draft_id, ["youtube.title"])

    assert next_draft.content.youtube.title == "New AI title"
    assert next_draft.content.youtube.description == base.content.youtube.description
    assert next_draft.content.tiktok.caption == base.content.tiktok.caption


def test_approval_marks_exact_version_without_creating_another(tmp_path, monkeypatch):
    store = _isolated_store(str(tmp_path / "checkpoints"))
    monkeypatch.setattr(svc, "publishing_draft_store", store)
    base = _draft()
    store.save(base)
    service = svc.PublishingAssistantService(Settings(content_dna_checkpoint_dir=str(tmp_path / "checkpoints")))
    monkeypatch.setattr(service, "_validate_source", lambda _audio_job_id: (SimpleNamespace(), SimpleNamespace(), SimpleNamespace(), SimpleNamespace()))

    approved = service.approve(base.draft_id)
    assert approved.status == PublishingDraftStatus.APPROVED
    assert approved.approved_at is not None
    assert approved.version_number == 1


def test_edit_as_new_version_preserves_approved_draft(tmp_path, monkeypatch):
    store = _isolated_store(str(tmp_path / "checkpoints"))
    monkeypatch.setattr(svc, "publishing_draft_store", store)
    monkeypatch.setattr(svc.audio_finishing_job_store, "get", lambda _job_id: SimpleNamespace(assembly_job_id="assembly_1"))
    approved_base = _draft(status=PublishingDraftStatus.APPROVED)
    approved_base.approved_at = datetime.now(timezone.utc)
    store.save(approved_base)

    service = svc.PublishingAssistantService(Settings(content_dna_checkpoint_dir=str(tmp_path / "checkpoints")))
    source = (
        SimpleNamespace(assembly_job_id="assembly_1", job_id="audio_1", version_number=10),
        SimpleNamespace(report_id="qc_1"),
        SimpleNamespace(package_id="pkg_2", package_version=2),
        SimpleNamespace(),
    )
    monkeypatch.setattr(service, "_validate_source", lambda _audio_job_id: source)

    fork = service.update(approved_base.draft_id, approved_base.content.model_copy(deep=True))

    assert fork.version_number == 2
    assert fork.status == PublishingDraftStatus.DRAFT
    assert fork.based_on_draft_id == approved_base.draft_id
    assert fork.source_package_version == 2
    persisted_base = store.get(approved_base.draft_id)
    assert persisted_base.status == PublishingDraftStatus.APPROVED
    assert persisted_base.approved_at == approved_base.approved_at
    assert persisted_base.content == approved_base.content
