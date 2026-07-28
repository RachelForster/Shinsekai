"""Host callbacks exposed to LLM capabilities without importing application code."""

from __future__ import annotations

from typing import Protocol


class LLMHostRuntime(Protocol):
    """Application services that the LLM layer may request through injection."""

    def notify_tool_call(self, tool_name: str) -> None: ...

    def confirm_risky_tool(
        self,
        tool_name: str,
        risk: str,
        args_text: str,
    ) -> bool: ...

    def post_context_token_estimate(self, estimate: dict[str, int]) -> None: ...

    def notify_tool_ready(self, group: str, message: str) -> None: ...

    def set_user_display_name(self, display_name: str) -> str | None: ...


class NullLLMHostRuntime:
    """Safe defaults for tests, tools, and non-host LLM consumers."""

    def notify_tool_call(self, tool_name: str) -> None:
        del tool_name

    def confirm_risky_tool(
        self,
        tool_name: str,
        risk: str,
        args_text: str,
    ) -> bool:
        del tool_name, args_text
        return str(risk or "").casefold() != "high"

    def post_context_token_estimate(self, estimate: dict[str, int]) -> None:
        del estimate

    def notify_tool_ready(self, group: str, message: str) -> None:
        del group, message

    def set_user_display_name(self, display_name: str) -> str | None:
        del display_name
        return "chat runtime is not ready"


_runtime: LLMHostRuntime = NullLLMHostRuntime()


def set_llm_host_runtime(runtime: LLMHostRuntime | None) -> None:
    """Install the host adapter; ``None`` restores safe standalone behavior."""

    global _runtime
    _runtime = runtime or NullLLMHostRuntime()


def get_llm_host_runtime() -> LLMHostRuntime:
    return _runtime


def reset_llm_host_runtime() -> None:
    set_llm_host_runtime(None)
