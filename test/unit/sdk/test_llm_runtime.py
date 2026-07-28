from __future__ import annotations

from sdk.llm_runtime import (
    NullLLMHostRuntime,
    get_llm_host_runtime,
    set_llm_host_runtime,
)


def test_null_llm_host_runtime_fails_closed_for_high_risk_tools():
    runtime = NullLLMHostRuntime()

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
