from datetime import datetime, timezone, timedelta

from app.services.veo_retry_policy_service import VeoRetryPolicyService

try:
    from google.cloud import firestore
except Exception:
    firestore = None


class VeoOperationRecoveryService:
    """
    Detects stale Veo operations and manages recovery decisions.
    """

    def __init__(self):
        self.db = firestore.Client() if firestore else None
        self.retry_policy = VeoRetryPolicyService()

    def mark_stale_operations(
        self,
        timeout_minutes=30,
    ):
        """
        Finds RUNNING operations with no heartbeat update.
        """

        if not self.db:
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(
            minutes=timeout_minutes
        )

        docs = (
            self.db.collection("veo_operations")
            .where("state", "==", "RUNNING")
            .stream()
        )

        stale = []

        for doc in docs:
            data = doc.to_dict()

            updated = data.get("updatedAt")

            if updated and updated < cutoff:
                doc.reference.update({
                    "state": "STALE",
                    "updatedAt": datetime.now(timezone.utc),
                })

                stale.append(doc.id)

        return stale

    def recover(self, operation_id):
        """
        Moves stale operations back into recovery processing.
        """

        if not self.db:
            return

        self.db.collection(
            "veo_operations"
        ).document(operation_id).update({
            "state": "RECOVERING",
            "updatedAt": datetime.now(timezone.utc),
        })

    def fail(self, operation_id, reason):
        if not self.db:
            return

        self.db.collection(
            "veo_operations"
        ).document(operation_id).update({
            "state": "FAILED",
            "failureReason": reason,
            "updatedAt": datetime.now(timezone.utc),
        })


    def retry_if_allowed(self, operation_id, error_code, attempt):
        if not self.retry_policy.should_retry(
            error_code,
            attempt
        ):
            return False

        if self.db:
            self.db.collection(
                "veo_operations"
            ).document(operation_id).update({
                "state": "RETRYING",
                "retryAttempt": attempt + 1,
            })

        return True
