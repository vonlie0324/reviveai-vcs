from datetime import datetime, timezone, timedelta

try:
    from google.cloud import firestore
except Exception:
    firestore = None


class VeoRecoveryLockService:
    """
    Firestore distributed lock to prevent duplicate recovery workers.
    """

    def __init__(self):
        self.db = firestore.Client() if firestore else None

    def acquire(self, lock_id="veo_recovery_worker", ttl_minutes=10):
        if not self.db:
            return True

        ref = self.db.collection(
            "system_locks"
        ).document(lock_id)

        transaction = self.db.transaction()

        @firestore.transactional
        def lock_transaction(tx):
            snapshot = ref.get(transaction=tx)

            now = datetime.now(timezone.utc)

            if snapshot.exists:
                data = snapshot.to_dict()
                expires = data.get("expiresAt")

                if expires and expires > now:
                    return False

            tx.set(
                ref,
                {
                    "owner": lock_id,
                    "expiresAt": now + timedelta(
                        minutes=ttl_minutes
                    ),
                    "updatedAt": now,
                },
            )

            return True

        return lock_transaction(transaction)

    def release(self, lock_id="veo_recovery_worker"):
        if not self.db:
            return

        self.db.collection(
            "system_locks"
        ).document(lock_id).delete()
