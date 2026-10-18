"""Tenant-scoped, durable channel-intelligence budget. No production ID is invented.

The cap is a monthly allocation per channel and is immutable for the month.
Uncertain provider calls retain reservations until explicitly reconciled.
"""
from __future__ import annotations
import math
import os
import uuid
from datetime import datetime, timezone

from app.core.firebase_clients import get_runtime_firestore_client
from app.core.tenant import tenant_namespace
try:
    from google.cloud import firestore
except ImportError:
    firestore = None


def configured_cost() -> float:
    value = float(os.getenv('REVIVEAI_CHANNEL_INTELLIGENCE_RESERVATION_USD', '0'))
    if not math.isfinite(value) or value <= 0:
        raise RuntimeError('Configure REVIVEAI_CHANNEL_INTELLIGENCE_RESERVATION_USD > 0')
    return value


def configured_monthly_cap() -> float:
    value = float(os.getenv('REVIVEAI_CHANNEL_INTELLIGENCE_MONTHLY_BUDGET_USD', '0'))
    if not math.isfinite(value) or value <= 0:
        raise RuntimeError('Configure REVIVEAI_CHANNEL_INTELLIGENCE_MONTHLY_BUDGET_USD > 0')
    return value


class IntelligenceProviderOutcomeUncertain(RuntimeError):
    """Provider charge or reconciliation outcome cannot safely be retried."""


class ChannelIntelligenceBudget:
    def __init__(self, db=None):
        self.db = db if db is not None else (get_runtime_firestore_client() if firestore else None)

    def reserve(self, channel_id: str, *, category: str, estimate: float | None = None):
        if self.db is None or firestore is None:
            raise RuntimeError('Channel intelligence ledger unavailable; provider call blocked')
        if not channel_id or not str(channel_id).strip():
            raise ValueError('channel_id required')
        amount = configured_cost() if estimate is None else float(estimate)
        cap = configured_monthly_cap()
        if not math.isfinite(amount) or amount <= 0 or amount > cap:
            raise RuntimeError('Invalid channel-intelligence reservation or exceeds monthly cap')
        now = datetime.now(timezone.utc)
        namespace = tenant_namespace()
        month = now.strftime('%Y-%m')
        # Stable prefix includes tenant namespace and channel; never share a pool across tenants.
        import hashlib
        channel_key = hashlib.sha256(f'{namespace}:{channel_id}:{month}'.encode()).hexdigest()
        budget_ref = self.db.collection('channel_intelligence_budgets').document(channel_key)
        operation_id = 'ci_' + uuid.uuid4().hex
        tx_ref = self.db.collection('channel_intelligence_cost_transactions').document(operation_id)
        transaction = self.db.transaction()

        @firestore.transactional
        def reserve_tx(tx):
            snap = budget_ref.get(transaction=tx)
            state = snap.to_dict() if snap.exists else {}
            if state and (state.get('tenantNamespace') != namespace or state.get('channelId') != channel_id):
                raise RuntimeError('Channel budget scope mismatch')
            allocated = float(state.get('allocated', cap))
            reserved = float(state.get('reserved', 0))
            spent = float(state.get('spent', 0))
            if allocated - reserved - spent + 1e-9 < amount:
                raise RuntimeError('Channel intelligence monthly budget exhausted')
            tx.set(budget_ref, {'tenantNamespace': namespace, 'channelId': channel_id,
                'month': month, 'allocated': allocated, 'reserved': reserved + amount,
                'spent': spent, 'updatedAt': now}, merge=True)
            tx.create(tx_ref, {'tenantNamespace': namespace, 'channelId': channel_id,
                'budgetId': channel_key, 'operationId': operation_id, 'category': category,
                'estimatedCost': amount, 'status': 'RESERVED', 'createdAt': now})
        reserve_tx(transaction)
        return operation_id

    def reconcile(self, operation_id: str, *, actual: float | None = None):
        if self.db is None or firestore is None:
            raise RuntimeError('Channel intelligence ledger unavailable')
        tx_ref = self.db.collection('channel_intelligence_cost_transactions').document(operation_id)
        namespace = tenant_namespace()
        transaction = self.db.transaction()
        @firestore.transactional
        def reconcile_tx(tx):
            snap = tx_ref.get(transaction=tx)
            if not snap.exists:
                raise ValueError('Unknown channel intelligence reservation')
            item = snap.to_dict() or {}
            if item.get('tenantNamespace') != namespace:
                raise ValueError('Reservation tenant mismatch')
            if item.get('status') == 'RECONCILED':
                return {'idempotent': True}
            if item.get('status') != 'RESERVED':
                raise ValueError('Reservation not reconcilable')
            estimated = float(item['estimatedCost'])
            charge = estimated if actual is None else float(actual)
            if not math.isfinite(charge) or charge < 0:
                raise ValueError('Invalid reconciled cost')
            budget_ref = self.db.collection('channel_intelligence_budgets').document(item['budgetId'])
            b_snap = budget_ref.get(transaction=tx)
            if not b_snap.exists:
                raise RuntimeError('Missing intelligence budget')
            budget = b_snap.to_dict() or {}
            if budget.get('tenantNamespace') != namespace or budget.get('channelId') != item.get('channelId'):
                raise ValueError('Intelligence budget scope mismatch')
            held = float(budget.get('reserved', 0))
            if held + 1e-8 < estimated:
                raise RuntimeError('Intelligence reserve balance inconsistent')
            new_reserved = max(0, held - estimated)
            new_spent = float(budget.get('spent', 0)) + charge
            tx.set(budget_ref, {'reserved': new_reserved, 'spent': new_spent,
                'overBudget': new_spent + new_reserved > float(budget['allocated']) + 1e-8,
                'updatedAt': datetime.now(timezone.utc)}, merge=True)
            tx.set(tx_ref, {'status': 'RECONCILED', 'actualCost': charge,
                'reconciledAt': datetime.now(timezone.utc)}, merge=True)
            return {'reserved': new_reserved, 'spent': new_spent}
        return reconcile_tx(transaction)

    async def generate(self, *, channel_id, category, client, **kwargs):
        operation_id = self.reserve(channel_id, category=category)
        # Do not release a reservation after ambiguous provider failures: a timeout can be charged.
        try:
            response = await client.aio.models.generate_content(**kwargs)
        except Exception as exc:
            raise IntelligenceProviderOutcomeUncertain(
                f"Provider outcome uncertain; reservation {operation_id} remains held for reconciliation"
            ) from exc
        # The provider request completed even if subsequent validation/parsing fails.
        try:
            self.reconcile(operation_id)
        except Exception as exc:
            raise IntelligenceProviderOutcomeUncertain(
                f"Provider succeeded but reconciliation failed for reservation {operation_id}; do not retry"
            ) from exc
        return response
