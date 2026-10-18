"""
Background execution starter abstraction.
"""


class SoundtrackBackgroundExecution:

    def __init__(self, runner):
        self.runner = runner
        self.running = False

    async def start(self):
        self.running = True

    async def stop(self):
        self.running = False
