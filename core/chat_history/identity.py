"""Stable dialog identities shared by streaming delivery and history reconstruction."""

from collections import Counter
from collections.abc import Mapping
import hashlib
import json

CHAT_TURN_ID = "_chatTurnId"


class DialogIdentities:
    def __init__(self, turn_id: str = "") -> None:
        self.turn_id = str(turn_id or "")
        self._occurrences: Counter[str] = Counter()

    def next(self, dialog: Mapping) -> str:
        if not self.turn_id:
            return ""  # Older histories have no durable identity to match safely.
        content = json.dumps([
            str(dialog.get("character_name", dialog.get("name", "")) or ""),
            str(dialog.get("speech", dialog.get("text", "")) or ""),
            str(dialog.get("sprite", dialog.get("asset_id", "-1"))),
            str(dialog.get("translate") or ""),
        ], ensure_ascii=False, separators=(",", ":"))
        occurrence = self._occurrences[content]
        self._occurrences[content] += 1
        return hashlib.sha256(
            json.dumps([self.turn_id, content, occurrence], ensure_ascii=False).encode("utf-8")
        ).hexdigest()
