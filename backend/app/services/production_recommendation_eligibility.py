"""Read-only eligibility checks for new production recommendations.

Existing legacy briefs count as started even when they failed or stopped early.
History failures are explicit: never treat unavailable Firestore as an empty history.
"""
from __future__ import annotations

import re
import unicodedata

from app.services.production_brief_job_service import production_brief_job_store


def normalized_title(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def already_started(recommendation, entry, recovery_job_id: str) -> bool:
    prior = entry.source_snapshot.recommendation
    # Recommendation IDs can be reused by different recovery runs. They are
    # only authoritative in conjunction with the recovery job ID.
    if entry.recovery_job_id == recovery_job_id and prior.recommendation_id == recommendation.recommendation_id:
        return True
    if (getattr(prior, "canonical_idea_id", None) and
        getattr(prior, "canonical_idea_id", None) == getattr(recommendation, "canonical_idea_id", None)):
        return True
    # Older records commonly lack canonical IDs; normalized exact titles are
    # deliberately conservative for new-production discovery.
    target = normalized_title(recommendation.title)
    if target and target in {
        normalized_title(prior.title), normalized_title(entry.working_title)
    }:
        return True
    return False


def authoritative_history(channel_id: str):
    """Return all verified tenant production entries, or raise on cloud outage.

    ProductionBriefJobStore.list_history ordinarily swallows Firestore errors and
    falls back to local files. That fallback is valuable for recovery but unsafe
    for uniqueness checks, so first require a successful cloud enumeration.
    """
    store = production_brief_job_store
    # A successful Firestore read is mandatory before considering a new job.
    # Include legacy local snapshots after cloud availability is verified.
    list(store._cloud.stream())
    return store.list_history(channel_id=channel_id)


def is_eligible(recommendation, recovery_job_id: str, history) -> bool:
    return not any(already_started(recommendation, entry, recovery_job_id) for entry in history)
