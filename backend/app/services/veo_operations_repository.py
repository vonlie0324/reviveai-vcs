class VeoOperationsRepository:
    """
    Query abstraction for Veo operational dashboards.
    """

    def __init__(self, db=None):
        self.db = db

    def summary(self):
        return {
            "activeJobs": 0,
            "staleJobs": 0,
            "retryingJobs": 0,
            "failedJobs": 0,
            "budgetBlockedJobs": 0,
        }
