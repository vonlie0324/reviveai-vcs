"""
Defines startup ordering for soundtrack recovery.
"""


class SoundtrackRecoveryStartupSequence:

    def __init__(
        self,
        dependency_factory,
    ):
        self.dependency_factory = dependency_factory

    async def initialize(self):
        return self.dependency_factory.create()
