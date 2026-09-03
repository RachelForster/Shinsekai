"""Tool discovery, activation, budgeting, and execution for ``LLMManager``."""

import json
from typing import Any

from ai.llm.chat_types import notify_tool_call_hint, tool_result_status


class ToolCallingMixin:
    """Implements tool governance while leaving chat orchestration to the manager."""

    def _current_tool_definitions(self) -> list[dict]:
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

        definitions = self.tools_manager.get_definitions(
            groups=self._active_tool_groups
        )
        available: list[dict] = []
        filtered: list[dict[str, str]] = []
        for definition in definitions:
            function = definition.get("function", {})
            name = str(function.get("name") or "")
            group = self.tools_manager.get_tool_group(name)
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
                non_default = [
                    group for group in self._active_tool_groups if group != "default"
                ]
                self._active_tool_groups = non_default[
                    : self._max_active_groups - 1
                ] + ["default"]
            else:
                self._active_tool_groups = self._active_tool_groups[
                    : self._max_active_groups
                ]

    def _activate_tool_group_from_search(self, function_args: Any) -> None:
        try:
            parsed = (
                json.loads(function_args)
                if isinstance(function_args, str)
                else function_args
            )
            keyword = (
                (parsed.get("keyword") or "").strip().lower()
                if isinstance(parsed, dict)
                else ""
            )
            if not keyword:
                return
            for group in self.tools_manager.get_groups():
                if keyword in group.lower():
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

    def _cooldown_skipped_tool_result(
        self, tool_name: str, cooldown_message: str
    ) -> str:
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

    def _repeated_failure_tool_result(
        self, tool_name: str, previous_status: str
    ) -> str:
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
        function_name = call["function"]["name"]
        function_args = call["function"]["arguments"]
        if isinstance(function_args, str) and not function_args.strip():
            function_args = "{}"

        state = self._turn_state
        if state is not None and state.tool_budget_exhausted():
            state.tool_calls_skipped += 1
            result = self._budget_exhausted_tool_result(function_name)
            self.logger.info(
                "Tool call skipped by first-turn budget",
                extra={
                    "event": "tool.call.skipped",
                    "tool_name": function_name,
                    "reason": "first_turn_tool_budget_exhausted",
                    "tool_call_attempts": state.tool_call_attempts,
                    "first_turn_tool_call_limit": state.first_turn_tool_call_limit,
                },
            )
            return function_name, result

        if state is not None:
            state.tool_call_attempts += 1
            previous_failure = state.tool_failures.get(function_name)
            if previous_failure:
                state.tool_calls_skipped += 1
                result = self._repeated_failure_tool_result(
                    function_name, previous_failure
                )
                self.logger.info(
                    "Tool call skipped after previous failure in same turn",
                    extra={
                        "event": "tool.call.skipped",
                        "tool_name": function_name,
                        "reason": "tool_failed_earlier_in_turn",
                        "previous_status": previous_failure,
                    },
                )
                return function_name, result

        cooldown_message = self.tool_executor.cooldown_message_for_tool(function_name)
        if cooldown_message is not None:
            if state is not None:
                state.tool_calls_skipped += 1
            result = self._cooldown_skipped_tool_result(function_name, cooldown_message)
            self.logger.info(
                "Tool call skipped because group is in cooldown",
                extra={
                    "event": "tool.call.skipped",
                    "tool_name": function_name,
                    "tool_group": self.tools_manager.get_tool_group(function_name),
                    "reason": "tool_group_in_cooldown",
                },
            )
            return function_name, result

        notify_tool_call_hint(function_name)
        result = self.tool_executor.execute(
            function_name,
            function_args,
            risk_confirm=self._confirm_risky_tool,
        )

        if function_name == "search_tools":
            self._activate_tool_group_from_search(function_args)

        if result is None:
            result = json.dumps({"status": "success", "result": "no return value"})
        elif not isinstance(result, str):
            result = json.dumps(result)

        status = tool_result_status(result)
        if state is not None:
            state.tool_calls_executed += 1
            if status in {"error", "loading", "cancelled"}:
                state.tool_failures[function_name] = status
        self.logger.info(
            "Tool call handled",
            extra={
                "event": "tool.call.handled",
                "tool_name": function_name,
                "tool_group": self.tools_manager.get_tool_group(function_name),
                "status": status,
                "result_chars": len(result or ""),
            },
        )
        return function_name, result
