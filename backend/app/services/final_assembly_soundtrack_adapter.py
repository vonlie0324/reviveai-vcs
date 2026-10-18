"""
Final assembly soundtrack adapter.

Resolves soundtrack assets before FFmpeg assembly.
"""


class FinalAssemblySoundtrackAdapter:

    def __init__(
        self,
        finishing_adapter,
    ):
        self.finishing_adapter = finishing_adapter

    def prepare_audio_asset(self, soundtrack_id):
        return self.finishing_adapter.get_local_processing_file(
            soundtrack_id
        )
