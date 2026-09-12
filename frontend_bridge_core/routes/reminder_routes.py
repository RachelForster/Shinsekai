from application.reminders import ReminderStore
from frontend_bridge_core.routes.router import ApiRequest, BodyKind, JsonResponse, Route


def _store(request):
    return ReminderStore(request.state.project_root_dir)


def _list(request: ApiRequest):
    return JsonResponse(_store(request).manage("list"))


def _manage(request: ApiRequest):
    allowed = {"action", "reminder_id", "character_name", "title", "message", "remind_at", "delay_minutes", "recurrence"}
    if set(request.body) - allowed or "action" not in request.body:
        raise ValueError("Invalid reminder fields")
    return JsonResponse(_store(request).manage(
        character_names=[character.name for character in request.state.config_manager.config.characters],
        **request.body,
    ))


def _claim(request: ApiRequest):
    return JsonResponse(_store(request).claim())


def _ack(request: ApiRequest):
    return JsonResponse(_store(request).acknowledge(request.body.get("reminder_id", ""), request.body.get("claim_token", "")))


REMINDER_ROUTES = (
    Route(frozenset({"GET"}), "/api/reminders", _list, BodyKind.NONE, "reminders.list"),
    Route(frozenset({"POST"}), "/api/reminders", _manage, name="reminders.manage"),
    Route(frozenset({"POST"}), "/api/reminders/claim", _claim, name="reminders.claim"),
    Route(frozenset({"POST"}), "/api/reminders/ack", _ack, name="reminders.ack"),
)
