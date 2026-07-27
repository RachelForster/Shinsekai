from __future__ import annotations

import pytest

from plugin_system.host import service as plugin_host
from sdk.frontend_user_input import (
    FrontendUserInputController,
    _bind_frontend_user_input_dispatcher,
)
from sdk.register import PluginCapabilityRegistry


@pytest.fixture(autouse=True)
def reset_frontend_user_input_dispatcher():
    _bind_frontend_user_input_dispatcher(None)
    yield
    _bind_frontend_user_input_dispatcher(None)


def plugin_controller(
    plugin_id: str = "demo.plugin",
) -> FrontendUserInputController:
    registry = PluginCapabilityRegistry()
    registry.set_settings_ui_plugin_context(plugin_id, "1.0.0")
    return registry.frontend_user_input()


def test_frontend_user_input_controller_is_bound_to_initializing_plugin() -> None:
    registry = PluginCapabilityRegistry()

    with pytest.raises(RuntimeError, match="PluginBase.initialize"):
        registry.frontend_user_input()

    controller = plugin_controller()
    assert controller.plugin_id == "demo.plugin"
    with pytest.raises(TypeError, match=r"register\.frontend_user_input"):
        FrontendUserInputController("spoofed.plugin")


def test_frontend_user_input_controller_submits_scoped_text() -> None:
    events: list[dict] = []
    plugin_host.bind_frontend_user_input_runtime(events.append)

    plugin_controller().submit_text("  [短信] 请角色回复  ")

    assert events == [
        {
            "type": "plugin.user-input.submit",
            "pluginId": "demo.plugin",
            "text": "[短信] 请角色回复",
        }
    ]


def test_frontend_user_input_controller_rejects_unavailable_or_invalid_input() -> None:
    controller = plugin_controller()

    with pytest.raises(RuntimeError, match="No active React Chat runtime"):
        controller.submit_text("hello")

    plugin_host.bind_frontend_user_input_runtime(lambda event: None)
    with pytest.raises(ValueError, match="cannot be empty"):
        controller.submit_text("  ")
    with pytest.raises(ValueError, match="cannot exceed"):
        controller.submit_text("x" * (64 * 1024 + 1))
