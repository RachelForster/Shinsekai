"""History commands with explicit, ordered branch participants."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from application.chat.dispatch_commands import CommandContext, CommandRegistry


@dataclass(frozen=True)
class HistoryCommandBindings:
    copy_payload: Callable[[], dict[str, Any]]
    open_payload: Callable[[], dict[str, Any]]
    clear_storage: Callable[[], None]
    features: Callable[[], dict[str, bool]]


@dataclass(frozen=True)
class HistoryParticipant:
    discard: Callable[[], None]
    before_branch: Callable[[str, dict[str, Any]], None]
    after_branch: Callable[[], None]


def register_history_commands(
    registry: CommandRegistry, bindings: HistoryCommandBindings, participant: HistoryParticipant,
) -> None:
    def copy_history(context: CommandContext) -> dict[str, Any]:
        return context.ports.snapshot("idle", "历史记录已复制。", extra=bindings.copy_payload())

    def open_history(context: CommandContext) -> dict[str, Any]:
        return context.ports.snapshot("idle", "历史文件已打开。", extra=bindings.open_payload())

    def clear_history(context: CommandContext) -> dict[str, Any]:
        participant.discard()
        patch = {"historyEntries": [], "options": []}
        if context.ports.session_id and context.ports.stream is not None:
            return context.forward("idle", "历史记录已经清空。", snapshot_patch=patch)
        bindings.clear_storage()
        return context.ports.snapshot("idle", "历史记录已经清空。", extra=patch)

    registry.register("copy-history", copy_history)

    registry.register("open-history", open_history)

    registry.register("clear-history", clear_history)

    def revert_history(context: CommandContext) -> dict[str, Any]:
        command = context.command
        body = context.body
        try:
            int(body.get("payload"))
        except (TypeError, ValueError) as exc:
            raise ValueError("回溯索引无效。") from exc
        participant.before_branch(command, body)
        result = context.forward("idle")
        participant.after_branch()
        return result

    registry.register("revert-history", revert_history)

    def fork_history(context: CommandContext) -> dict[str, Any]:
        command = context.command
        body = context.body
        if not bindings.features()["forkHistory"]:
            raise PermissionError("React Chat UI Fork 实验功能未启用。")
        payload = body.get("payload")
        raw_index = payload.get("userIndex") if isinstance(payload, dict) else payload
        try:
            int(raw_index)
        except (TypeError, ValueError) as exc:
            raise ValueError("分支索引无效。") from exc
        participant.before_branch(command, body)
        result = context.forward("generating", "正在创建对话分支。")
        participant.after_branch()
        return result

    registry.register("fork-history", fork_history)

    def switch_branch(context: CommandContext) -> dict[str, Any]:
        command = context.command
        body = context.body
        if not bindings.features()["conversationTree"]:
            raise PermissionError("React Chat UI 分支流程图实验功能未启用。")
        branch_id = str(body.get("payload") or "").strip()
        if not branch_id:
            raise ValueError("分支 id 不能为空。")
        participant.before_branch(command, body)
        result = context.forward("idle", "已切换对话分支。")
        participant.after_branch()
        return result

    registry.register("switch-branch", switch_branch)

    def rename_branch(context: CommandContext) -> dict[str, Any]:
        body = context.body
        if not bindings.features()["conversationTree"]:
            raise PermissionError("React Chat UI 分支流程图实验功能未启用。")
        payload = body.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("分支重命名参数无效。")
        branch_id = str(payload.get("branchId") or "").strip()
        label = str(payload.get("label") or "").strip()
        if not branch_id:
            raise ValueError("分支 id 不能为空。")
        if not label:
            raise ValueError("分支名称不能为空。")
        return context.forward("idle", "已重命名对话分支。")

    registry.register("rename-branch", rename_branch)
