"""Unit tests for workspace plugin UI bridge endpoints, SDK assets, and HTML injection."""

from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from application.runtime.state import BridgeState
from frontend_bridge_core import plugin_ui_extensions
from frontend_bridge_core.plugin_auth import is_plugin_route_allowed, issue_plugin_token
from frontend_bridge_core.plugin_sdk_assets import (
    SDK_HOST_BRIDGE_JS_PATH,
    SDK_THEME_CSS_PATH,
    SDK_UI_CSS_PATH,
    inject_plugin_sdk_into_html,
    resolve_sdk_asset,
)
from frontend_bridge_core.routes.api import BRIDGE_AUTH_HEADER, FrontendBridgeHandler
from frontend_bridge_core.routes.plugin_routes import PLUGIN_ROUTES
from frontend_bridge_core.routes.router import ApiRequest, Router
from sdk.types import (
    FrontendChatUIContribution,
    FrontendConfigAction,
    FrontendPageContribution,
    FrontendSectionContribution,
)


def _state(auth_token: str = "master-secret") -> BridgeState:
    return BridgeState(
        background_manager=None,
        character_manager=None,
        config_manager=None,
        template_generator=None,
        auth_token=auth_token,
        chat_session={},
    )


def _dispatch(
    router: Router,
    state: BridgeState,
    method: str,
    path: str,
    body: dict | None = None,
    query: dict | None = None,
):
    matched = router.match(method, path)
    assert matched is not None
    req = ApiRequest(
        state=state,
        method=method,
        path=path,
        query=query or {},
        params=matched.params,
        body=body or {},
    )
    return matched.route.handler(req)


def test_sdk_assets_resolve_and_inject_once() -> None:
    for path, expected_ct in (
        (SDK_THEME_CSS_PATH, "text/css"),
        (SDK_UI_CSS_PATH, "text/css"),
        (SDK_HOST_BRIDGE_JS_PATH, "application/javascript"),
    ):
        resolved = resolve_sdk_asset(path)
        assert resolved is not None
        content_type, payload = resolved
        assert expected_ct in content_type
        assert len(payload) > 20

    assert b"--theme-accent" in resolve_sdk_asset(SDK_THEME_CSS_PATH)[1]
    assert b".sk-card" in resolve_sdk_asset(SDK_UI_CSS_PATH)[1]
    assert b"window.ShinsekaiHost" in resolve_sdk_asset(SDK_HOST_BRIDGE_JS_PATH)[1]

    raw_html = b"<!doctype html><html><head><title>Demo</title></head><body>Hi</body></html>"
    injected = inject_plugin_sdk_into_html(raw_html)
    assert injected.count(SDK_HOST_BRIDGE_JS_PATH.encode("utf-8")) == 1
    assert inject_plugin_sdk_into_html(injected) == injected


def test_sdk_assets_and_plugin_html_injection_over_http(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin_root = tmp_path / "plugins" / "demo_plugin" / "ui"
    plugin_root.mkdir(parents=True)
    index_html = plugin_root / "index.html"
    index_html.write_text("<html><head></head><body>Board</body></html>", encoding="utf-8")

    pages = {
        "board": FrontendPageContribution(
            plugin_id="demo.plugin",
            plugin_version="1.0.0",
            page_id="board",
            title="Board",
            entry="ui/index.html",
            inject_host_theme=True,
        ),
        "raw": FrontendPageContribution(
            plugin_id="demo.plugin",
            plugin_version="1.0.0",
            page_id="raw",
            title="Raw",
            entry="ui/raw.html",
            inject_host_theme=False,
        ),
    }

    monkeypatch.setattr(
        "frontend_bridge_core.routes.file_transport._resolve_plugin_frontend_file",
        lambda plugin_id, page_id, asset="": index_html,
    )
    monkeypatch.setattr(
        "frontend_bridge_core.routes.file_transport._should_inject_host_theme",
        lambda plugin_id, page_id: pages[page_id].inject_host_theme,
    )

    state = _state("master-secret")

    server = ThreadingHTTPServer(("127.0.0.1", 0), FrontendBridgeHandler)
    server.state = state  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        # SDK CSS & JS load without bearer auth, but reject bogus tokens
        with urlopen(f"{base}{SDK_THEME_CSS_PATH}", timeout=5) as resp:
            assert resp.status == HTTPStatus.OK
            assert b"--theme-accent" in resp.read()

        with pytest.raises(HTTPError) as err_info:
            urlopen(Request(f"{base}{SDK_HOST_BRIDGE_JS_PATH}", headers={BRIDGE_AUTH_HEADER: "wrong"}), timeout=5)
        assert err_info.value.code == HTTPStatus.FORBIDDEN

        scoped_token = issue_plugin_token("master-secret", "demo.plugin")
        with urlopen(
            f"{base}/api/plugins/demo.plugin/frontend/board/index.html?shinsekai_bridge_token={scoped_token}",
            timeout=5,
        ) as board_resp:
            body = board_resp.read().decode("utf-8")
            assert SDK_THEME_CSS_PATH in body
            assert SDK_HOST_BRIDGE_JS_PATH in body

        with urlopen(
            f"{base}/api/plugins/demo.plugin/frontend/raw/index.html?shinsekai_bridge_token={scoped_token}",
            timeout=5,
        ) as raw_resp:
            body = raw_resp.read().decode("utf-8")
            assert SDK_HOST_BRIDGE_JS_PATH not in body
    finally:
        server.shutdown()
        server.server_close()


def test_sidebar_pages_sections_and_contextual_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    saved_payloads: list[tuple[dict, str, str]] = []
    action_contexts: list[tuple[str, str, str]] = []
    values_store = {"roles": 9}

    page = FrontendPageContribution(
        plugin_id="werewolf.plugin",
        plugin_version="1.0.0",
        page_id="lobby",
        title="Werewolf Lobby",
        entry="ui/index.html",
        nav_label="Lobby",
        nav_icon="gamepad",
        show_in_sidebar=True,
        order=10,
        i18n={"zh_CN": {"navLabel": "狼人杀大厅"}},
    )
    section = FrontendSectionContribution(
        plugin_id="werewolf.plugin",
        plugin_version="1.0.0",
        section_id="rules",
        page="template",
        slot="sidebar",
        title="Werewolf Rules",
        nav_label="Rules",
        renderer="schema",
        schema=[{"id": "main", "title": "Main", "fields": [{"key": "roles", "label": "Roles", "type": "integer"}]}],
        load_values=lambda ctx: {"roles": values_store["roles"], "entity": ctx.entity_id},
        save_values=lambda vals, ctx: (
            values_store.update({"roles": int(vals.get("roles", 9))}),
            saved_payloads.append((dict(vals), ctx.entity_id, ctx.locale)),
            {"kind": "success", "i18nMessage": {"zh_CN": "规则已保存", "en": "Rules saved"}, "refresh": ["templates"]},
        )[-1],
        actions=[
            FrontendConfigAction(
                id="reset",
                label="Reset",
                run=lambda vals, ctx: {"kind": "info", "message": f"reset:{ctx.entity_id}", "refresh": ["templates", "bad-key"]},
            )
        ],
    )
    slot_action = FrontendChatUIContribution(
        plugin_id="werewolf.plugin",
        plugin_version="1.0.0",
        contribution_id="quick-setup",
        slot="template-header-actions",
        title="Quick Setup",
        icon="wand",
        action=lambda ctx: (
            action_contexts.append((ctx.page, ctx.entity_id, ctx.locale)),
            {"kind": "success", "i18nMessage": {"en": f"Setup {ctx.entity_id}"}, "refresh": ["templates"]},
        )[-1],
    )

    monkeypatch.setattr(plugin_ui_extensions, "frontend_page_contributions", lambda: [page])
    monkeypatch.setattr(plugin_ui_extensions, "frontend_section_contributions", lambda: [section])
    monkeypatch.setattr(plugin_ui_extensions, "frontend_chat_ui_contributions", lambda: [slot_action])

    state = _state("secret")
    router = Router(PLUGIN_ROUTES)

    sidebar_res = _dispatch(router, state, "GET", "/api/plugins/sidebar-pages")
    assert sidebar_res.status == HTTPStatus.OK
    assert sidebar_res.data["pages"][0]["navIcon"] == "gamepad"
    assert "shinsekai_bridge_token=" in sidebar_res.data["pages"][0]["frontendUrl"]

    sections_res = _dispatch(
        router,
        state,
        "GET",
        "/api/plugins/sections",
        query={"page": ["templates"], "entityType": ["template"], "entityId": ["tpl-1"], "locale": ["en"]},
    )
    assert sections_res.status == HTTPStatus.OK
    assert sections_res.data["sections"][0]["slot"] == "sidebar"
    assert sections_res.data["sections"][0]["values"]["entity"] == "tpl-1"

    save_res = _dispatch(
        router,
        state,
        "POST",
        "/api/plugins/werewolf.plugin/sections/rules/values",
        body={"values": {"roles": 12}, "context": {"entityType": "template", "entityId": "tpl-1", "locale": "zh_CN"}},
    )
    assert save_res.status == HTTPStatus.OK
    assert save_res.data["i18nMessage"] == {"zh_CN": "规则已保存", "en": "Rules saved"}
    assert save_res.data["refresh"] == ["templates"]
    assert saved_payloads == [({"roles": 12}, "tpl-1", "zh_CN")]

    act_res = _dispatch(
        router,
        state,
        "POST",
        "/api/plugins/werewolf.plugin/sections/rules/actions/reset",
        body={"values": {"roles": 12}, "context": {"entityType": "template", "entityId": "tpl-1"}},
    )
    assert act_res.status == HTTPStatus.OK
    assert act_res.data["message"] == "reset:tpl-1"
    assert act_res.data["refresh"] == ["templates"]

    run_res = _dispatch(
        router,
        state,
        "POST",
        "/api/plugins/werewolf.plugin/chat-ui/quick-setup/run",
        body={"context": {"page": "template", "entityType": "template", "entityId": "tpl-1", "locale": "en"}},
    )
    assert run_res.status == HTTPStatus.OK
    assert run_res.data["i18nMessage"] == {"en": "Setup tpl-1"}
    assert run_res.data["refresh"] == ["templates"]
    assert action_contexts == [("template", "tpl-1", "en")]

    # Scoped token guards allow self section saves & SDK assets, block cross-plugin writes
    assert is_plugin_route_allowed("GET", SDK_THEME_CSS_PATH, "werewolf.plugin")
    assert is_plugin_route_allowed("POST", "/api/plugins/werewolf.plugin/sections/rules/values", "werewolf.plugin")
    assert not is_plugin_route_allowed("POST", "/api/plugins/other.plugin/sections/rules/values", "werewolf.plugin")
