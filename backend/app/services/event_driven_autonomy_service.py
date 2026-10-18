from __future__ import annotations

import logging

from app.core.config import get_settings
from app.core.task_execution import internal_task_context
from app.services.autopilot_supervisor_queue import autopilot_supervisor_queue
from app.services.youtube_autonomy_queue import youtube_autonomy_queue

logger = logging.getLogger(__name__)


class EventDrivenAutonomyService:
    """Bootstrap/recovery helper for Cloud Tasks mode.

    This performs finite work only. It never creates an in-process loop, so Cloud Run can
    safely use request-based CPU allocation and scale to zero between wake-up requests.
    """

    def __init__(self):
        self.settings = get_settings()

    def bootstrap(self) -> dict[str, int]:
        if not self.settings.autopilot_event_driven_enabled:
            return {"autopilot_restored": 0, "autopilot_scheduled": 0, "youtube_restored": 0, "youtube_scheduled": 0}
        # Bootstrap only reconstructs durable queue docs. Task creation happens once
        # below via schedule_pending(), avoiding duplicate startup tasks.
        with internal_task_context():
            autopilot_restored = autopilot_supervisor_queue.bootstrap_from_persisted_states()
        youtube_restored = youtube_autonomy_queue.bootstrap()
        autopilot_scheduled = autopilot_supervisor_queue.schedule_pending()
        youtube_scheduled = youtube_autonomy_queue.schedule_pending()
        result = {
            "autopilot_restored": autopilot_restored,
            "autopilot_scheduled": autopilot_scheduled,
            "youtube_restored": youtube_restored,
            "youtube_scheduled": youtube_scheduled,
        }
        logger.info("Event-driven autonomy bootstrap: %s", result)
        return result

    def recovery_sweep(self) -> dict[str, int]:
        return self.bootstrap()


event_driven_autonomy_service = EventDrivenAutonomyService()
