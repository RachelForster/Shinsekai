from __future__ import annotations

from sdk.llm_runtime import (
    NullLLMHostRuntime,
    get_llm_host_runtime,
    reset_llm_host_runtime,
    set_llm_host_runtime,
)


def test_null_llm_host_runtime_fails_closed_for_high_risk_tools():
    runtime = NullLLMHostRuntime()

    runtime.notify_tool_call("read")
    runtime.post_context_token_estimate({"total": 42})
    runtime.notify_tool_ready("filesystem", "ready")
    assert runtime.confirm_risky_tool("write", "high", "{}") is False
    assert runtime.confirm_risky_tool("read", "medium", "{}") is True
    assert runtime.set_user_display_name("Alice") == "chat runtime is not ready"


def test_llm_host_runtime_adapter_can_be_injected_and_restored():
    previous = get_llm_host_runtime()
    replacement = NullLLMHostRuntime()
    try:
        set_llm_host_runtime(replacement)
        assert get_llm_host_runtime() is replacement
    finally:
        set_llm_host_runtime(previous)


def test_llm_host_runtime_reset_installs_fresh_safe_defaults():
    previous = get_llm_host_runtime()
    try:
        reset_llm_host_runtime()
        assert isinstance(get_llm_host_runtime(), NullLLMHostRuntime)
    finally:
        set_llm_host_runtime(previous)
