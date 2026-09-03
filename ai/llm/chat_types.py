"""Provider-neutral chat state and message formatting helpers."""

import copy
from dataclasses import dataclass, field
from datetime import datetime
import json
from typing import Any

from sdk.llm_runtime import get_llm_host_runtime


FIRST_USER_TURN_TOOL_CALL_LIMIT = 1


@dataclass
class ChatTurnState:
    started_at: float
    first_user_turn: bool
    first_turn_tool_call_limit: int
    llm_rounds: int = 0
    tool_call_attempts: int = 0
    tool_calls_executed: int = 0
    tool_calls_skipped: int = 0
    tool_failures: dict[str, str] = field(default_factory=dict)

    def tool_budget_exhausted(self) -> bool:
        return (
            self.first_user_turn
            and self.first_turn_tool_call_limit >= 0
            and self.tool_call_attempts >= self.first_turn_tool_call_limit
        )


def tool_result_status(result: str) -> str:
    if not result:
        return "empty"
    try:
        parsed = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return "raw"
    if not isinstance(parsed, dict):
        return "success"
    if parsed.get("status") == "loading":
        return "loading"
    if parsed.get("cancelled") is True:
        return "cancelled"
    if "error" in parsed:
        return "error"
    return str(parsed.get("status") or "success")


def prefix_user_text_with_local_time(text: Any) -> Any:
    """Prefix user content with the current local date and time."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prefix = f"[本地时间 {timestamp}]"
    if not isinstance(text, list):
        return f"{prefix}\n{text}"
    content = copy.deepcopy(text)
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            block["text"] = f"{prefix}\n{str(block.get('text') or '')}"
            return content
    content.insert(0, {"type": "text", "text": prefix})
    return content


def notify_tool_call_hint(tool_name: str) -> None:
    """Ask the injected host to surface the active tool call."""
    try:
        get_llm_host_runtime().notify_tool_call(tool_name)
    except Exception:
        pass
