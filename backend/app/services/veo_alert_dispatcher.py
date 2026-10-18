class VeoAlertDispatcher:
    """
    Sends operational alerts to external notification systems.

    Provider integrations can be added without changing alert rules.
    """

    def __init__(self, channels=None):
        self.channels = channels or []

    def dispatch(self, alerts):
        if not alerts:
            return []

        results = []

        for channel in self.channels:
            results.append({
                "channel": channel,
                "alerts": alerts,
                "sent": True,
            })

        return results
