from types import SimpleNamespace

from ai.tools import reminder_tools
from application.reminders import management
from application.runtime.context import _ApplicationLLMHostRuntime
from sdk.llm_runtime import NullLLMHostRuntime
from sdk.tool_registry import iter_registered_tools
from frontend_bridge_core.routes.api import FrontendBridgeHandler
from frontend_bridge_core.routes.router import ApiRequest


def test_character_tool_and_bridge_share_schedules(tmp_path, monkeypatch):
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(tmp_path))
    config = SimpleNamespace(config=SimpleNamespace(characters=[SimpleNamespace(name="澪")]))
    monkeypatch.setattr(management, "ConfigManager", lambda: config)
    monkeypatch.setattr(reminder_tools, "get_llm_host_runtime", _ApplicationLLMHostRuntime)
    state = SimpleNamespace(project_root_dir=str(tmp_path), config_manager=config)

    def call(method, path, body=None):
        matched = FrontendBridgeHandler.api_router.match(method, path)
        assert matched
        return matched.route.handler(ApiRequest(state, method, path, {}, matched.params, body or {})).data

    created = reminder_tools.manage_reminders("create", character_name="澪", title="喝水", message="喝点水吧！", delay_minutes="10")
    assert created["ok"]
    item = created["reminder"]
    assert call("GET", "/api/reminders")["reminders"] == [item]
    assert call("POST", "/api/reminders/claim") == []
    assert call("POST", "/api/reminders", {"action": "update", "reminder_id": item["id"], "title": "休息"})["ok"]
    assert reminder_tools.manage_reminders("list")["reminders"][0]["title"] == "休息"
    assert call("POST", "/api/reminders", {"action": "cancel", "reminder_id": item["id"]})["ok"]
    assert reminder_tools.manage_reminders("list")["reminders"][0]["status"] == "cancelled"
    assert not reminder_tools.manage_reminders("update", reminder_id=item["id"], title="新标题")["ok"]


def test_scheduling_tool_is_available_to_every_character_without_search():
    registrations = [entry for entry in iter_registered_tools() if (entry[1] or entry[0].__name__) == "manage_reminders"]
    assert registrations
    assert registrations[0][3] == "default"


def test_tool_returns_failure_instead_of_claiming_unsaved_reminder(tmp_path, monkeypatch):
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(management, "ConfigManager", lambda: SimpleNamespace(config=SimpleNamespace(characters=[])))
    monkeypatch.setattr(reminder_tools, "get_llm_host_runtime", _ApplicationLLMHostRuntime)
    result = reminder_tools.manage_reminders("create", character_name="不存在", title="睡觉", message="晚安", delay_minutes="10")
    assert result["ok"] is False
    assert reminder_tools.manage_reminders("list")["reminders"] == []


def test_tool_without_host_reports_unavailable(monkeypatch):
    monkeypatch.setattr(reminder_tools, "get_llm_host_runtime", NullLLMHostRuntime)
    assert reminder_tools.manage_reminders("list") == {"ok": False, "error": "reminder host is not available"}
