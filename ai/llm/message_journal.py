"""Write each accepted chat message once to the session store."""

from __future__ import annotations

from collections.abc import Callable

from core.chat_history.storage import (
    legacy_active_history_branch,
    open_session_store,
    session_id_for_history_path,
)
from sdk.adapters.session import ConversationSessionPort


class HistoryFileJournal:
    def __init__(
        self,
        history_file: str,
        intercept: Callable[[dict], bool] | None = None,
    ) -> None:
        self.history_file = str(history_file or "")
        self.intercept = intercept
        self.last_turn_seq: int | None = None

    @property
    def session_id(self) -> str:
        if not self.history_file:
            return ""
        return session_id_for_history_path(self.history_file)

    @property
    def active_branch_id(self) -> str:
        return legacy_active_history_branch(self.history_file) if self.history_file else "main"

    @property
    def session_store(self) -> ConversationSessionPort | None:
        if not self.history_file:
            return None
        return open_session_store(self.history_file)

    def append(self, message: dict) -> int | None:
        self.last_turn_seq = None
        if not self.history_file:
            return None
        store = self.session_store
        if store is not None:
            branch_id = self.active_branch_id
            if self.intercept is not None and self.intercept(message):
                marker = message.get("_storyTurnId")
                if marker:
                    for turn in reversed(store.list_turns(branch_id=branch_id)):
                        if turn.raw_message.get("_storyTurnId") == marker:
                            self.last_turn_seq = turn.seq
                            break
                return self.last_turn_seq
            turn = store.append_raw_message(message, branch_id=branch_id)
            if turn.seq > 0:
                self.last_turn_seq = turn.seq
        return self.last_turn_seq
