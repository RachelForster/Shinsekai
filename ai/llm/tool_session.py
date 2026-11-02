"""Per-conversation tool selection, budgets, cooldowns and execution policy."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ai.llm.ports import ToolCatalog, ToolRunner

FIRST_USER_TURN_TOOL_CALL_LIMIT = 1


@dataclass
class _ChatTurnState:
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

def _tool_result_status(result: str) -> str:
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


class ToolSession:
    def __init__(
        self, catalog: ToolCatalog, executor: ToolRunner, *, enabled: bool,
        max_active_groups: int, first_turn_tool_call_limit: int,
        confirm, notify, logger,
    ) -> None:
        self.catalog = catalog
        self.tool_executor = executor
        self.tools_enabled = enabled
        self._max_active_groups = max_active_groups
        self.first_turn_tool_call_limit = first_turn_tool_call_limit
        self._active_tool_groups = ["default"]
        self._turn_state: _ChatTurnState | None = None
        self._confirm_risky_tool = confirm
        self.notify = notify
        self.logger = logger

    def finish_turn(self) -> None:
        state = self._turn_state
        if state is not None:
            self.logger.info(
                "Chat turn profile completed",
                extra={
                    "event": "chat.turn.profile.completed",
                    "duration_ms": round((time.perf_counter() - state.started_at) * 1000, 2),
                    "first_user_turn": state.first_user_turn,
                    "llm_rounds": state.llm_rounds,
                    "tool_call_attempts": state.tool_call_attempts,
                    "tool_calls_executed": state.tool_calls_executed,
                    "tool_calls_skipped": state.tool_calls_skipped,
                    "tool_failures": dict(state.tool_failures),
                },
            )
        self._turn_state = None
        self._reset_active_tool_groups()

    def _begin_chat_turn(self, *, first_user_turn: bool) -> None:
        self._turn_state = _ChatTurnState(
            started_at=time.perf_counter(),
            first_user_turn=first_user_turn,
            first_turn_tool_call_limit=self.first_turn_tool_call_limit,
        )
        self.logger.info(
            "Chat turn profile started",
            extra={
                "event": "chat.turn.profile.started",
                "first_user_turn": first_user_turn,
                "first_turn_tool_call_limit": self.first_turn_tool_call_limit,
            },
        )

    def _next_llm_round(self) -> int:
        if self._turn_state is None:
            return 1
        self._turn_state.llm_rounds += 1
        return self._turn_state.llm_rounds

    def _current_tool_definitions(self) -> list[dict]:
        if not self.tools_enabled:
            return []
        state = self._turn_state
        if state is not None and state.tool_budget_exhausted():
            self.logger.info(
                "LLM tools disabled by first-turn tool budget",
                extra={
                    "event": "ai.tools.disabled",
                    "reason": "first_turn_tool_budget_exhausted",
                    "tool_call_attempts": state.tool_call_attempts,
                    "first_turn_tool_call_limit": state.first_turn_tool_call_limit,
                },
            )
            return []

        defs = self.catalog.get_definitions(groups=self._active_tool_groups)
        available: list[dict] = []
        filtered: list[dict[str, str]] = []
        for definition in defs:
            func = definition.get("function", {})
            name = str(func.get("name") or "")
            group = self.catalog.get_tool_group(name)
            if self.tool_executor.is_in_cooldown(group):
                filtered.append({"name": name, "group": group})
                continue
            available.append(definition)

        if filtered:
            self.logger.info(
                "Filtered tool definitions in cooldown",
                extra={
                    "event": "ai.tools.filtered",
                    "filtered_tool_count": len(filtered),
                    "filtered_groups": sorted({item["group"] for item in filtered}),
                    "filtered_tools": [item["name"] for item in filtered],
                },
            )
        return available

    def _reset_active_tool_groups(self) -> None:
        self._active_tool_groups = ["default"]

    def _activate_tool_group(self, group: str) -> None:
        if not group:
            return
        if group in self._active_tool_groups:
            self._active_tool_groups.remove(group)
        self._active_tool_groups.insert(0, group)
        if "default" not in self._active_tool_groups:
            self._active_tool_groups.append("default")
        if len(self._active_tool_groups) > self._max_active_groups:
            if "default" in self._active_tool_groups and self._max_active_groups > 1:
                non_default = [g for g in self._active_tool_groups if g != "default"]
                self._active_tool_groups = non_default[: self._max_active_groups - 1] + ["default"]
            else:
                self._active_tool_groups = self._active_tool_groups[: self._max_active_groups]

    def _activate_tool_group_from_search(self, func_args: Any) -> None:
        try:
            parsed = json.loads(func_args) if isinstance(func_args, str) else func_args
            kw = (parsed.get("keyword") or "").strip().lower() if isinstance(parsed, dict) else ""
            if not kw:
                return
            for group in self.catalog.get_groups():
                if kw in group.lower():
                    self._activate_tool_group(group)
        except Exception:
            pass

    def _budget_exhausted_tool_result(self, tool_name: str) -> str:
        return json.dumps(
            {
                "status": "skipped",
                "reason": "first_turn_tool_budget_exhausted",
                "message": (
                    f"首轮工具调用预算已用完，已跳过 {tool_name}。"
                    "请基于已有信息直接回复用户，不要继续调用工具。"
                ),
            },
            ensure_ascii=False,
        )

    def _cooldown_skipped_tool_result(self, tool_name: str, cooldown_message: str) -> str:
        try:
            parsed = json.loads(cooldown_message)
        except (json.JSONDecodeError, TypeError):
            parsed = {"status": "loading", "message": str(cooldown_message or "")}
        if isinstance(parsed, dict):
            parsed.setdefault("status", "skipped")
            parsed["tool"] = tool_name
            parsed["reason"] = "tool_group_in_cooldown"
            parsed["message"] = (
                str(parsed.get("message") or "")
                + " 请基于已有信息直接回复用户，不要继续调用这个工具组。"
            ).strip()
        return json.dumps(parsed, ensure_ascii=False)

    def _repeated_failure_tool_result(self, tool_name: str, previous_status: str) -> str:
        return json.dumps(
            {
                "status": "skipped",
                "reason": "tool_failed_earlier_in_turn",
                "tool": tool_name,
                "previous_status": previous_status,
                "message": (
                    f"{tool_name} 已在本轮失败或不可用，已跳过重复调用。"
                    "请基于已有信息直接回复用户。"
                ),
            },
            ensure_ascii=False,
        )

    def _execute_formatted_tool_call(self, call: dict) -> tuple[str, str]:
        if not self.tools_enabled:
            raise ValueError("Tools are disabled for this LLM workflow")
        func_name = call["function"]["name"]
        func_args = call["function"]["arguments"]
        if isinstance(func_args, str) and not func_args.strip():
            func_args = "{}"

        state = self._turn_state
        if state is not None and state.tool_budget_exhausted():
            state.tool_calls_skipped += 1
            result = self._budget_exhausted_tool_result(func_name)
            self.logger.info(
                "Tool call skipped by first-turn budget",
                extra={
                    "event": "tool.call.skipped",
                    "tool_name": func_name,
                    "reason": "first_turn_tool_budget_exhausted",
                    "tool_call_attempts": state.tool_call_attempts,
                    "first_turn_tool_call_limit": state.first_turn_tool_call_limit,
                },
            )
            return func_name, result

        if state is not None:
            state.tool_call_attempts += 1
            previous_failure = state.tool_failures.get(func_name)
            if previous_failure:
                state.tool_calls_skipped += 1
                result = self._repeated_failure_tool_result(func_name, previous_failure)
                self.logger.info(
                    "Tool call skipped after previous failure in same turn",
                    extra={
                        "event": "tool.call.skipped",
                        "tool_name": func_name,
                        "reason": "tool_failed_earlier_in_turn",
                        "previous_status": previous_failure,
                    },
                )
                return func_name, result

        cooldown_message = self.tool_executor.cooldown_message_for_tool(func_name)
        if cooldown_message is not None:
            if state is not None:
                state.tool_calls_skipped += 1
            result = self._cooldown_skipped_tool_result(func_name, cooldown_message)
            self.logger.info(
                "Tool call skipped because group is in cooldown",
                extra={
                    "event": "tool.call.skipped",
                    "tool_name": func_name,
                    "tool_group": self.catalog.get_tool_group(func_name),
                    "reason": "tool_group_in_cooldown",
                },
            )
            return func_name, result

        self.notify(func_name)
        result = self.tool_executor.execute(
            func_name,
            func_args,
            risk_confirm=self._confirm_risky_tool,
        )

        if func_name == "search_tools":
            self._activate_tool_group_from_search(func_args)

        if result is None:
            result = json.dumps({"status": "success", "result": "no return value"})
        elif not isinstance(result, str):
            result = json.dumps(result)

        status = _tool_result_status(result)
        if state is not None:
            state.tool_calls_executed += 1
            if status in {"error", "loading", "cancelled"}:
                state.tool_failures[func_name] = status
        self.logger.info(
            "Tool call handled",
            extra={
                "event": "tool.call.handled",
                "tool_name": func_name,
                "tool_group": self.catalog.get_tool_group(func_name),
                "status": status,
                "result_chars": len(result or ""),
            },
        )
        return func_name, result
