"""
Configuration for soundtrack recovery scheduler.
"""


class SoundtrackRecoverySettings:

    def __init__(
        self,
        enabled=True,
        interval_seconds=300,
    ):
        self.enabled = enabled
        self.interval_seconds = interval_seconds
