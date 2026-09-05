from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from application.chat.manage_branches import (
    ConversationBranchBindings,
    ConversationBranchManager,
)
from core.chat_history.storage import load_branch_state


class _BranchHarness:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = copy.deepcopy(messages)
        self.cancelled = 0
        self.cleared_options = 0
        self.persisted_messages: list[list[Any]] = []
        self.published_trees: list[dict[str, object]] = []
        self.replayed_history: list[object] = []
        self.submitted: list[dict[str, object]] = []
        self.synced_history = 0

    def bindings(self) -> ConversationBranchBindings:
        def submit_text(
            text: str,
            *,
            attachments: list[dict[str, object]] | None = None,
            ignore_unavailable_attachments: bool = False,
            notify_key: str | None = "main.notify_submitted",
        ) -> bool:
            self.submitted.append(
                {
                    "attachments": list(attachments or []),
                    "ignoreUnavailable": ignore_unavailable_attachments,
                    "notifyKey": notify_key,
                    "text": text,
                }
            )
            return True

        return ConversationBranchBindings(
            get_messages=lambda: self.messages,
            set_messages=lambda messages: setattr(
                self,
                "messages",
                copy.deepcopy(messages),
            ),
            cancel_pending_batch=lambda: setattr(
                self,
                "cancelled",
                self.cancelled + 1,
            ),
            persist_messages=lambda messages: self.persisted_messages.append(
                copy.deepcopy(messages)
            ),
            publish_tree=lambda tree: self.published_trees.append(copy.deepcopy(tree)),
            clear_options=lambda: setattr(
                self,
                "cleared_options",
                self.cleared_options + 1,
            ),
            sync_history=lambda: setattr(
                self,
                "synced_history",
                self.synced_history + 1,
            ),
            replay_history=self.replayed_history.append,
            submit_text=submit_text,
        )


def _conversation() -> tuple[list[str], list[dict[str, Any]]]:
    attachment = {
        "kind": "image",
        "name": "scene.png",
        "path": "C:/media/scene.png",
    }
    return (
        ["<b>你</b>：first", "Mio：answer", "<b>你</b>：second", "Mio：last"],
        [
            {"role": "user", "content": "first", "input_text": "first"},
            {"role": "assistant", "content": "answer"},
            {
                "role": "user",
                "attachments": [attachment],
                "content": "second [image]",
                "input_text": "second",
            },
            {"role": "assistant", "content": "last"},
        ],
    )


def test_fork_preserves_main_and_replays_canonical_user_turn(tmp_path: Path) -> None:
    history, messages = _conversation()
    harness = _BranchHarness(messages)
    manager = ConversationBranchManager(
        history_path=(tmp_path / "session").as_posix(),
        chat_history=history,
        bindings=harness.bindings(),
        now_ms=lambda: 1000,
    )

    manager.fork(1)

    assert manager.active_branch_id == "branch-2"
    assert history == ["<b>你</b>：first", "Mio：answer"]
    assert harness.messages == messages[:2]
    assert harness.cancelled == 1
    assert harness.cleared_options == 1
    assert harness.synced_history == 1
    assert harness.submitted == [
        {
            "attachments": [messages[2]["attachments"][0]],
            "ignoreUnavailable": True,
            "notifyKey": None,
            "text": "second",
        }
    ]
    assert manager.state["branches"]["main"]["history"] == [
        "<b>你</b>：first",
        "Mio：answer",
        "<b>你</b>：second",
        "Mio：last",
    ]
    assert load_branch_state(tmp_path / "session")["active"] == "branch-2"


def test_switch_restores_branch_messages_history_and_latest_presentation(
    tmp_path: Path,
) -> None:
    history, messages = _conversation()
    harness = _BranchHarness(messages)
    manager = ConversationBranchManager(
        history_path=(tmp_path / "session").as_posix(),
        chat_history=history,
        bindings=harness.bindings(),
        now_ms=lambda: 2000,
    )
    manager.fork(1)
    harness.messages.append({"role": "assistant", "content": "alternate"})
    history.append("Mio：alternate")

    manager.switch("main")

    assert manager.active_branch_id == "main"
    assert history == [
        "<b>你</b>：first",
        "Mio：answer",
        "<b>你</b>：second",
        "Mio：last",
    ]
    assert harness.messages == messages
    assert harness.replayed_history == ["Mio：last"]
    assert harness.cancelled == 2
    assert harness.cleared_options == 2
    assert harness.published_trees[-1]["activeBranchId"] == "main"


def test_rename_trims_label_and_persists_tree(tmp_path: Path) -> None:
    history, messages = _conversation()
    harness = _BranchHarness(messages)
    manager = ConversationBranchManager(
        history_path=(tmp_path / "session").as_posix(),
        chat_history=history,
        bindings=harness.bindings(),
        now_ms=lambda: 3000,
    )

    manager.rename("main", "x" * 80)

    assert manager.state["branches"]["main"]["label"] == "x" * 64
    assert manager.state["branches"]["main"]["updatedAt"] == 3000
    assert load_branch_state(tmp_path / "session")["branches"]["main"]["label"] == (
        "x" * 64
    )


def test_load_uses_recovered_active_history_over_stale_branch_tree(
    tmp_path: Path,
) -> None:
    history, messages = _conversation()
    first_harness = _BranchHarness(messages)
    history_path = tmp_path / "session"
    first = ConversationBranchManager(
        history_path=history_path.as_posix(),
        chat_history=history,
        bindings=first_harness.bindings(),
        now_ms=lambda: 4000,
    )
    first.persist()

    recovered_history = ["<b>你</b>：recovered"]
    recovered_messages = [{"role": "user", "content": "recovered"}]
    second_harness = _BranchHarness(recovered_messages)
    second = ConversationBranchManager(
        history_path=history_path.as_posix(),
        chat_history=recovered_history,
        bindings=second_harness.bindings(),
        now_ms=lambda: 5000,
    )

    second.load(recovered_messages, active_history_present=True)

    assert recovered_history == ["<b>你</b>：recovered"]
    assert recovered_messages == [{"role": "user", "content": "recovered"}]
    assert second_harness.messages == recovered_messages
    assert second.state["branches"]["main"]["history"] == recovered_history


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        (lambda manager: manager.fork(-1), "分支索引无效"),
        (lambda manager: manager.fork(99), "找不到可分叉"),
        (lambda manager: manager.switch("missing"), "对话分支不存在"),
        (lambda manager: manager.rename("main", ""), "分支名称不能为空"),
    ],
)
def test_branch_operations_reject_invalid_requests(
    tmp_path: Path,
    operation,
    message: str,
) -> None:
    history, messages = _conversation()
    harness = _BranchHarness(messages)
    manager = ConversationBranchManager(
        history_path=(tmp_path / "session").as_posix(),
        chat_history=history,
        bindings=harness.bindings(),
    )

    with pytest.raises(ValueError, match=message):
        operation(manager)
