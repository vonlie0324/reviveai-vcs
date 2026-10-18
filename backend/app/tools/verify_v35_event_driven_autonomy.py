from __future__ import annotations

from app.core.config import get_settings
from app.services.cloud_task_dispatcher import cloud_task_dispatcher
from app.services.autopilot_supervisor_queue import autopilot_supervisor_queue
from app.services.youtube_autonomy_queue import youtube_autonomy_queue


def main() -> None:
    s = get_settings()
    print("ReviveAI v3.5 event-driven autonomy verification")
    print("-------------------------------------------------")
    print(f"event driven enabled       : {'YES' if s.autopilot_event_driven_enabled else 'NO'}")
    print(f"Cloud Tasks configured     : {'YES' if cloud_task_dispatcher.configured else 'NO'}")
    print(f"tasks project              : {s.effective_autopilot_tasks_project_id or '(missing)'}")
    print(f"tasks location             : {s.autopilot_tasks_location or '(missing)'}")
    print(f"tasks queue                : {s.autopilot_tasks_queue or '(missing)'}")
    print(f"target base URL configured : {'YES' if bool(s.autopilot_tasks_target_base_url) else 'NO'}")
    print(f"OIDC service account set   : {'YES' if bool(s.autopilot_tasks_service_account_email) else 'NO'}")
    print(f"active Autopilot queue docs: {len(autopilot_supervisor_queue.list_running(limit=100, include_waiting_final_approval=True, include_waiting_learning=True, include_completed=True))}")
    print(f"due YouTube queue docs     : {len(youtube_autonomy_queue.list_due(limit=100))}")
    ok = (not s.autopilot_event_driven_enabled) or cloud_task_dispatcher.configured
    print("\nOK: v3.5 task dispatch configuration is complete." if ok else "\nERROR: event-driven mode is enabled but Cloud Tasks configuration is incomplete.")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
