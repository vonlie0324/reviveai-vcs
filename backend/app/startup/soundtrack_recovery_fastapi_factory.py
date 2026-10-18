"""
Creates the soundtrack recovery runtime during application startup.
"""


class SoundtrackRecoveryFastAPIFactory:

    def __init__(
        self,
        dependency_builder,
    ):
        self.dependency_builder = dependency_builder

    def create(self):
        return self.dependency_builder.build()
