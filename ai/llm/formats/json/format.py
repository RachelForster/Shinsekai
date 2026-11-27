"""Built-in JSON dialog output format (`json_v1`)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
import re
from typing import Any

from core.messaging.dialog_output import has_valid_json_dialog_output
from core.messaging.stage_effects import (
    normalize_character_motion,
    normalize_scene_transition,
)
from core.messaging.stream_parser import LlmResponseStreamParser
from sdk.adapters.dialog_format import (
    DEFAULT_DIALOG_FORMAT_ID,
    DialogFormatPromptContext,
    DialogOutfitHint,
    DialogOutfitHintContext,
    DialogOutputFormat,
    DialogPlayerHintContext,
    DialogStreamParser,
)
from sdk.messages import LLMDialogMessage
from sdk.types import RequirementSpec

from ..registry import builtin_dialog_format
from .prompts import (
    render_json_format_reminder,
    render_json_label,
    render_json_outfit_hint,
    render_json_player_hint,
    render_json_repair_prompt,
    render_json_requirements,
    render_json_schema_hint,
    render_json_tool_protocol,
    render_json_tools_intro,
)

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


@builtin_dialog_format(order=30)
class JsonDialogFormat(DialogOutputFormat):
    """Default `{"dialog": [...]}` JSON output format."""

    format_id = DEFAULT_DIALOG_FORMAT_ID
    label = "JSON"
    order = 30
    api_response_format = {"type": "json_object"}

    def render_label(self, *, locale: str = "zh_CN") -> str:
        return render_json_label(locale=locale)

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
        speaker_requires_media: Callable[[str], bool] | None = None,
    ) -> bool:
        return has_valid_json_dialog_output(
            raw,
            media_selection_mode=media_selection_mode,
            speaker_requires_media=speaker_requires_media,
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
            if item.voice_instruct:
                payload["voice_instruct"] = item.voice_instruct
            serialized_items.append(payload)
        return json.dumps({"dialog": serialized_items}, ensure_ascii=False)

    def render_schema_hint(
        self,
        *,
        media_field: str,
        translate_required: bool,
        locale: str,
        prompt_context: DialogFormatPromptContext | None = None,
    ) -> str | None:
        return render_json_schema_hint(
            media_field=media_field,
            translate_required=translate_required,
            locale=locale,
            prompt_context=prompt_context,
        )

    def render_requirements(
        self,
        prompt_context: DialogFormatPromptContext,
    ) -> Sequence[RequirementSpec] | None:
        return render_json_requirements(prompt_context)

    def render_outfit_hint(
        self,
        context: DialogOutfitHintContext,
    ) -> DialogOutfitHint | None:
        return render_json_outfit_hint(context)

    def render_player_hint(
        self,
        context: DialogPlayerHintContext,
    ) -> str | None:
        return render_json_player_hint(context)

    def render_format_reminder(
        self,
        *,
        locale: str,
        translate: Callable[..., str] | None = None,
    ) -> str | None:
        return render_json_format_reminder(locale=locale, translate=translate)

    def render_tool_protocol(
        self,
        *,
        locale: str,
        translate: Callable[..., str] | None = None,
    ) -> str | None:
        return render_json_tool_protocol(locale=locale, translate=translate)

    def render_tools_intro(
        self,
        *,
        locale: str,
        translate: Callable[..., str] | None = None,
    ) -> str | None:
        return render_json_tools_intro(locale=locale, translate=translate)

    def render_repair_prompt(
        self,
        *,
        media_field: str,
        retry: bool,
        locale: str,
        allow_unbound_speakers: bool = False,
        bound_speakers: Sequence[str] = (),
    ) -> str | None:
        return render_json_repair_prompt(
            media_field=media_field,
            retry=retry,
            locale=locale,
            allow_unbound_speakers=allow_unbound_speakers,
            bound_speakers=bound_speakers,
        )


__all__ = ["JsonDialogFormat"]
