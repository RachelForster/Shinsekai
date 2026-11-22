"""Regression coverage for the one writable chat timeline and its journal."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai.llm.history_manager import HistoryManager
from ai.llm.message_journal import HistoryFileJournal
from application.chat.history.state import revert_chat_history
from application.chat.runtime.session import save_runtime_chat_history
from core.chat_history.models import COMPACT_SUMMARY_SOURCE
from core.chat_history.storage import (
    close_session_store,
    open_session_store,
    read_active_chat_history,
    save_branch_state,
)
from core.vector_store.sqlite_hybrid_store import SqliteHybridStore
from sdk.adapters.memory import MemoryRecord


def user(text: str) -> dict:
    return {"role": "user", "content": text}


@pytest.fixture
def active(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(HistoryManager, "_instance", None)
    active = tmp_path / "session" / "active.json"
    active.parent.mkdir()
    yield active
    close_session_store(active)


def test_shutting_down_with_a_trimmed_prompt_does_not_rewrite_the_journal(active):
    messages = [user(f"message {i}") for i in range(6)]
    active.write_text(json.dumps(messages), encoding="utf-8")
    history = HistoryManager([])
    assert history.load_chat_history(str(active)) == messages
    store = open_session_store(active)
    original_sequences = [turn.seq for turn in store.list_turns()]
    prompt = [
        {"role": "user", "source": COMPACT_SUMMARY_SOURCE, "content": "【历史摘要】较早历史已省略"},
        messages[-1],
    ]

    assert save_runtime_chat_history(str(active.parent), prompt)
    assert [turn.seq for turn in store.list_turns()] == original_sequences
    assert store.get_active_compact_checkpoint() is None
    close_session_store(active)
    assert history.load_chat_history(str(active)) == messages


def test_old_journal_does_not_reimport_rows_when_sqlite_committed_first(active):
    messages = [user("stored"), user("repeated"), user("repeated"), user("committed before crash")]
    active.write_text(json.dumps(messages[:1]), encoding="utf-8")
    history = HistoryManager([])
    history.load_chat_history(str(active))
    store = open_session_store(active)
    for message in messages[1:]:
        store.append_raw_message(message)
    temporary = Path(str(active) + ".tmp")
    for message in messages[1:3]:
        HistoryManager.append_message_to_tmp(str(active), message)
    close_session_store(active)

    assert read_active_chat_history(active) == messages
    assert history.load_chat_history(str(active)) == messages
    assert not temporary.exists()
    journal = HistoryFileJournal(str(active))
    journal.append(user("new messages are written once"))
    assert not temporary.exists()
    close_session_store(active)
    assert history.load_chat_history(str(active)) == messages + [user("new messages are written once")]


def test_reverting_a_legacy_save_keeps_its_last_active_timeline_and_archived_memories(
    active, tmp_path,
):
    save_branch_state(active.parent, {
        "active": "old-alternate",
        "branches": {
            "main": {"id": "main", "messages": [user("archived")]},
            "old-alternate": {"id": "old-alternate", "messages": [user("previous turn")]},
        },
    })
    ui_history = []
    history = HistoryManager(ui_history)
    assert history.load_chat_history(str(active)) == [user("previous turn")]
    store = open_session_store(active)
    archived = store.append_raw_message(user("archived"))
    journal = HistoryFileJournal(str(active))
    removed = journal.append(user("next turn"))
    assert journal.active_branch_id == "old-alternate"
    assert history.load_chat_history(str(active)) == [user("previous turn"), user("next turn")]

    shared = SqliteHybridStore(tmp_path / "shared.db")
    try:
        store.shared_memory_rollback = shared.rollback_after_turn
        for repo in (shared, store.save_memory_repo):
            for key, seq in [("archived", archived.seq), ("removed", removed)]:
                repo.upsert(MemoryRecord(
                    id=key, scope="char_session", owner_id="Mio", detail_text=key,
                    gist_text=key, source_session_id=store.session_id, source_turn_seq=seq,
                ))
        model = SimpleNamespace(messages=[user("previous turn"), user("next turn")])
        model.get_messages = lambda: model.messages
        model.set_messages = lambda messages: setattr(model, "messages", messages)
        window = SimpleNamespace(setDisplayWords=lambda *_: None, setOptions=lambda *_: None)

        report = revert_chat_history(1, model, ui_history, window, history_path=str(active.parent))

        assert report is not None
        assert report.rolled_back_save_memories == report.rolled_back_shared_memories == 1
        assert model.messages == [user("previous turn")]
        assert shared.get("removed") is None
        assert shared.get("archived") is not None
        assert store.save_memory_repo.get("archived") is not None
        assert [t.raw_message for t in store.list_turns()] == [user("archived")]
        close_session_store(active)
        assert history.load_chat_history(str(active)) == [user("previous turn")]
    finally:
        shared.close()
