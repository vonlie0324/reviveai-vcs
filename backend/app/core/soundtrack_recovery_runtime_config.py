"""
Runtime configuration helper.
"""


class SoundtrackRecoveryRuntimeConfig:

    def __init__(
        self,
        enabled=True,
        interval_seconds=300,
    ):
        self.enabled = enabled
        self.interval_seconds = interval_seconds
