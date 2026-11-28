from __future__ import annotations

from http import HTTPStatus
from types import SimpleNamespace

import pytest

from application.chat.stop_chat import ChatSessionChanged

from frontend_bridge_core.routes.chat_routes import CHAT_ROUTES
from frontend_bridge_core.routes.router import ApiRequest, Router


def _contracts() -> set[tuple[str, str]]:
    return {
        (method, route.pattern) for route in CHAT_ROUTES for method in route.methods
    }


def _request(
    router: Router,
    method: str,
    path: str,
    *,
    body: dict | None = None,
    query: dict[str, list[str]] | None = None,
) -> tuple[ApiRequest, object]:
    matched = router.match(method, path)
    assert matched is not None
    return (
        ApiRequest(
            state=SimpleNamespace(),
            method=method,
            path=path,
            query=query or {},
            params=matched.params,
            body=body or {},
        ),
        matched.route,
    )


def test_chat_route_contracts_remain_stable() -> None:
    assert _contracts() == {
        ("POST", "/api/chat/replay"),
        ("POST", "/api/chat/replay/{replay_id}/start"),
        ("GET", "/api/chat/replay/{replay_id}"),
        ("POST", "/api/chat/replay/{replay_id}/control"),
        ("POST", "/api/chat/replay/{replay_id}/voice/{entry_id}"),
        ("DELETE", "/api/chat/replay/{replay_id}"),
        ("DELETE", "/api/chat/conversations/{conversation_id}"),
        ("GET", "/api/chat/conversations/current"),
        ("GET", "/api/chat/conversations"),
        ("GET", "/api/chat/conversations/{conversation_id}/launch-payload"),
        ("POST", "/api/chat/conversations/{conversation_id}/rename"),
        ("POST", "/api/chat/conversations/{conversation_id}/settings"),
        ("DELETE", "/api/chat/themes/{theme_id}"),
        ("GET", "/api/chat/history"),
        ("GET", "/api/chat/history-voice/{voice_id}"),
        ("GET", "/api/chat/runtime-status"),
        ("GET", "/api/chat/snapshot"),
        ("GET", "/api/chat/theme"),
        ("GET", "/api/chat/themes"),
        ("GET", "/api/chat/themes/active"),
        ("GET", "/api/chat/themes/{theme_id}"),
        ("POST", "/api/chat/close"),
        ("POST", "/api/chat/command"),
        ("POST", "/api/chat/behavior-command"),
        ("POST", "/api/chat/export-vn"),
        ("POST", "/api/chat/init"),
        ("POST", "/api/chat/launch"),
        ("POST", "/api/chat/resume-last"),
        ("POST", "/api/chat/themes/active"),
        ("POST", "/api/chat/themes/save"),
    }


def test_history_voice_file_path_is_not_captured_as_a_voice_id() -> None:
    assert Router(list(CHAT_ROUTES)).match("GET", "/api/chat/history-voice-file") is None


def test_chat_init_preserves_accepted_status(monkeypatch) -> None:
    task = {"id": "chat-init-1", "status": "queued"}
    monkeypatch.setattr(
        "frontend_bridge_core.routes.chat_routes.start_chat_initialization",
        lambda _state, _body: task,
    )
    router = Router(list(CHAT_ROUTES))
    request, route = _request(
        router,
        "POST",
        "/api/chat/init",
        body={"mode": "resume-last"},
    )

    response = route.handler(request)

    assert response.data == task
    assert response.status is HTTPStatus.ACCEPTED


def test_snapshot_preserves_renderer_query_parameter(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "frontend_bridge_core.routes.chat_routes._chat_snapshot",
        lambda _state, *, renderer_id: calls.append(renderer_id)
        or {"rendererId": renderer_id},
    )
    router = Router(list(CHAT_ROUTES))
    request, route = _request(
        router,
        "GET",
        "/api/chat/snapshot",
        query={"rendererId": ["renderer-1"]},
    )

    response = route.handler(request)

    assert response.data == {"rendererId": "renderer-1"}
    assert calls == ["renderer-1"]


def test_observer_snapshot_does_not_supply_a_renderer(monkeypatch) -> None:
    snapshot = {"sessionId": "session-A"}
    calls = []
    monkeypatch.setattr(
        "frontend_bridge_core.routes.chat_routes._chat_snapshot",
        lambda _state, *, renderer_id: calls.append(renderer_id) or snapshot,
    )
    request, route = _request(Router(list(CHAT_ROUTES)), "GET", "/api/chat/snapshot")
    assert route.handler(request).data == snapshot
    assert calls == [""]


@pytest.mark.parametrize("body, expected", [({}, None), ({"expectedSessionId": "A"}, "A"), ({"expectedSessionId": ""}, "")])
def test_close_forwards_expected_session_identity(monkeypatch, body, expected):
    calls = []
    monkeypatch.setattr(
        "frontend_bridge_core.routes.chat_routes.stop_chat",
        lambda _state, *, expected_session_id: calls.append(expected_session_id) or {"status": "idle"},
    )
    request, route = _request(Router(list(CHAT_ROUTES)), "POST", "/api/chat/close", body=body)
    assert route.handler(request).data == {"status": "idle"}
    assert calls == [expected]


@pytest.mark.parametrize("expected", [None, 7, False, {}])
def test_close_rejects_invalid_session_identity(expected):
    request, route = _request(Router(list(CHAT_ROUTES)), "POST", "/api/chat/close", body={"expectedSessionId": expected})
    with pytest.raises(ValueError, match="expectedSessionId must be a string"):
        route.handler(request)


def test_close_reports_session_conflict(monkeypatch):
    def changed(*_args, **_kwargs):
        raise ChatSessionChanged("chat changed")
    monkeypatch.setattr("frontend_bridge_core.routes.chat_routes.stop_chat", changed)
    request, route = _request(Router(list(CHAT_ROUTES)), "POST", "/api/chat/close", body={"expectedSessionId": "A"})
    response = route.handler(request)
    assert response.status is HTTPStatus.CONFLICT
    assert response.data == {"error": "chat changed", "errorCode": "chat_session_changed"}


def test_launch_chat_isolates_mismatched_behavior_histories(
    tmp_path, monkeypatch
) -> None:
    from application.chat.host.launch_history import resolve_chat_history_path
    from core.chat_history.behavior_state_store import (
        BehaviorStateStore,
        read_latest_behavior_id_readonly,
    )
    from core.chat_history.storage import (
        chat_history_session_dir,
        close_session_store,
        open_session_store,
    )
    from frontend_bridge_core.chat_session import _launch_chat_locked
    from sdk.exception.types import AppError

    history_dir = tmp_path / "history"
    template_dir = tmp_path / "templates"
    history_dir.mkdir()
    template_dir.mkdir()

    state = SimpleNamespace(
        project_root_dir=str(tmp_path),
        history_dir=str(history_dir),
        template_dir_path=str(template_dir),
        chat_session={},
        chat_stream=None,
        auth_token="",
        config_manager=SimpleNamespace(
            config=SimpleNamespace(
                system_config=SimpleNamespace(
                    live_room_id="",
                    voice_language="ja",
                    chat_ui_runtime_mode="react",
                    use_agent_chat_pipeline=False,
                ),
                characters=[],
                background_list=[],
            ),
            get_character_by_name=lambda _n: None,
            get_background_by_name=lambda _n: None,
            save_system_config=lambda: None,
        ),
    )

    body_base = {
        "templateId": "tpl.txt",
        "scenario": "Werewolf village",
        "system": "System rules",
        "characters": [],
        "behaviorId": "mafia",
    }
    default_history = resolve_chat_history_path(state, body_base, body_base)
    session_dir = chat_history_session_dir(default_history)
    session_dir.mkdir(parents=True, exist_ok=True)
    store = open_session_store(default_history)
    try:
        BehaviorStateStore(store, session_dir).initialize_state(  # type: ignore[arg-type]
            branch_id="main",
            behavior_id="werewolf",
            state={"phase": "day"},
        )
    finally:
        close_session_store(default_history)

    monkeypatch.setattr("frontend_bridge_core.chat_session._chat_runtime_closing", lambda _s: False)
    monkeypatch.setattr("frontend_bridge_core.chat_session._chat_process_running", lambda: False)
    monkeypatch.setattr("frontend_bridge_core.chat_session.configure_mobile_access", lambda *_a, **_kw: None)
    monkeypatch.setattr("frontend_bridge_core.chat_session.build_effect_context", lambda *_a, **_kw: SimpleNamespace(selected_names=[]))
    monkeypatch.setattr("frontend_bridge_core.chat_session.find_session_behavior_plugin_id", lambda bid: "com.demo." + bid)
    monkeypatch.setattr(
        "frontend_bridge_core.chat_session._session_lifecycle",
        lambda *_a, **_kw: SimpleNamespace(
            begin=lambda *_a2, **_kw2: "launch-1",
            launch=lambda fn: fn() or "ok",
        ),
    )
    monkeypatch.setattr("frontend_bridge_core.chat_session._complete_chat_launch", lambda *_a, **_kw: None)
    monkeypatch.setattr("frontend_bridge_core.chat_session.remember_conversation", lambda *_a, **_kw: None)
    monkeypatch.setattr("frontend_bridge_core.chat_session._chat_snapshot", lambda _s, status, err, extra=None: {"status": status, **(extra or {})})

    launched_paths: list[str] = []
    monkeypatch.setattr(
        "frontend_bridge_core.chat_session._launch_runtime_chat",
        lambda _s, **kw: launched_paths.append(kw["history_file"]) or "ok",
    )

    # 1. Implicit default path owned by another behavior opens a fresh sibling history.
    _launch_chat_locked(state, dict(body_base))
    assert len(launched_paths) == 1
    assert launched_paths[0] != default_history.as_posix()
    assert read_latest_behavior_id_readonly(session_dir) == "werewolf"

    # 2. Explicit historyPath owned by another behavior raises HTTP 409 mismatch.
    with pytest.raises(AppError) as mismatch:
        _launch_chat_locked(
            state,
            {**body_base, "historyPath": default_history.as_posix()},
        )
    assert mismatch.value.error_code == "behavior.identity_mismatch"
    assert mismatch.value.http_status == 409
