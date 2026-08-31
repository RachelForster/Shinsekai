"""Manage conversation branch state for an active chat session."""

from __future__ import annotations

from collections.abc import Callable, MutableSequence
import copy
from dataclasses import dataclass
import time
from typing import Any, Protocol

from application.chat.history_state import (
    canonical_user_turn_payload,
    history_entry_plain_text,
    is_user_history_entry,
)
from core.sprite.chat_branch_storage import (
    load_branch_state,
    reconcile_active_branch_state,
    save_branch_state,
)


class SubmitRuntimeText(Protocol):
    def __call__(
        self,
        text: str,
        *,
        attachments: list[dict[str, object]] | None = None,
        ignore_unavailable_attachments: bool = False,
        notify_key: str | None = "main.notify_submitted",
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class ConversationBranchBindings:
    """Narrow session ports used by conversation branch operations."""

    get_messages: Callable[[], list[Any]]
    set_messages: Callable[[list[Any]], None]
    cancel_pending_batch: Callable[[], None]
    persist_messages: Callable[[list[Any]], object]
    publish_tree: Callable[[dict[str, object]], None]
    clear_options: Callable[[], None]
    sync_history: Callable[[], None]
    replay_history: Callable[[object], None]
    submit_text: SubmitRuntimeText


class ConversationBranchManager:
    """Own branch creation, switching, naming, and persistence."""

    def __init__(
        self,
        *,
        history_path: str,
        chat_history: MutableSequence[Any],
        bindings: ConversationBranchBindings,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self.history_path = str(history_path or "")
        self.chat_history = chat_history
        self.bindings = bindings
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self.state = self._default_state()

    def load(
        self,
        loaded_messages: list[Any],
        *,
        active_history_present: bool,
    ) -> None:
        restored = load_branch_state(self.history_path) if self.history_path else None
        if restored is None:
            self.state = self._default_state()
            return
        restored_messages, restored_history = reconcile_active_branch_state(
            restored,
            loaded_messages,
            list(self.chat_history),
            active_history_present=active_history_present,
        )
        loaded_messages[:] = restored_messages
        self.chat_history[:] = restored_history
        self.bindings.set_messages(restored_messages)
        self.state = restored

    def publish_tree(self) -> None:
        self.bindings.publish_tree(self.tree_payload())

    def tree_payload(self) -> dict[str, object]:
        public_branches = []
        for branch in self._branches().values():
            public_branches.append(
                {
                    "createdAt": branch.get("createdAt"),
                    "forkedFromEntryId": branch.get("forkedFromEntryId") or "",
                    "forkedFromText": branch.get("forkedFromText") or "",
                    "id": str(branch.get("id") or ""),
                    "label": str(branch.get("label") or ""),
                    "parentId": branch.get("parentId"),
                    "updatedAt": branch.get("updatedAt"),
                }
            )
        return {
            "activeBranchId": self.active_branch_id,
            "branches": public_branches,
        }

    @property
    def active_branch_id(self) -> str:
        return str(self.state.get("active") or "main")

    def persist(self) -> None:
        if not self.history_path:
            return
        self._save_active_branch()
        self.bindings.persist_messages(self.bindings.get_messages())
        save_branch_state(self.history_path, self.state)

    def reset(self) -> None:
        self.state = self._default_state()

    def fork(self, user_index: int, branch_id: str = "") -> None:
        if user_index < 0:
            raise ValueError("分支索引无效。")
        user_position = self._user_history_position(user_index)
        if user_position < 0:
            raise ValueError("找不到可分叉的历史记录。")
        source_entry = self.chat_history[user_position]
        replay_payload = canonical_user_turn_payload(
            self._user_message(user_index),
            fallback_text=self._plain_user_text(source_entry),
        )
        user_text = str(replay_payload["text"] or "")
        user_attachments = list(replay_payload["attachments"] or [])
        if not user_text and not user_attachments:
            raise ValueError("分支输入内容为空。")

        self.bindings.cancel_pending_batch()
        self._save_active_branch()
        prefix_history = list(self.chat_history[:user_position])
        prefix_messages = self._messages_before_user(user_index)
        next_id = self._next_branch_id(branch_id)
        now = self._now_ms()
        self._branches()[next_id] = {
            "createdAt": now,
            "forkedFromEntryId": f"history-{user_position}",
            "forkedFromText": user_text,
            "history": list(prefix_history),
            "id": next_id,
            "label": f"Branch {self.state['counter']}",
            "messages": copy.deepcopy(prefix_messages),
            "parentId": self.active_branch_id,
            "updatedAt": now,
        }
        self.state["active"] = next_id
        self.chat_history[:] = prefix_history
        self.bindings.set_messages(copy.deepcopy(prefix_messages))
        self.bindings.clear_options()
        self.bindings.sync_history()
        self.publish_tree()
        self.persist()
        self.bindings.submit_text(
            user_text,
            attachments=user_attachments,
            ignore_unavailable_attachments=True,
            notify_key=None,
        )

    def switch(self, branch_id: str) -> None:
        target_id = str(branch_id or "").strip()
        branches = self._branches()
        if not target_id or target_id not in branches:
            raise ValueError("对话分支不存在。")
        self.bindings.cancel_pending_batch()
        self._save_active_branch()
        branch = branches[target_id]
        self.state["active"] = target_id
        self.chat_history[:] = list(branch.get("history") or [])
        self.bindings.set_messages(copy.deepcopy(branch.get("messages") or []))
        self.bindings.clear_options()
        self.bindings.sync_history()
        if self.chat_history:
            self.bindings.replay_history(self.chat_history[-1])
        self.publish_tree()
        self.persist()

    def rename(self, branch_id: str, label: str) -> None:
        target_id = str(branch_id or "").strip()
        next_label = str(label or "").strip()
        if not target_id or target_id not in self._branches():
            raise ValueError("对话分支不存在。")
        if not next_label:
            raise ValueError("分支名称不能为空。")
        self._branches()[target_id]["label"] = next_label[:64]
        self._branches()[target_id]["updatedAt"] = self._now_ms()
        self.publish_tree()
        self.persist()

    def _default_state(self) -> dict[str, object]:
        now = self._now_ms()
        return {
            "active": "main",
            "counter": 1,
            "branches": {
                "main": {
                    "createdAt": now,
                    "forkedFromEntryId": "",
                    "forkedFromText": "",
                    "history": list(self.chat_history),
                    "id": "main",
                    "label": "Main",
                    "messages": copy.deepcopy(self.bindings.get_messages()),
                    "parentId": None,
                    "updatedAt": now,
                }
            },
        }

    def _branches(self) -> dict[str, dict[str, object]]:
        return self.state["branches"]  # type: ignore[return-value]

    def _save_active_branch(self) -> None:
        branch = self._branches().get(self.active_branch_id)
        if branch is None:
            return
        branch["history"] = list(self.chat_history)
        branch["messages"] = copy.deepcopy(self.bindings.get_messages())
        branch["updatedAt"] = self._now_ms()

    def _user_history_position(self, user_index: int) -> int:
        current_user_index = -1
        for index, entry in enumerate(self.chat_history):
            if is_user_history_entry(str(entry)):
                current_user_index += 1
                if current_user_index == user_index:
                    return index
        return -1

    def _messages_before_user(self, user_index: int) -> list[Any]:
        new_messages = []
        current_user_index = -1
        for message in self.bindings.get_messages():
            role = message.get("role")
            if role == "user":
                current_user_index += 1
                if current_user_index >= user_index:
                    break
            new_messages.append(copy.deepcopy(message))
        return new_messages

    def _user_message(self, user_index: int) -> dict[str, object] | None:
        current_user_index = -1
        for message in self.bindings.get_messages():
            if message.get("role") != "user":
                continue
            current_user_index += 1
            if current_user_index == user_index:
                return message
        return None

    @staticmethod
    def _plain_user_text(history_entry: object) -> str:
        text = history_entry_plain_text(history_entry)
        for separator in ("：", ":"):
            if separator in text:
                speaker, body = text.split(separator, 1)
                if speaker.strip() in {"你", "User", "user"}:
                    return body.strip()
        return text.strip()

    def _next_branch_id(self, branch_id: str) -> str:
        requested_id = str(branch_id or "").strip()
        if requested_id:
            if requested_id in self._branches():
                raise ValueError("对话分支已存在。")
            suffix = requested_id[7:] if requested_id.startswith("branch-") else ""
            if suffix.isdigit():
                self.state["counter"] = max(
                    int(self.state.get("counter") or 1),
                    int(suffix),
                )
            return requested_id
        self.state["counter"] = int(self.state.get("counter") or 1) + 1
        return f"branch-{self.state['counter']}"


__all__ = ["ConversationBranchBindings", "ConversationBranchManager"]
