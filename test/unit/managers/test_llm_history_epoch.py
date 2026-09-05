"""History-version fencing for an LLM turn that outlives a history switch."""

from __future__ import annotations

from pathlib import Path
from threading import Event, Thread

import pytest

from ai.llm.history_manager import HistoryManager
from ai.llm.llm_manager import LLMManager
from test.mocks import MockLLMAdapter


class _BlockingAdapter(MockLLMAdapter):
    """A synchronous response that lets a test replace history mid-request."""

    def __init__(self) -> None:
        super().__init__(responses=["late reply"])
        self.request_started = Event()
        self.release_response = Event()

    def chat(self, messages, stream=False, **kwargs):  # noqa: ANN001, ANN201
        self.request_started.set()
        if not self.release_response.wait(timeout=5):
            raise TimeoutError("test did not release the fake LLM response")
        return super().chat(messages, stream=stream, **kwargs)


def _manager(adapter: MockLLMAdapter | None = None, *, history_file: str = "") -> LLMManager:
    return LLMManager(
        adapter=adapter or MockLLMAdapter(),
        user_template="system",
        history_file=history_file,
    )


def test_stale_scope_before_chat_never_calls_adapter_or_writes_new_history():
    adapter = MockLLMAdapter()
    manager = _manager(adapter)
    old_epoch = manager.history_epoch

    manager.set_messages([
        {"role": "system", "content": "replacement"},
        {"role": "user", "content": "new conversation"},
    ])

    with manager.history_scope(old_epoch):
        assert manager._cancel_requested is True
        assert manager.chat("late input", stream=False, include_local_time=False) == ""

    assert adapter.call_history == []
    assert manager.messages == [
        {"role": "system", "content": "replacement"},
        {"role": "user", "content": "new conversation"},
    ]


@pytest.mark.parametrize("transition", ["clear", "replace"])
def test_blocked_old_request_cannot_append_or_recreate_tmp_after_history_transition(
    tmp_path: Path, transition: str
):
    adapter = _BlockingAdapter()
    history_file = str(tmp_path / "chat.json")
    manager = _manager(adapter, history_file=history_file)
    old_epoch = manager.history_epoch
    result: dict[str, object] = {}

    def run_old_turn() -> None:
        with manager.history_scope(old_epoch):
            result["value"] = manager.chat(
                "old input", stream=False, include_local_time=False
            )

    worker = Thread(target=run_old_turn)
    worker.start()
    assert adapter.request_started.wait(timeout=2)

    if transition == "clear":
        manager.clear_messages()
        expected = [{"role": "system", "content": "system"}]
    else:
        expected = [
            {"role": "system", "content": "replacement"},
            {"role": "user", "content": "new input"},
        ]
        manager.set_messages(expected)

    # The production history boundary removes the old recovery file after it
    # advances the epoch.  A late old stream must not create it again.
    HistoryManager.delete_tmp(history_file)
    adapter.release_response.set()
    worker.join(timeout=3)

    assert not worker.is_alive()
    assert result["value"] == ""
    assert manager.messages == expected
    assert not Path(history_file + ".tmp").exists()
    assert [m["role"] for m in manager.messages] == [
        message["role"] for message in expected
    ]


def test_stale_scope_direct_mutations_and_tmp_write_are_fenced(tmp_path: Path):
    history_file = str(tmp_path / "chat.json")
    manager = _manager(history_file=history_file)
    old_epoch = manager.history_epoch

    with manager.history_scope(old_epoch):
        manager.invalidate_history()
        # Existing manager code and plugins sometimes mutate ``messages``
        # directly; both forms must remain local to this stale scope.
        manager.messages.append({"role": "assistant", "content": "late append"})
        manager.messages = [{"role": "assistant", "content": "late replace"}]
        assert manager.add_message("assistant", "late persisted") is False

    assert manager.messages == [{"role": "system", "content": "system"}]
    assert not Path(history_file + ".tmp").exists()


def test_fresh_scope_persists_and_nested_scope_keeps_outer_scope_live():
    manager = _manager()
    fresh_epoch = manager.history_epoch

    with manager.history_scope(fresh_epoch):
        with manager.history_scope():
            manager.messages = manager.messages + [
                {"role": "user", "content": "nested"}
            ]
        # A live nested replacement updates the outer scope's list reference,
        # rather than making the outer turn look stale.
        assert manager.add_message("assistant", "outer") is True

    assert manager.messages == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "nested"},
        {"role": "assistant", "content": "outer"},
    ]


def test_nested_scope_cannot_revive_an_invalidated_outer_scope():
    manager = _manager()
    epoch = manager.history_epoch

    with manager.history_scope(epoch):
        manager.invalidate_history()
        with manager.history_scope():
            assert manager._cancel_requested is True
            manager.messages[0]["content"] = "late nested mutation"
            assert manager.add_message("assistant", "late nested") is False

    assert manager.messages == [{"role": "system", "content": "system"}]


def test_set_messages_detaches_caller_owned_nested_message_dicts():
    manager = _manager()
    replacement = [{"role": "system", "content": "replacement"}]

    manager.set_messages(replacement)
    replacement[0]["content"] = "caller mutation"

    assert manager.messages == [{"role": "system", "content": "replacement"}]


def test_unscoped_blocked_compaction_cannot_replace_new_history():
    manager = _manager()
    entered = Event()
    release = Event()
    result: dict[str, object] = {}

    def blocked_compaction(_messages):  # noqa: ANN001
        entered.set()
        assert release.wait(timeout=3)
        return [{"role": "system", "content": "stale compacted"}]

    manager.compact_manager.auto_compact_if_needed = blocked_compaction

    worker = Thread(
        target=lambda: result.setdefault("value", manager.add_message("user", "old"))
    )
    worker.start()
    assert entered.wait(timeout=2)

    manager.set_messages([
        {"role": "system", "content": "new history"},
        {"role": "user", "content": "fresh"},
    ])
    release.set()
    worker.join(timeout=3)

    assert not worker.is_alive()
    assert result["value"] is False
    assert manager.messages == [
        {"role": "system", "content": "new history"},
        {"role": "user", "content": "fresh"},
    ]


def test_lazy_history_state_initializes_for_a_lightweight_new_instance():
    manager = LLMManager.__new__(LLMManager)
    manager.__dict__["messages"] = [{"role": "system", "content": "legacy"}]

    assert manager.history_epoch == 0
    assert manager.messages == [{"role": "system", "content": "legacy"}]


def test_cancellation_before_first_stream_iteration_releases_chat_bookkeeping():
    adapter = MockLLMAdapter()
    manager = _manager(adapter)
    with manager.history_scope():
        stream = manager.chat("old input", stream=True, include_local_time=False)
        assert manager._chat_depth == 1
        manager.invalidate_history()
        stream.close()
        assert manager._chat_depth == 0
        assert manager._turn_state is None
    assert adapter.call_history == []
