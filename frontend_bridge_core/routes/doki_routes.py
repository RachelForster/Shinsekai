from application.chat.doki_handoff import prepare, launch, status, acknowledge
from frontend_bridge_core.routes.router import JsonResponse, Route


def _prepare(request):
    return JsonResponse(prepare(request.state, request.body))


def _launch(request):
    return JsonResponse(launch(request.state, request.body['handoff_id']))


def _status(request):
    return JsonResponse(status(request.state, request.body['handoff_id']))


def _entered(request):
    return JsonResponse(acknowledge(request.state, request.body))


DOKI_ROUTES = tuple(Route(methods=frozenset({'POST'}), pattern='/api/integrations/doki/' + name, handler=handler, name='doki.' + name) for name, handler in [('prepare', _prepare), ('launch', _launch), ('status', _status), ('entered', _entered)])
