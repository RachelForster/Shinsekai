"""Incremental history storage backed by ConversationSessionPort + .tmp recovery journal."""

from __future__ import annotations

from collections.abc import Callable

from ai.llm.history_manager import HistoryManager
from core.chat_history.storage import (
    open_session_store,
    session_id_for_history_path,
)
from sdk.adapters.session import ConversationSessionPort


class HistoryFileJournal:
    def __init__(
        self,
        history_file: str,
        intercept: Callable[[dict], bool] | None = None,
        *,
        branch_id_provider: Callable[[], str] | None = None,
    ) -> None:
        self.history_file = str(history_file or "")
        self.intercept = intercept
        self.branch_id_provider = branch_id_provider
        self.last_turn_seq: int | None = None

    @property
    def session_id(self) -> str:
        if not self.history_file:
            return ""
        return session_id_for_history_path(self.history_file)

    @property
    def active_branch_id(self) -> str:
        if callable(self.branch_id_provider):
            resolved = str(self.branch_id_provider() or "").strip()
            if resolved:
                return resolved
        return "main"

    @property
    def session_store(self) -> ConversationSessionPort | None:
        if not self.history_file:
            return None
        return open_session_store(self.history_file)

    def append(self, message: dict) -> int | None:
        self.last_turn_seq = None
        if not self.history_file:
            return None
        if self.intercept is not None and self.intercept(message):
            return None
        store = self.session_store
        if store is not None:
            turn = store.append_raw_message(
                message,
                branch_id=self.active_branch_id,
            )
            if turn.seq > 0:
                self.last_turn_seq = turn.seq
        HistoryManager.append_message_to_tmp(self.history_file, message)
        return self.last_turn_seq
