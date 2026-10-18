"""
Registry helper for recovery worker lifecycle.
"""


class SoundtrackRecoveryRegistry:

    def __init__(self):
        self.worker = None

    def register(self, worker):
        self.worker = worker

    def get_worker(self):
        return self.worker
