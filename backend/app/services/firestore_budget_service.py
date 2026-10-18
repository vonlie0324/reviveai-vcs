from __future__ import annotations

from datetime import datetime, timezone

from app.core.firebase_clients import get_runtime_firestore_client
from app.core.tenant import tenant_namespace

try:
    from google.cloud import firestore
except Exception:
    firestore = None


class FirestoreBudgetService:
    """Firestore-backed, tenant-attributed and idempotent cost reservation ledger."""

    def __init__(self):
        self.db = get_runtime_firestore_client() if firestore else None

    def ensure_production_budget(self, production_id, channel_id, allocated_usd):
        """Initialize a tenant-scoped immutable budget snapshot before any reservation.

        Existing allocations are not silently increased by channel policy edits.
        """
        import math
        if self.db is None:
            raise RuntimeError("budget_ledger_unavailable")
        amount = float(allocated_usd)
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError("Invalid production budget")
        namespace = tenant_namespace()
        ref = self.db.collection("productions").document(production_id).collection("system").document("budget")
        transaction = self.db.transaction()

        @firestore.transactional
        def initialize(tx):
            snap = ref.get(transaction=tx)
            if snap.exists:
                current = snap.to_dict() or {}
                if current.get("tenantNamespace") != namespace or current.get("channelId") != channel_id:
                    raise ValueError("Production budget scope mismatch")
                return current
            data = {
                "allocated": amount, "reserved": 0.0, "spent": 0.0,
                "channelId": channel_id, "tenantNamespace": namespace,
                "createdAt": datetime.now(timezone.utc),
                "updatedAt": datetime.now(timezone.utc),
            }
            tx.set(ref, data)
            return data
        return initialize(transaction)

    def reserve(self, production_id, estimated_cost, operation_id):
        # Never authorize a billable provider call when the durable budget ledger
        # is unavailable. A previous fail-open fallback silently bypassed caps.
        if self.db is None:
            return {
                "allowed": False,
                "transaction_id": operation_id,
                "remaining": 0,
                "reason": "budget_ledger_unavailable",
            }

        estimated_cost = float(estimated_cost or 0)
        if not (estimated_cost > 0 and estimated_cost < float("inf")):
            return {
                "allowed": False,
                "transaction_id": operation_id,
                "remaining": 0,
                "reason": "invalid_estimated_cost",
            }
        namespace = tenant_namespace()
        budget_ref = (
            self.db.collection("productions")
            .document(production_id)
            .collection("system")
            .document("budget")
        )
        tx_ref = self.db.collection("production_cost_transactions").document(operation_id)
        transaction = self.db.transaction()

        @firestore.transactional
        def reserve_tx(tx):
            existing = tx_ref.get(transaction=tx)
            if existing.exists:
                current = existing.to_dict() or {}
                if (str(current.get("productionId") or "") != str(production_id)
                    or current.get("tenantNamespace") != namespace):
                    return {"allowed": False, "remaining": 0, "reason": "operation_id_conflict"}
                return {
                    # An existing claim is NOT permission to call the provider again.
                    # Reconnect using its durable provider operation instead.
                    "allowed": False,
                    "reason": "existing_operation_requires_recovery",
                    "transaction_id": operation_id,
                    "idempotent": True,
                }

            snap = budget_ref.get(transaction=tx)
            budget = snap.to_dict() if snap.exists else {"allocated": 0, "reserved": 0, "spent": 0}
            if snap.exists and budget.get("tenantNamespace") != namespace:
                return {"allowed": False, "remaining": 0, "reason": "budget_tenant_mismatch"}
            allocated = float(budget.get("allocated", 0) or 0)
            reserved = float(budget.get("reserved", 0) or 0)
            spent = float(budget.get("spent", 0) or 0)
            remaining = allocated - reserved - spent
            if estimated_cost > remaining:
                return {
                    "allowed": False, "remaining": remaining,
                    "reason": "insufficient_funds",
                    "allocated": allocated, "reserved": reserved, "spent": spent,
                    "requested": estimated_cost,
                }

            tx.set(
                budget_ref,
                {
                    "allocated": allocated,
                    "reserved": reserved + estimated_cost,
                    "spent": spent,
                    "tenantNamespace": namespace,
                    "updatedAt": datetime.now(timezone.utc),
                },
                merge=True,
            )
            tx.set(
                tx_ref,
                {
                    "tenantNamespace": namespace,
                    "productionId": production_id,
                    "operationId": operation_id,
                    "estimatedCost": estimated_cost,
                    "status": "RESERVED",
                    "createdAt": datetime.now(timezone.utc),
                },
            )
            return {"allowed": True, "transaction_id": operation_id}

        return reserve_tx(transaction)

    def complete(self, operation_id, actual_cost):
        """Finish an existing reservation; never write an unaccounted cost transaction."""
        if self.db is None:
            raise RuntimeError("budget_ledger_unavailable")
        tx_ref = self.db.collection("production_cost_transactions").document(operation_id)
        snap = tx_ref.get()
        if not snap.exists:
            raise ValueError("Cannot complete an operation without a reservation")
        item = snap.to_dict() or {}
        if item.get("tenantNamespace") != tenant_namespace():
            raise ValueError("Budget transaction belongs to another tenant")
        return self.reconcile(item.get("productionId"), operation_id, item.get("estimatedCost"), actual_cost)

    def release(self, operation_id):
        if not self.db:
            return

        tx_ref = self.db.collection("production_cost_transactions").document(operation_id)
        transaction = self.db.transaction()

        @firestore.transactional
        def release_tx(tx):
            snap = tx_ref.get(transaction=tx)
            if not snap.exists:
                return
            item = snap.to_dict() or {}
            status = str(item.get("status") or "").upper()
            if item.get("tenantNamespace") != tenant_namespace():
                raise ValueError("Budget reservation tenant mismatch")
            if status in {"RELEASED", "RECONCILED"}:
                return
            if status != "RESERVED":
                raise ValueError(f"Cannot release operation in {status} state")

            production_id = str(item.get("productionId") or "").strip()
            estimated = float(item.get("estimatedCost", 0) or 0)
            if production_id:
                budget_ref = (
                    self.db.collection("productions")
                    .document(production_id)
                    .collection("system")
                    .document("budget")
                )
                budget_snap = budget_ref.get(transaction=tx)
                budget = budget_snap.to_dict() if budget_snap.exists else {}
                reserved = float(budget.get("reserved", 0) or 0)
                tx.set(
                    budget_ref,
                    {
                        "reserved": max(0.0, reserved - estimated),
                        "tenantNamespace": tenant_namespace(),
                        "updatedAt": datetime.now(timezone.utc),
                    },
                    merge=True,
                )

            tx.set(
                tx_ref,
                {
                    "tenantNamespace": tenant_namespace(),
                    "status": "RELEASED",
                    "releasedAt": datetime.now(timezone.utc),
                },
                merge=True,
            )

        release_tx(transaction)

    def reconcile(self, production_id, operation_id, estimated_cost, actual_cost):
        """Atomically convert an existing reservation to actual spend exactly once.

        The reservation stored in Firestore is authoritative.  Caller estimates
        are retained only for compatibility; they never change ledger math.
        """
        import math

        if self.db is None:
            raise RuntimeError("budget_ledger_unavailable")
        actual_cost = float(actual_cost)
        if not math.isfinite(actual_cost) or actual_cost < 0:
            raise ValueError("Invalid actual cost")
        namespace = tenant_namespace()
        tx_ref = self.db.collection("production_cost_transactions").document(operation_id)
        budget_ref = (
            self.db.collection("productions").document(production_id)
            .collection("system").document("budget")
        )
        transaction = self.db.transaction()

        @firestore.transactional
        def reconcile_tx(tx):
            cost_snap = tx_ref.get(transaction=tx)
            if not cost_snap.exists:
                raise ValueError("Cannot reconcile an operation without a reservation")
            item = cost_snap.to_dict() or {}
            if item.get("tenantNamespace") != namespace or str(item.get("productionId")) != str(production_id):
                raise ValueError("Budget reservation scope mismatch")
            status = str(item.get("status") or "").upper()
            if status == "RECONCILED":
                return {"idempotent": True, "status": "RECONCILED"}
            if status != "RESERVED":
                raise ValueError(f"Cannot reconcile operation in {status} state")
            reserved_cost = float(item.get("estimatedCost") or 0)
            if not math.isfinite(reserved_cost) or reserved_cost <= 0:
                raise ValueError("Invalid reservation amount")
            budget_snap = budget_ref.get(transaction=tx)
            if not budget_snap.exists:
                raise ValueError("Production budget ledger missing")
            budget = budget_snap.to_dict() or {}
            if budget.get("tenantNamespace") != namespace:
                raise ValueError("Production budget tenant mismatch")
            reserved = float(budget.get("reserved") or 0)
            spent = float(budget.get("spent") or 0)
            allocated = float(budget.get("allocated") or 0)
            if reserved + 1e-8 < reserved_cost:
                raise ValueError("Budget reservation balance inconsistent")
            new_reserved = max(0.0, reserved - reserved_cost)
            new_spent = spent + actual_cost
            # An overage must be reflected rather than silently erased; alert
            # operators while continuing to account for the real provider charge.
            tx.set(budget_ref, {
                "allocated": allocated,
                "reserved": new_reserved,
                "spent": new_spent,
                "overBudget": (new_spent + new_reserved > allocated + 1e-8),
                "tenantNamespace": namespace,
                "updatedAt": datetime.now(timezone.utc),
            }, merge=True)
            tx.set(tx_ref, {
                "tenantNamespace": namespace,
                "productionId": production_id,
                "operationId": operation_id,
                "estimatedCost": reserved_cost,
                "actualCost": actual_cost,
                "variance": actual_cost - reserved_cost,
                "status": "RECONCILED",
                "reconciledAt": datetime.now(timezone.utc),
            }, merge=True)
            return {"reserved": new_reserved, "spent": new_spent, "overBudget": new_spent + new_reserved > allocated + 1e-8}

        return reconcile_tx(transaction)
