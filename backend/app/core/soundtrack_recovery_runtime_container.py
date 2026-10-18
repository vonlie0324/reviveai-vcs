"""
Runtime container for soundtrack recovery dependencies.
"""


class SoundtrackRecoveryRuntimeContainer:

    def __init__(
        self,
        dependencies,
    ):
        self.dependencies = dependencies

    def get(
        self,
        key,
    ):
        return self.dependencies.get(key)
