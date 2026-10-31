from frontend_bridge_core.chat_session import launch_chat
from application.chat.doki_handoff import prepare, launch, status, acknowledge, change_presence, preview_records
from frontend_bridge_core.routes.router import JsonResponse, Route


def _prepare(request):
    return JsonResponse(prepare(request.state, request.body))


def _launch(request):
    return JsonResponse(launch(request.state, request.body['handoff_id'], launcher=launch_chat))


def _status(request):
    return JsonResponse(status(request.state, request.body['handoff_id']))


def _presence(request):
    from application.chat.stop_chat import stop_chat
    return JsonResponse(change_presence(request.state, request.body, stopper=stop_chat))


def _records(request):
    return JsonResponse(preview_records(request.state, request.body))


def _entered(request):
    return JsonResponse(acknowledge(request.state, request.body))


DOKI_ROUTES = tuple(Route(methods=frozenset({'POST'}), pattern='/api/integrations/doki/' + name, handler=handler, name='doki.' + name) for name, handler in [('prepare', _prepare), ('launch', _launch), ('status', _status), ('entered', _entered), ('presence', _presence), ('records', _records)])
