from datetime import timedelta


class VeoRetryPolicyService:
    """
    Retry policy with persisted backoff schedule.
    """

    BACKOFF_SECONDS = [
        5,
        30,
        300,
    ]

    RETRYABLE_ERRORS = {
        "TIMEOUT",
        "TEMPORARY_UNAVAILABLE",
        "RATE_LIMIT",
        "INTERNAL",
    }

    def should_retry(self, error_code, attempt, max_attempts=3):
        return (
            attempt < max_attempts
            and error_code in self.RETRYABLE_ERRORS
        )

    def next_retry_delay(self, attempt):
        index = min(
            attempt,
            len(self.BACKOFF_SECONDS) - 1,
        )
        return self.BACKOFF_SECONDS[index]

    def build_retry_metadata(self, attempt):
        return {
            "retryAttempt": attempt + 1,
            "backoffSeconds": self.next_retry_delay(attempt),
        }
