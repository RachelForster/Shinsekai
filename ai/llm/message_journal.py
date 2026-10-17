"""Incremental history storage with an optional application-owned interceptor."""

from collections.abc import Callable

from ai.llm.history_manager import HistoryManager


class HistoryFileJournal:
    def __init__(self, history_file: str, intercept: Callable[[dict], bool] | None = None) -> None:
        self.history_file = history_file
        self.intercept = intercept

    def append(self, message: dict) -> None:
        if not self.history_file:
            return
        if self.intercept is not None and self.intercept(message):
            return
        HistoryManager.append_message_to_tmp(self.history_file, message)
