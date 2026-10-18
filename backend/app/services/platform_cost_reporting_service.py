"""Bounded, read-only administrative view over legacy root production-cost entries.

Channel IDs originate from transaction records. Tenant associations are accepted only
when they match an existing tenant-scoped saved YouTube connection. This is a
ledger snapshot, not a verified provider invoice.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.firebase_clients import get_runtime_firestore_client
from app.core.tenant import normalize_tenant_namespace, tenant_namespace

MAX_SCAN = 2000
MAX_TENANT_CONNECTION_SCAN = 500


def _money(value: Any) -> Decimal:
    try:
        result = Decimal(str(value if value is not None else 0))
        return result if result.is_finite() and result >= 0 else Decimal(0)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)


def _namespace(value: Any) -> str | None:
    try:
        return normalize_tenant_namespace(str(value or ""))
    except Exception:
        return None


def _cost(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))




def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / (1000 if value > 1e11 else 1), tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _transaction_time(item: dict) -> datetime | None:
    return _timestamp(item.get("createdAt")) or _timestamp(item.get("updatedAt"))


def _verified_owners(namespaces: set[str], *, max_users: int = 2000) -> tuple[dict[str, dict], bool]:
    """Resolve namespace by hashing Firebase UID; never guess by email/channel title."""
    if not namespaces:
        return {}, False
    from app.core.config import get_settings
    from app.core.firebase_auth import firebase_admin_auth
    auth, app = firebase_admin_auth(get_settings())
    matched: dict[str, dict] = {}
    duplicates: set[str] = set()
    count = 0
    page = auth.list_users(max_results=1000, app=app)
    truncated = False
    while True:
        for user in page.users:
            count += 1
            if count > max_users:
                truncated = True
                break
            ns = tenant_namespace(user.uid)
            if ns in namespaces:
                if ns in matched:
                    duplicates.add(ns)
                else:
                    matched[ns] = {"uid": user.uid, "display_name": user.display_name or user.email or "Unnamed user"}
        if truncated or not page.next_page_token:
            break
        page = auth.list_users(page_token=page.next_page_token, max_results=1000, app=app)
    for ns in duplicates:
        matched.pop(ns, None)
    return matched, truncated

def _saved_connections(db, requested_channels: set[str]) -> tuple[dict[str, list[dict]], bool]:
    """Read only known tenant connection documents; never return OAuth tokens."""
    matches: dict[str, list[dict]] = defaultdict(list)
    if not requested_channels:
        return matches, False
    collection = db.collection("reviveai_tenants")
    # Firestore permits subcollections below absent parent documents. Streaming
    # parent snapshots skips those namespaces; list_documents discovers them.
    tenant_refs = []
    for tenant_ref in collection.list_documents():
        tenant_refs.append(tenant_ref)
        if len(tenant_refs) > MAX_TENANT_CONNECTION_SCAN:
            break
    truncated = len(tenant_refs) > MAX_TENANT_CONNECTION_SCAN
    for tenant_ref in tenant_refs[:MAX_TENANT_CONNECTION_SCAN]:
        ns = _namespace(tenant_ref.id)
        if not ns:
            continue
        doc = tenant_ref.collection("youtube_connections").document("connection").get()
        if not doc.exists:
            continue
        wrapper = doc.to_dict() or {}
        payload = wrapper.get("payload_json")
        if isinstance(payload, str):
            try:
                connection = json.loads(payload)
            except (ValueError, TypeError):
                continue
        elif "channel_id" in wrapper:
            connection = wrapper
        else:
            continue
        if not isinstance(connection, dict):
            continue
        channel_id = str(connection.get("channel_id") or "").strip()
        if channel_id in requested_channels:
            matches[channel_id].append({"tenant_namespace": ns, "channel_title": str(connection.get("channel_title") or "").strip() or None})
    return matches, truncated


def get_platform_cost_snapshot(limit: int = 500, from_date: date | None = None, to_date: date | None = None) -> dict[str, Any]:
    limit = max(1, min(int(limit), MAX_SCAN))
    if from_date and to_date and from_date > to_date:
        raise ValueError("from_date cannot be after to_date")
    db = get_runtime_firestore_client()
    documents = list(db.collection("production_cost_transactions").limit(limit + 1).stream())
    has_more = len(documents) > limit
    documents = documents[:limit]
    entries_all = [(doc.id, doc.to_dict() or {}) for doc in documents]
    entries = []
    undated = 0
    daily: dict[str, dict[str, Any]] = {}
    for ident, data in entries_all:
        when = _transaction_time(data)
        if when is None:
            undated += 1
            if from_date or to_date:
                continue  # never invent a timestamp for an undated historical row
        elif (from_date and when.date() < from_date) or (to_date and when.date() > to_date):
            continue
        entries.append((ident, data))
        if when is not None:
            day = when.date().isoformat()
            record = daily.setdefault(day, {"date": day, "actual": Decimal(0), "estimated": Decimal(0), "reserved": Decimal(0), "transactions": 0})
            record["actual"] += _money(data.get("actualCost"))
            record["estimated"] += _money(data.get("estimatedCost"))
            record["reserved"] += _money(data.get("estimatedCost")) if str(data.get("status") or "").upper() in {"RESERVED", "CLAIMED"} else Decimal(0)
            record["transactions"] += 1
    channel_ids = {str(v.get("channelId") or "").strip() for _, v in entries if str(v.get("channelId") or "").strip()}
    connections, connections_truncated = _saved_connections(db, channel_ids)
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    total_actual = total_estimated = total_reserved = Decimal(0)
    for transaction_id, item in entries:
        explicit_ns = _namespace(item.get("tenantNamespace"))
        channel_id = str(item.get("channelId") or "").strip() or None
        owners = connections.get(channel_id, []) if channel_id else []
        matched = [x for x in owners if x["tenant_namespace"] == explicit_ns] if explicit_ns else owners
        if channel_id and len(matched) == 1 and (explicit_ns or len(owners) == 1):
            attribution = "CHANNEL_CONNECTION_MATCH"
            tenant_ns = matched[0]["tenant_namespace"]
            channel_title = matched[0]["channel_title"]
        elif channel_id:
            attribution = "CHANNEL_ID_ONLY"
            tenant_ns = explicit_ns
            channel_title = None
        elif explicit_ns:
            attribution = "TENANT"
            tenant_ns = explicit_ns
            channel_title = None
        else:
            attribution = "UNATTRIBUTED"
            tenant_ns = None
            channel_title = None
        group_key = (attribution, channel_id or tenant_ns or "UNATTRIBUTED")
        if group_key not in groups:
            groups[group_key] = {"attribution": attribution, "channel_id": channel_id,
                "channel_title": channel_title, "tenant_namespace": tenant_ns, "transactions": 0,
                "actual": Decimal(0), "estimated": Decimal(0), "reserved": Decimal(0), "production_ids": set(), "productions": {}, "titles": set(), "provenance": defaultdict(int)}
        group = groups[group_key]
        actual, estimated = _money(item.get("actualCost")), _money(item.get("estimatedCost"))
        reserved = estimated if str(item.get("status") or "").upper() in {"RESERVED", "CLAIMED"} else Decimal(0)
        group["transactions"] += 1
        group["actual"] += actual
        group["estimated"] += estimated
        group["reserved"] += reserved
        total_actual += actual
        total_estimated += estimated
        total_reserved += reserved
        title = str(item.get("productionTitle") or item.get("title") or "").strip()
        if title:
            group["titles"].add(title.casefold())
        source = str(item.get("source") or "UNKNOWN").strip().upper()
        status = str(item.get("status") or "UNKNOWN").strip().upper()
        group["provenance"][f"{source}:{status}"] += 1
        production_id = str(item.get("productionId") or "").strip()
        if production_id:
            group["production_ids"].add(production_id)
            prod = group["productions"].setdefault(production_id, {"production_id": production_id,
                "production_title": title or None, "provenance": defaultdict(int),
                "transaction_count": 0, "actual": Decimal(0), "estimated": Decimal(0), "reserved": Decimal(0)})
            prod["provenance"][f"{source}:{status}"] += 1
            prod["transaction_count"] += 1
            prod["actual"] += actual
            prod["estimated"] += estimated
            prod["reserved"] += reserved
    verified_namespaces = {g["tenant_namespace"] for g in groups.values() if g["attribution"] == "CHANNEL_CONNECTION_MATCH" and g["tenant_namespace"]}
    owner_error = False
    try:
        verified_owners, owner_scan_truncated = _verified_owners(verified_namespaces)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Admin cost owner directory lookup failed")
        verified_owners, owner_scan_truncated, owner_error = {}, True, True
    rows = []
    for group in groups.values():
        productions = [{"production_id": p["production_id"], "production_title": p["production_title"],
            "transaction_count": p["transaction_count"], "provenance": dict(sorted(p["provenance"].items())), "actual_cost_usd": _cost(p["actual"]),
            "estimated_cost_usd": _cost(p["estimated"]), "reserved_estimate_usd": _cost(p["reserved"])}
            for p in group["productions"].values()]
        productions.sort(key=lambda p: (-p["actual_cost_usd"], p["production_id"]))
        by_title: dict[str, dict[str, Any]] = {}
        for prod in productions:
            display = prod["production_title"] or "Untitled production"
            key = display.casefold()
            if key not in by_title:
                by_title[key] = {"title": display, "jobs": [], "actual_cost_usd": Decimal(0),
                    "estimated_cost_usd": Decimal(0), "reserved_estimate_usd": Decimal(0), "transaction_count": 0}
            bucket = by_title[key]
            bucket["jobs"].append(prod)
            bucket["transaction_count"] += prod["transaction_count"]
            for k in ("actual_cost_usd", "estimated_cost_usd", "reserved_estimate_usd"):
                bucket[k] += Decimal(str(prod[k]))
        titles = [{**{k: (_cost(v) if isinstance(v, Decimal) else v) for k, v in bucket.items()},
            "production_job_count": len(bucket["jobs"])} for bucket in by_title.values()]
        titles.sort(key=lambda x: (-x["actual_cost_usd"], x["title"].casefold()))
        rows.append({"owner": verified_owners.get(group["tenant_namespace"]) if group["attribution"] == "CHANNEL_CONNECTION_MATCH" and not owner_scan_truncated else None, "tenant_namespace": group["tenant_namespace"], "attribution": group["attribution"],
            "channel_id": group["channel_id"], "channel_title": group["channel_title"],
            "transaction_count": group["transactions"], "production_count": len(group["production_ids"]),
            "unique_title_count": len(group["titles"]), "title_groups": titles,
            "provenance": dict(sorted(group["provenance"].items())),
            "actual_cost_usd": _cost(group["actual"]), "estimated_cost_usd": _cost(group["estimated"]),
            "reserved_estimate_usd": _cost(group["reserved"]), "productions": productions})
    rows.sort(key=lambda r: (-r["actual_cost_usd"], r["channel_id"] or r["tenant_namespace"] or ""))
    trends = [{"date": d["date"], "actual_cost_usd": _cost(d["actual"]), "estimated_cost_usd": _cost(d["estimated"]),
        "reserved_estimate_usd": _cost(d["reserved"]), "transaction_count": d["transactions"]} for d in sorted(daily.values(), key=lambda x: x["date"])]
    return {"owner_directory_incomplete": owner_scan_truncated, "owner_directory_error": owner_error,
        "undated_transaction_count_in_scan": undated, "date_from": from_date.isoformat() if from_date else None,
        "date_to": to_date.isoformat() if to_date else None, "daily_trend": trends,
        "scope": "LEDGER_SNAPSHOT", "currency": "USD", "scanned_transactions": len(entries),
        "has_more": has_more, "max_scan": limit, "channel_attribution_available": any(r["channel_id"] for r in rows),
        "connection_registry_scan_incomplete": connections_truncated,
        "total_actual_cost_usd": _cost(total_actual), "total_estimated_cost_usd": _cost(total_estimated),
        "total_reserved_estimate_usd": _cost(total_reserved), "groups": rows,
        "generated_at": datetime.now(timezone.utc).isoformat()}
