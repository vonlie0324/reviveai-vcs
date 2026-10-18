from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from app.core.firebase_clients import get_runtime_firestore_client
from app.core.tenant import tenant_namespace
from app.services.firestore_job_repository import FirestoreJobRepository


LEGACY_PREFIXES = ("production_", "assembly_", "media_")


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _timestamp(value: Any) -> float:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    if value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except (TypeError, ValueError):
            pass
    return 0.0


def _candidate_ids(value: str | None) -> set[str]:
    raw = str(value or "").strip()
    if not raw:
        return set()
    values = {raw}
    for prefix in LEGACY_PREFIXES:
        if raw.startswith(prefix) and len(raw) > len(prefix):
            values.add(raw[len(prefix):])
    return values


class ProductionCostDashboardService:
    """Tenant-aware production-cost aggregation.

    The cost ledger is a legacy root-level Firestore collection, while current
    ReviveAI runtime records (publications, production briefs and autonomous
    activity) are tenant scoped. This service uses the tenant-scoped lineage as
    the authority and only admits root cost transactions that belong to that
    lineage (or that were written with the current tenantNamespace field).

    This prevents cross-tenant leakage and also guarantees that a published
    production remains visible even when its provider-cost record is missing.
    """

    def __init__(self) -> None:
        self.db = get_runtime_firestore_client()
        self.namespace = tenant_namespace()
        self.publications = FirestoreJobRepository("youtube_publications")
        self.activity = FirestoreJobRepository("autonomous_activity_events")
        self.production_briefs = FirestoreJobRepository("production_brief_jobs")

    @staticmethod
    def _safe_stream(repo: FirestoreJobRepository) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        try:
            for _doc_id, payload in repo.stream():
                if isinstance(payload, dict):
                    values.append(payload)
        except Exception:
            # Dashboard reads should degrade to the remaining durable sources.
            pass
        return values

    @staticmethod
    def _brief_title(payload: dict[str, Any]) -> str | None:
        result = payload.get("result") or {}
        creative = result.get("creative_direction") or {}
        title = creative.get("working_title")
        if title:
            return str(title)
        source = payload.get("source_snapshot") or {}
        recommendation = source.get("recommendation") or {}
        for key in ("working_title", "title", "idea_title"):
            if recommendation.get(key):
                return str(recommendation[key])
        return None

    def _lineage(self) -> tuple[
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
        set[str],
    ]:
        """Return rows, publications by production, briefs, and known production IDs."""
        approval_events = [
            event
            for event in self._safe_stream(self.activity)
            if str(event.get("action") or "") == "AUTONOMOUS_FINAL_APPROVAL"
        ]

        approval_by_recommendation: dict[str, dict[str, Any]] = {}
        approval_by_package: dict[str, dict[str, Any]] = {}
        approval_by_draft: dict[str, dict[str, Any]] = {}
        for event in sorted(approval_events, key=lambda x: _timestamp(x.get("occurred_at"))):
            if event.get("recommendation_id"):
                approval_by_recommendation[str(event["recommendation_id"])] = event
            if event.get("package_id"):
                approval_by_package[str(event["package_id"])] = event
            if event.get("publishing_draft_id"):
                approval_by_draft[str(event["publishing_draft_id"])] = event

        briefs: dict[str, dict[str, Any]] = {}
        for brief in self._safe_stream(self.production_briefs):
            job_id = str(brief.get("job_id") or "").strip()
            if job_id:
                briefs[job_id] = brief

        rows: dict[str, dict[str, Any]] = {}
        publications_by_production: dict[str, dict[str, Any]] = {}
        known_ids: set[str] = set()

        # Every tenant-scoped production brief is valid production history, even if
        # it never reached YouTube. Seeding these IDs preserves older/manual cost
        # rows while still preventing global root-ledger leakage across tenants.
        for production_id, brief in briefs.items():
            known_ids.add(production_id)
            rows.setdefault(
                production_id,
                self._base_row(
                    production_id=production_id,
                    title=self._brief_title(brief) or production_id,
                    created_at=brief.get("created_at") or brief.get("updated_at"),
                    status=str(brief.get("stage") or "PRODUCTION"),
                ),
            )

        # Seed lineage from final-approval events. These events already contain the
        # production/media/assembly/audio/package identifiers for legacy publications.
        for event in approval_events:
            production_id = str(event.get("production_job_id") or "").strip()
            if not production_id:
                continue
            known_ids.add(production_id)
            brief = briefs.get(production_id) or {}
            rows.setdefault(
                production_id,
                self._base_row(
                    production_id=production_id,
                    title=self._brief_title(brief) or production_id,
                    created_at=event.get("occurred_at"),
                    status="APPROVED",
                ),
            )

        # Publications are authoritative for the release list. New records carry
        # production_job_id directly; legacy records are repaired in-memory by the
        # final-approval event that shares recommendation/package/draft lineage.
        for publication in self._safe_stream(self.publications):
            approval = None
            recommendation_id = str(publication.get("recommendation_id") or "").strip()
            package_id = str(publication.get("package_id") or "").strip()
            draft_id = str(publication.get("publishing_draft_id") or "").strip()
            if recommendation_id:
                approval = approval_by_recommendation.get(recommendation_id)
            if approval is None and package_id:
                approval = approval_by_package.get(package_id)
            if approval is None and draft_id:
                approval = approval_by_draft.get(draft_id)

            production_id = str(
                publication.get("production_job_id")
                or (approval or {}).get("production_job_id")
                or ""
            ).strip()
            if not production_id:
                # Keep the release visible even if a very old publication predates
                # lineage events. A publication-scoped row is safer than hiding it.
                production_id = f"publication:{publication.get('publication_id') or recommendation_id or package_id}"

            known_ids.add(production_id)
            publication = dict(publication)
            if approval:
                for key in ("production_job_id", "media_job_id", "assembly_job_id", "audio_job_id"):
                    if not publication.get(key) and approval.get(key):
                        publication[key] = approval[key]

            brief = briefs.get(str(publication.get("production_job_id") or production_id)) or {}
            row = rows.setdefault(
                production_id,
                self._base_row(
                    production_id=production_id,
                    title=(
                        publication.get("video_title")
                        or self._brief_title(brief)
                        or production_id
                    ),
                    created_at=publication.get("created_at"),
                    status=str(publication.get("status") or "UNKNOWN"),
                ),
            )
            row.update(
                {
                    "title": publication.get("video_title") or row["title"],
                    "status": str(publication.get("status") or row["status"]),
                    "publication_id": publication.get("publication_id"),
                    "youtube_video_id": publication.get("youtube_video_id"),
                    "youtube_url": publication.get("youtube_url"),
                    "release_at": (
                        _iso(publication.get("public_release_at"))
                        or _iso(publication.get("public_confirmed_at"))
                        or _iso(publication.get("published_at"))
                        or _iso(publication.get("publish_at"))
                    ),
                    "created_at": _iso(publication.get("created_at")) or row.get("created_at"),
                    "production_job_id": publication.get("production_job_id") or production_id,
                    "media_job_id": publication.get("media_job_id"),
                    "assembly_job_id": publication.get("assembly_job_id"),
                    "audio_job_id": publication.get("audio_job_id"),
                    "package_id": publication.get("package_id"),
                    "recommendation_id": publication.get("recommendation_id"),
                }
            )
            publications_by_production[production_id] = publication

        return rows, publications_by_production, briefs, known_ids

    @staticmethod
    def _base_row(*, production_id: str, title: str, created_at: Any, status: str) -> dict[str, Any]:
        return {
            "id": production_id,
            "production_job_id": production_id,
            "title": title,
            "status": status,
            "provider": None,
            "model": None,
            "created_at": _iso(created_at),
            "release_at": None,
            "publication_id": None,
            "youtube_video_id": None,
            "youtube_url": None,
            "media_job_id": None,
            "assembly_job_id": None,
            "audio_job_id": None,
            "package_id": None,
            "recommendation_id": None,
            "estimated_cost": 0.0,
            "actual_cost": 0.0,
            "reserved_cost": 0.0,
            "variance": 0.0,
            "cost_status": "UNAVAILABLE",
            "transaction_count": 0,
        }

    def _match_transaction_production(self, item: dict[str, Any], known_ids: set[str]) -> str | None:
        raw_id = str(item.get("productionId") or "").strip()
        if not raw_id:
            return None

        # New writes are explicitly tenant tagged.
        if str(item.get("tenantNamespace") or "").strip() == self.namespace:
            for candidate in _candidate_ids(raw_id):
                if candidate in known_ids:
                    return candidate
            return raw_id

        # Legacy writes have no tenant tag. Only admit them if they match a
        # production ID established by this tenant's own lineage.
        for candidate in _candidate_ids(raw_id):
            if candidate in known_ids:
                return candidate
        return None

    def _transactions(self, known_ids: set[str]) -> Iterable[tuple[str, Any, dict[str, Any]]]:
        for snap in self.db.collection("production_cost_transactions").stream():
            item = snap.to_dict() or {}
            production_id = self._match_transaction_production(item, known_ids)
            if production_id:
                yield production_id, snap, item

    def get_dashboard(self) -> dict[str, Any]:
        rows, _publications, briefs, known_ids = self._lineage()

        for production_id, _snap, item in self._transactions(known_ids):
            known_ids.add(production_id)
            brief = briefs.get(production_id) or {}
            row = rows.setdefault(
                production_id,
                self._base_row(
                    production_id=production_id,
                    title=(
                        item.get("title")
                        or item.get("productionTitle")
                        or self._brief_title(brief)
                        or production_id
                    ),
                    created_at=item.get("createdAt"),
                    status=str(item.get("status") or "UNKNOWN"),
                ),
            )

            estimated = _as_float(item.get("estimatedCost"))
            actual = _as_float(item.get("actualCost"))
            row["estimated_cost"] += estimated
            row["actual_cost"] += actual
            row["transaction_count"] += 1
            if str(item.get("status") or "").upper() in {"RESERVED", "CLAIMED"}:
                row["reserved_cost"] += estimated

            # Publication status/title remains authoritative when present.
            if not row.get("publication_id"):
                row["status"] = str(item.get("status") or row["status"])
                if item.get("title") or item.get("productionTitle"):
                    row["title"] = item.get("title") or item.get("productionTitle")
            row["provider"] = item.get("provider") or row.get("provider")
            row["model"] = item.get("model") or row.get("model")
            row["created_at"] = _iso(item.get("createdAt")) or row.get("created_at")
            row["cost_status"] = "RECORDED"

        total_allocated = 0.0
        total_reserved = 0.0
        total_budget_spent = 0.0
        for production_id in known_ids:
            if production_id.startswith("publication:"):
                continue
            try:
                snap = (
                    self.db.collection("productions")
                    .document(production_id)
                    .collection("system")
                    .document("budget")
                    .get()
                )
                if not snap.exists:
                    continue
                budget = snap.to_dict() or {}
                total_allocated += _as_float(budget.get("allocated"))
                total_reserved += _as_float(budget.get("reserved"))
                total_budget_spent += _as_float(budget.get("spent"))
            except Exception:
                continue

        output = list(rows.values())
        for row in output:
            row["estimated_cost"] = round(_as_float(row["estimated_cost"]), 2)
            row["actual_cost"] = round(_as_float(row["actual_cost"]), 2)
            row["reserved_cost"] = round(_as_float(row["reserved_cost"]), 2)
            row["variance"] = round(row["actual_cost"] - row["estimated_cost"], 2)

        output.sort(
            key=lambda row: (
                _timestamp(row.get("release_at")),
                _timestamp(row.get("created_at")),
                str(row.get("title") or ""),
            ),
            reverse=True,
        )

        total_spend = round(sum(_as_float(row["actual_cost"]) for row in output), 2)
        costed = [row for row in output if int(row.get("transaction_count") or 0) > 0]
        average_cost = round(
            sum(_as_float(row["actual_cost"]) for row in costed) / len(costed), 2
        ) if costed else 0.0
        remaining = max(0.0, total_allocated - total_reserved - total_budget_spent)

        return {
            "total_spend": total_spend,
            "reserved_budget": round(total_reserved, 2),
            "remaining_budget": round(remaining, 2),
            "average_cost_per_video": average_cost,
            "productions": output,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_detail(self, production_id: str) -> dict[str, Any]:
        dashboard = self.get_dashboard()
        row = next((item for item in dashboard["productions"] if item["id"] == production_id), None)
        if row is None:
            return {
                "production_id": production_id,
                "title": production_id,
                "status": "NOT_FOUND",
                "estimated_cost": 0.0,
                "actual_cost": 0.0,
                "variance": 0.0,
                "operations": [],
                "transactions": [],
            }

        known_ids = {str(item["id"]) for item in dashboard["productions"]}
        transactions: list[dict[str, Any]] = []
        for matched_id, snap, item in self._transactions(known_ids):
            if matched_id != production_id:
                continue
            estimated = _as_float(item.get("estimatedCost"))
            actual = _as_float(item.get("actualCost"))
            transactions.append(
                {
                    "id": snap.id,
                    "operation_id": item.get("providerOperationName") or item.get("operationId") or snap.id,
                    "provider": item.get("provider"),
                    "model": item.get("model"),
                    "status": item.get("status"),
                    "estimated_cost": round(estimated, 2),
                    "actual_cost": round(actual, 2),
                    "variance": round(actual - estimated, 2),
                    "created_at": _iso(item.get("createdAt")),
                    "completed_at": _iso(item.get("completedAt") or item.get("reconciledAt") or item.get("releasedAt")),
                }
            )

        transactions.sort(key=lambda item: _timestamp(item.get("created_at")), reverse=True)
        return {
            **row,
            "production_id": production_id,
            "operations": transactions,
            "transactions": transactions,
            "summary": {
                "estimated_cost": row["estimated_cost"],
                "actual_cost": row["actual_cost"],
                "variance": row["variance"],
                "health": "HEALTHY" if row["variance"] <= 0 else "WARNING",
            },
        }

    def get_timeline(self, production_id: str) -> dict[str, Any]:
        detail = self.get_detail(production_id)
        return {
            "production_id": production_id,
            "events": [
                {
                    "type": item.get("status"),
                    "timestamp": item.get("completed_at") or item.get("created_at"),
                    "cost": item.get("actual_cost") or item.get("estimated_cost"),
                }
                for item in detail.get("transactions", [])
            ],
        }
