from datetime import datetime, timezone

try:
    from google.cloud import firestore
except Exception:
    firestore = None


class VeoResponseValidationError(Exception):
    pass


class VeoOperationCaptureService:
    """
    Captures Veo lifecycle, usage, and provider errors.

    Provider-specific mapping is isolated here so workflow code
    remains stable when SDK response fields evolve.
    """

    def __init__(self):
        from app.core.firebase_clients import get_runtime_firestore_client
        self.db = get_runtime_firestore_client() if firestore else None

    def _ref(self, operation_id):
        return self.db.collection("veo_operations").document(operation_id)

    def validate_response(self, response):
        if not response:
            raise VeoResponseValidationError("Empty Veo response")

        return True

    def persist_state(self, operation_id, production_id, state, metadata=None):
        record = {
            "operationId": operation_id,
            "productionId": production_id,
            "provider": "VEO",
            "state": state,
            "metadata": metadata or {},
            "updatedAt": datetime.now(timezone.utc),
        }

        if self.db:
            self._ref(operation_id).set(record, merge=True)

        return record

    def extract_usage(self, response):
        """
        Normalizes usage fields from the SDK/provider response.

        Keeps fallback handling because exact SDK fields may differ
        by provider SDK version.
        """
        if not response:
            return {}

        if isinstance(response, dict):
            usage = response.get("usageMetadata") or response.get("usage") or {}

            return {
                "cost": (
                    usage.get("cost")
                    or usage.get("totalCost")
                    or usage.get("total_cost")
                ),
                "inputTokens": (
                    usage.get("inputTokenCount")
                    or usage.get("inputTokens")
                ),
                "outputTokens": (
                    usage.get("outputTokenCount")
                    or usage.get("outputTokens")
                ),
                "durationSeconds": (
                    usage.get("durationSeconds")
                    or usage.get("duration_seconds")
                ),
                "model": response.get("model"),
            }

        return {}

    def extract_error(self, response):
        if not response:
            return {}

        if isinstance(response, dict):
            error = response.get("error") or {}

            return {
                "code": error.get("code"),
                "message": error.get("message"),
                "details": error.get("details"),
            }

        return {
            "message": str(response)
        }

    def capture_completed(self, production_id, operation_id, response):
        usage = self.extract_usage(response)

        record = {
            "productionId": production_id,
            "operationId": operation_id,
            "provider": "VEO",
            "state": "COMPLETED",
            "usage": usage,
            "providerResponse": response,
            "updatedAt": datetime.now(timezone.utc),
        }

        if self.db:
            self._ref(operation_id).set(record, merge=True)

        return usage

    def capture_failed(self, production_id, operation_id, response):
        error = self.extract_error(response)

        record = {
            "productionId": production_id,
            "operationId": operation_id,
            "provider": "VEO",
            "state": "FAILED",
            "error": error,
            "providerResponse": response,
            "updatedAt": datetime.now(timezone.utc),
        }

        if self.db:
            self._ref(operation_id).set(record, merge=True)

        return error
