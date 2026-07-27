from __future__ import annotations

from types import SimpleNamespace

import pytest

from plugin_system.host import service as plugin_host
from sdk.frontend_ui import FrontendUIController, _bind_frontend_ui_dispatcher
from sdk.register import PluginCapabilityRegistry


@pytest.fixture(autouse=True)
def reset_frontend_ui_dispatcher():
    _bind_frontend_ui_dispatcher(None)
    yield
    _bind_frontend_ui_dispatcher(None)


def plugin_controller(
    plugin_id: str = "demo.plugin",
) -> FrontendUIController:
    registry = PluginCapabilityRegistry()
    registry.set_settings_ui_plugin_context(plugin_id, "1.0.0")
    return registry.frontend_ui()


def test_frontend_ui_controller_is_bound_to_initializing_plugin() -> None:
    registry = PluginCapabilityRegistry()

    with pytest.raises(RuntimeError, match="PluginBase.initialize"):
        registry.frontend_ui()

    registry.set_settings_ui_plugin_context("demo.plugin", "1.0.0")
    controller = registry.frontend_ui()
    registry.clear_settings_ui_plugin_context()

    assert controller.plugin_id == "demo.plugin"
    with pytest.raises(TypeError, match=r"register\.frontend_ui"):
        FrontendUIController("spoofed.plugin")


def test_frontend_ui_controller_presents_and_dismisses_json_payload() -> None:
    events: list[dict] = []
    _bind_frontend_ui_dispatcher(events.append)
    controller = plugin_controller()

    presentation_id = controller.present_page(
        "dashboard",
        presentation_id="notice-42",
        payload={"kind": "reminder", "nested": {"items": [1, True, None]}},
    )
    controller.dismiss_page(presentation_id)

    assert presentation_id == "notice-42"
    assert events == [
        {
            "type": "plugin.page.present",
            "mode": "overlay",
            "pageId": "dashboard",
            "payload": {
                "kind": "reminder",
                "nested": {"items": [1, True, None]},
            },
            "pluginId": "demo.plugin",
            "presentationId": "notice-42",
        },
        {
            "type": "plugin.page.dismiss",
            "pluginId": "demo.plugin",
            "presentationId": "notice-42",
        },
    ]


def test_frontend_ui_controller_rejects_unavailable_runtime_and_unsafe_payloads() -> None:
    controller = plugin_controller()

    with pytest.raises(RuntimeError, match="No active React Chat runtime"):
        controller.present_page("dashboard")

    _bind_frontend_ui_dispatcher(lambda event: None)
    with pytest.raises(ValueError, match="JSON-safe"):
        controller.present_page("dashboard", payload={"bad": object()})
    with pytest.raises(ValueError, match="only overlay"):
        controller.present_page("dashboard", mode="navigate")
    with pytest.raises(ValueError, match="cannot exceed"):
        controller.present_page("dashboard", payload={"large": "x" * (16 * 1024)})


def test_host_dispatcher_allows_only_pages_registered_by_the_calling_plugin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[dict] = []
    monkeypatch.setattr(
        plugin_host,
        "collect_frontend_page_contributions",
        lambda: [
            SimpleNamespace(page_id="dashboard", plugin_id="demo.plugin"),
            SimpleNamespace(page_id="settings", plugin_id="other.plugin"),
        ],
    )
    plugin_host.bind_frontend_ui_runtime(events.append)
    controller = plugin_controller()

    controller.present_page("dashboard", presentation_id="ok")

    with pytest.raises(ValueError, match="not registered"):
        controller.present_page("settings", presentation_id="blocked")
    assert [event["presentationId"] for event in events] == ["ok"]
