"""Security tests for scoped plugin tokens, cookie path isolation, and route guards."""

from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from application.runtime.state import BridgeState
from frontend_bridge_core.plugin_auth import (
    PLUGIN_AUTH_COOKIE,
    build_plugin_cookie_header,
    is_plugin_route_allowed,
    issue_plugin_token,
    resolve_issued_plugin_cookie_header,
    verify_plugin_token,
)
from frontend_bridge_core.routes.api import FrontendBridgeHandler


def _state(*, auth_token: str = "master-secret", chat_session: dict | None = None) -> BridgeState:
    return BridgeState(
        background_manager=None,
        character_manager=None,
        config_manager=None,
        template_generator=None,
        auth_token=auth_token,
        chat_session=chat_session if chat_session is not None else {},
    )


def _http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict | None = None,
):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req_headers = dict(headers or {})
    if data is not None:
        req_headers.setdefault("Content-Type", "application/json")
    return urlopen(Request(url, data=data, headers=req_headers, method=method), timeout=5)


def test_scoped_plugin_token_roundtrip_and_tamper_rejection() -> None:
    master = "top-secret-master-token"
    token = issue_plugin_token(master, "com.example/werewolf")

    assert token.startswith("shp1.")
    assert token != master
    assert verify_plugin_token(master, token) == "com.example/werewolf"
    assert verify_plugin_token("wrong-master", token) is None
    assert verify_plugin_token(master, f"{token[:-1]}A") is None
    assert verify_plugin_token(master, master) is None
    assert verify_plugin_token(master, "shp1.bad\n.sig") is None
    assert issue_plugin_token("", "com.example/werewolf") == ""
    assert issue_plugin_token(master, "") == ""


def test_plugin_route_allowlist_blocks_sensitive_and_cross_plugin_paths() -> None:
    plugin_id = "com.example.game"

    assert is_plugin_route_allowed("GET", "/api/plugins/com.example.game/ui", plugin_id)
    assert is_plugin_route_allowed("GET", "/api/plugins/com.example.game/tools", plugin_id)
    assert is_plugin_route_allowed(
        "GET", "/api/plugins/com.example.game/frontend/board/index.html", plugin_id
    )
    assert is_plugin_route_allowed("GET", "/api/chat/snapshot", plugin_id)
    assert is_plugin_route_allowed("GET", "/api/plugins/session-behaviors", plugin_id)
    assert is_plugin_route_allowed("GET", "/assets/sprites/alice/0.png", plugin_id)
    assert is_plugin_route_allowed(
        "POST", "/api/plugins/com.example.game/tools/roll/invoke", plugin_id
    )
    assert is_plugin_route_allowed("POST", "/api/chat/behavior-command", plugin_id)

    for method, path in (
        ("GET", "/api/config"),
        ("GET", "/api/config/api"),
        ("GET", "/api/download"),
        ("GET", "/data/config/api.yaml"),
        ("GET", "/assets/../data/config/api.yaml"),
        ("GET", "/assets/%2e%2e/data/config/api.yaml"),
        ("GET", "/api/agent/status"),
        ("GET", "/api/plugins/other.plugin/tools"),
        ("GET", "/api/plugins/other.plugin/frontend/index.html"),
        ("POST", "/api/config/api"),
        ("POST", "/api/plugins/other.plugin/tools/steal/invoke"),
        ("POST", "/api/plugins/install"),
        ("POST", "/api/chat/command"),
        ("DELETE", "/api/plugins/com.example.game"),
        ("PUT", "/api/config/system"),
    ):
        assert not is_plugin_route_allowed(method, path, plugin_id), (method, path)


def test_build_plugin_cookie_header_scopes_path_and_rejects_mismatch() -> None:
    token = issue_plugin_token("secret", "demo/plugin")
    header = build_plugin_cookie_header(
        "/api/plugins/demo%2Fplugin/frontend/board/index.html",
        token,
        "demo/plugin",
    )
    assert header is not None
    assert header.startswith(f"{PLUGIN_AUTH_COOKIE}={token};")
    assert "Path=/api/plugins/demo%2Fplugin/;" in header
    assert "HttpOnly" in header
    assert "SameSite=Strict" in header
    assert build_plugin_cookie_header("/api/config", token, "demo/plugin") is None
    assert (
        build_plugin_cookie_header("/api/plugins/other/frontend/", token, "demo/plugin")
        is None
    )
    assert (
        build_plugin_cookie_header(
            "/api/plugins/demo%2Fplugin/../other/frontend/",
            token,
            "demo/plugin",
        )
        is None
    )


def test_live_bridge_enforces_plugin_isolation_cookies_and_ownership(
    tmp_path, monkeypatch
) -> None:
    state = _state(
        auth_token="master-secret-key",
        chat_session={"behaviorId": "werewolf", "behaviorPluginId": "com.demo.game"},
    )
    page_file = tmp_path / "index.html"
    page_file.write_text("<html>plugin</html>", encoding="utf-8")

    monkeypatch.setattr(
        "frontend_bridge_core.routes.file_transport._resolve_plugin_frontend_file",
        lambda plugin_id, page_id, asset: (
            page_file if plugin_id == "com.demo.game" else tmp_path / "missing.html"
        ),
    )
    monkeypatch.setattr(
        "frontend_bridge_core.routes.plugin_routes.list_session_behavior_contributions",
        lambda: [{"behaviorId": "werewolf", "pluginId": "com.demo.game"}],
    )
    monkeypatch.setattr(
        "frontend_bridge_core.routes.chat_routes._chat_snapshot",
        lambda _s, *, renderer_id="": {"status": "running", "rendererId": renderer_id},
    )
    command_calls: list[dict] = []
    monkeypatch.setattr(
        "frontend_bridge_core.routes.chat_routes._handle_chat_command",
        lambda _s, body: command_calls.append(dict(body)) or {"status": "running"},
    )
    tool_calls: list[tuple[str, str, dict]] = []
    state.services = SimpleNamespace(
        get_plugin_tools=lambda: SimpleNamespace(
            list_tools=lambda pid: [{"name": "roll", "pluginId": pid}],
            invoke=lambda pid, tool, args: tool_calls.append((pid, tool, args)) or {"ok": True},
        )
    )
    monkeypatch.setattr(
        "frontend_bridge_core.routes.system_routes._app_config_response",
        lambda _s, **_kw: {"api_config": {"llm_api_key": "sk-top-secret"}},
    )

    plugin_token = issue_plugin_token(state.auth_token, "com.demo.game")
    other_token = issue_plugin_token(state.auth_token, "com.evil.other")

    server = ThreadingHTTPServer(("127.0.0.1", 0), FrontendBridgeHandler)
    server.state = state
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        # 1. Unauthenticated loopback read to /api/config and /data/config is denied; master succeeds.
        with pytest.raises(HTTPError) as unauth_cfg:
            _http_request(f"{base}/api/config")
        assert unauth_cfg.value.code == HTTPStatus.FORBIDDEN

        with pytest.raises(HTTPError) as unauth_yaml:
            _http_request(f"{base}/data/config/api.yaml")
        assert unauth_yaml.value.code == HTTPStatus.FORBIDDEN

        with _http_request(
            f"{base}/api/config",
            headers={"X-Shinsekai-Bridge-Token": state.auth_token},
        ) as resp:
            assert json.loads(resp.read())["api_config"]["llm_api_key"] == "sk-top-secret"

        # 2. Plugin token cannot read /api/config, /api/agent/*, /data/*, or another plugin's tools.
        for path in (
            "/api/config",
            "/api/config/api",
            "/api/download?path=data/config/api.yaml",
            "/data/config/api.yaml",
            "/assets/../data/config/api.yaml",
            "/api/agent/status",
            "/api/plugins/com.evil.other/tools",
        ):
            with pytest.raises(HTTPError) as denied:
                _http_request(
                    f"{base}{path}",
                    headers={"X-Shinsekai-Bridge-Token": plugin_token},
                )
            assert denied.value.code == HTTPStatus.FORBIDDEN, path

        for method, path, body in (
            ("POST", "/api/config/api", {"llm_api_key": "hijacked"}),
            ("POST", "/api/plugins/com.evil.other/tools/x/invoke", {"arguments": {}}),
            ("POST", "/api/plugins/install", {"source": "bad"}),
            ("POST", "/api/chat/command", {"type": "clear-history"}),
        ):
            with pytest.raises(HTTPError) as denied:
                _http_request(
                    f"{base}{path}",
                    method=method,
                    headers={"X-Shinsekai-Bridge-Token": plugin_token},
                    body=body,
                )
            assert denied.value.code == HTTPStatus.FORBIDDEN, (method, path)

        # 3. Loading plugin frontend page via ?shinsekai_bridge_token sets path-isolated cookie.
        with _http_request(
            f"{base}/api/plugins/com.demo.game/frontend/board/index.html"
            f"?shinsekai_bridge_token={plugin_token}"
        ) as resp:
            assert b"plugin" in resp.read()
            cookie_hdr = resp.headers["Set-Cookie"]
            assert cookie_hdr.startswith(f"{PLUGIN_AUTH_COOKIE}={plugin_token};")
            assert "Path=/api/plugins/com.demo.game/;" in cookie_hdr
            assert "shinsekai_bridge_token=" not in cookie_hdr

        # 4. Path-scoped plugin cookie works for own tools & UI but fails elsewhere.
        with _http_request(
            f"{base}/api/plugins/com.demo.game/tools",
            headers={"Cookie": f"{PLUGIN_AUTH_COOKIE}={plugin_token}"},
        ) as resp:
            assert json.loads(resp.read()) == [{"name": "roll", "pluginId": "com.demo.game"}]

        with pytest.raises(HTTPError) as cookie_cfg_denied:
            _http_request(
                f"{base}/api/config",
                headers={"Cookie": f"{PLUGIN_AUTH_COOKIE}={plugin_token}"},
            )
        assert cookie_cfg_denied.value.code == HTTPStatus.FORBIDDEN

        # 5. Plugin can invoke its own tools, list session-behaviors, and read chat snapshot.
        with _http_request(
            f"{base}/api/plugins/com.demo.game/tools/roll/invoke",
            method="POST",
            headers={"X-Shinsekai-Bridge-Token": plugin_token},
            body={"arguments": {"sides": 6}},
        ) as resp:
            assert json.loads(resp.read()) == {"ok": True}
        assert tool_calls == [("com.demo.game", "roll", {"sides": 6})]

        with _http_request(
            f"{base}/api/plugins/session-behaviors",
            headers={"X-Shinsekai-Bridge-Token": plugin_token},
        ) as resp:
            assert json.loads(resp.read())["behaviors"][0]["behaviorId"] == "werewolf"

        with _http_request(
            f"{base}/api/chat/snapshot",
            headers={"X-Shinsekai-Bridge-Token": plugin_token},
        ) as resp:
            assert json.loads(resp.read())["status"] == "running"

        # 6. /api/chat/behavior-command succeeds only for owning plugin token.
        with _http_request(
            f"{base}/api/chat/behavior-command",
            method="POST",
            headers={"X-Shinsekai-Bridge-Token": plugin_token},
            body={"commandId": "c1", "action": "vote", "expectedStateVersion": 1},
        ) as resp:
            assert json.loads(resp.read())["status"] == "running"
        assert command_calls[-1]["type"] == "behavior-command"
        assert command_calls[-1]["payload"]["action"] == "vote"

        with pytest.raises(HTTPError) as non_owner_denied:
            _http_request(
                f"{base}/api/chat/behavior-command",
                method="POST",
                headers={"X-Shinsekai-Bridge-Token": other_token},
                body={"commandId": "c2", "action": "vote", "expectedStateVersion": 1},
            )
        assert non_owner_denied.value.code == HTTPStatus.FORBIDDEN
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_resolve_issued_plugin_cookie_header_and_cors_use_server_cookie() -> None:
    master = "server-master-secret"
    issued = issue_plugin_token(master, "demo/plugin")

    header = resolve_issued_plugin_cookie_header(
        master,
        "/api/plugins/demo%2Fplugin/frontend/board/index.html",
        issued,
    )
    assert header is not None
    assert header.startswith(f"{PLUGIN_AUTH_COOKIE}={issued};")
    assert "Path=/api/plugins/demo%2Fplugin/;" in header
    assert "HttpOnly" in header
    assert "SameSite=Strict" in header

    assert (
        resolve_issued_plugin_cookie_header(
            master,
            "/api/plugins/other.plugin/frontend/board/index.html",
            issued,
        )
        is None
    )
    assert (
        resolve_issued_plugin_cookie_header(
            master,
            "/api/plugins/demo%2Fplugin/../other/frontend/",
            issued,
        )
        is None
    )
    assert (
        resolve_issued_plugin_cookie_header(
            master,
            "/api/plugins/demo%2Fplugin/frontend/board/index.html",
            "shp1.forged.token",
        )
        is None
    )

    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    sent_headers: list[tuple[str, str]] = []
    handler.server = SimpleNamespace(state=SimpleNamespace(auth_token=master))  # type: ignore[assignment]
    handler.path = (
        "/api/plugins/demo%2Fplugin/frontend/board/index.html"
        f"?shinsekai_bridge_token={issued}"
    )
    handler.headers = {}  # type: ignore[assignment]
    handler.send_header = lambda k, v: sent_headers.append((k, v))  # type: ignore[method-assign]
    handler._send_cors()
    assert ("Set-Cookie", header) in sent_headers
