"""Built-in JSON dialog output format (`json_v1`)."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from core.messaging.dialog_output import has_valid_json_dialog_output
from core.messaging.stage_effects import (
    normalize_character_motion,
    normalize_scene_transition,
)
from core.messaging.stream_parser import LlmResponseStreamParser
from sdk.adapters.dialog_format import (
    DEFAULT_DIALOG_FORMAT_ID,
    DialogOutputFormat,
    DialogStreamParser,
)
from sdk.messages import LLMDialogMessage

_FENCE_START_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*")
_FENCE_END_RE = re.compile(r"\s*```$", re.DOTALL)


def _strip_json_fences(raw: str) -> str:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = _FENCE_START_RE.sub("", text)
        text = _FENCE_END_RE.sub("", text)
    return text.strip()


def _normalize_item(raw_item: dict[str, Any]) -> LLMDialogMessage:
    msg = LLMDialogMessage(**raw_item)
    if msg.transition:
        msg.transition = normalize_scene_transition(msg.transition)
    if msg.motion:
        msg.motion = normalize_character_motion(msg.motion)
    return msg


class JsonDialogFormat(DialogOutputFormat):
    """Default `{"dialog": [...]}` JSON output format."""

    format_id = DEFAULT_DIALOG_FORMAT_ID
    label = "JSON"
    api_response_format = {"type": "json_object"}

    def create_stream_parser(self) -> DialogStreamParser:
        return LlmResponseStreamParser()

    def parse_complete(self, raw: str) -> list[LLMDialogMessage]:
        text = _strip_json_fences(raw)
        if not text:
            return []
        parsed: Any = None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    return []
        items: list[dict[str, Any]] = []
        if isinstance(parsed, dict) and isinstance(parsed.get("dialog"), list):
            items = [item for item in parsed["dialog"] if isinstance(item, dict)]
        elif isinstance(parsed, list):
            items = [item for item in parsed if isinstance(item, dict)]
        elif isinstance(parsed, dict) and "character_name" in parsed:
            items = [parsed]
        out: list[LLMDialogMessage] = []
        for item in items:
            try:
                out.append(_normalize_item(item))
            except Exception:
                continue
        return out

    def validate(
        self,
        raw: str,
        *,
        media_selection_mode: str = "indexed",
    ) -> bool:
        return has_valid_json_dialog_output(
            raw,
            media_selection_mode=media_selection_mode,
        )

    def can_parse(self, raw: str) -> bool:
        text = _strip_json_fences(raw)
        if not text or text[0] not in "{[":
            return False
        return bool(self.parse_complete(text))

    def serialize(self, items: Sequence[LLMDialogMessage]) -> str | None:
        serialized_items: list[dict[str, Any]] = []
        for item in items:
            payload: dict[str, Any] = {
                "character_name": item.name,
                "speech": item.text or "",
                "sprite": item.asset_id if item.asset_id is not None else "-1",
            }
            if item.vibe:
                payload["vibe"] = item.vibe
            if item.translate:
                payload["translate"] = item.translate
            if item.effect:
                payload["effect"] = item.effect
            if item.outfit:
                payload["outfit"] = item.outfit
            if item.transition:
                payload["transition"] = item.transition
            if item.motion:
                payload["motion"] = item.motion
            serialized_items.append(payload)
        return json.dumps({"dialog": serialized_items}, ensure_ascii=False)
