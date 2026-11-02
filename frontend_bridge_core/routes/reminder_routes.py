from application.reminders import ReminderStore
from application.reminders.presentation import ReminderPresenter
from application.reminders.migration import migrate_bedtime
from frontend_bridge_core.routes.router import ApiRequest, BodyKind, JsonResponse, Route


def _store(request):
    return ReminderStore(request.state.project_root_dir)


def _list(request: ApiRequest):
    return JsonResponse(_store(request).manage("list"))


def _manage(request: ApiRequest):
    allowed = {
        "action",
        "reminder_id",
        "character_name",
        "title",
        "message",
        "remind_at",
        "delay_minutes",
        "recurrence",
    }
    if set(request.body) - allowed or "action" not in request.body:
        raise ValueError("Invalid reminder fields")
    return JsonResponse(
        _store(request).manage(
            character_names=[
                character.name
                for character in request.state.config_manager.config.characters
            ],
            **request.body,
        )
    )


def _claim(request: ApiRequest):
    return JsonResponse(_store(request).claim(
        character_names=[character.name for character in request.state.config_manager.config.characters]
    ))


def _ack(request: ApiRequest):
    return JsonResponse(
        _store(request).acknowledge(
            request.body.get("reminder_id", ""), request.body.get("claim_token", "")
        )
    )


def _migrate_bedtime(request: ApiRequest):
    required = {"bedtime_time", "title", "message"}
    if not required <= request.body.keys() or request.body.keys() - required - {"last_delivered_date"}:
        raise ValueError("Invalid bedtime migration fields")
    return JsonResponse(migrate_bedtime(_store(request), **request.body))


def _presenter(request):
    with request.state.task_lock:
        if request.state.reminder_presenter is None:
            request.state.reminder_presenter = ReminderPresenter(
                request.state.config_manager, request.state.project_root_dir
            )
        return request.state.reminder_presenter


def _presentation(request: ApiRequest):
    return JsonResponse(_presenter(request).render(request.body))


def _speech(request: ApiRequest):
    return JsonResponse(_presenter(request).speech(request.body))


REMINDER_ROUTES = (
    Route(frozenset({"GET"}), "/api/reminders", _list, BodyKind.NONE, "reminders.list"),
    Route(frozenset({"POST"}), "/api/reminders", _manage, name="reminders.manage"),
    Route(frozenset({"POST"}), "/api/reminders/claim", _claim, name="reminders.claim"),
    Route(frozenset({"POST"}), "/api/reminders/ack", _ack, name="reminders.ack"),
    Route(frozenset({"POST"}), "/api/reminders/migrate-bedtime", _migrate_bedtime, name="reminders.migrate"),
    Route(
        frozenset({"POST"}),
        "/api/reminders/presentation",
        _presentation,
        name="reminders.presentation",
    ),
    Route(
        frozenset({"POST"}), "/api/reminders/speech", _speech, name="reminders.speech"
    ),
)
