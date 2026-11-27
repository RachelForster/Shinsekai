"""Built-in XML / HTML tag dialog output format (`xml_v1`)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import re
from xml.sax.saxutils import escape as _xml_escape, quoteattr as _xml_quoteattr

from core.messaging.dialog_tokens import (
    BGM_ALIASES,
    CG_ALIASES,
    CHOICE_ALIASES,
    COT_ALIASES,
    NARR_ALIASES,
    SCENE_ALIASES,
    STAT_ALIASES,
    normalize_character_name,
)
from sdk.adapters.dialog_format import (
    XML_DIALOG_FORMAT_ID,
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
from .parser import NEXT_STAGE_OPEN_RE, XmlTagsStreamParser
from .prompts import (
    render_xml_format_reminder,
    render_xml_label,
    render_xml_outfit_hint,
    render_xml_player_hint,
    render_xml_repair_prompt,
    render_xml_requirements,
    render_xml_schema_hint,
    render_xml_tool_protocol,
    render_xml_tools_intro,
)

_COT_CLOSE_RE = re.compile(r"</(\s*cot\b)", re.IGNORECASE)
_FENCE_LINE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*$")


def _fmt_attrs(**kwargs: str | None) -> str:
    parts: list[str] = []
    for key, val in kwargs.items():
        if val is None or val == "":
            continue
        parts.append(f"{key}={_xml_quoteattr(str(val))}")
    return (" " + " ".join(parts)) if parts else ""


def _escape_cot_body(text: str) -> str:
    """Prevent literal ``</cot>`` inside reasoning from closing the outer tag."""
    return _COT_CLOSE_RE.sub(r"&lt;/\1", text)


def _strip_optional_fences(raw: str) -> str:
    lines = str(raw or "").strip().splitlines()
    if lines and _FENCE_LINE_RE.match(lines[0].strip()):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


@builtin_dialog_format(order=10)
class XmlTagsDialogFormat(DialogOutputFormat):
    """Streaming XML / HTML tag DSL output format."""

    format_id = XML_DIALOG_FORMAT_ID
    label = "XML / HTML Tags"
    order = 10
    api_response_format = {"type": "text"}

    def render_label(self, *, locale: str = "zh_CN") -> str:
        return render_xml_label(locale=locale)

    def create_stream_parser(self) -> DialogStreamParser:
        return XmlTagsStreamParser()

    def parse_complete(self, raw: str) -> list[LLMDialogMessage]:
        parser = XmlTagsStreamParser()
        messages = list(parser.feed(str(raw or "")))
        messages.extend(parser.flush())
        return messages

    def validate(
        self,
        raw: str,
        *,
        media_selection_mode: str = "indexed",
    ) -> bool:
        if not isinstance(raw, str) or not raw.strip():
            return False
        parser = XmlTagsStreamParser()
        messages = list(parser.feed(raw))
        messages.extend(parser.flush())
        if parser.has_errors or not messages:
            return False
        if NEXT_STAGE_OPEN_RE.search(parser.unparsed_remainder):
            return False
        semantic = str(media_selection_mode or "").strip().lower() == "semantic"
        for msg in messages:
            if not normalize_character_name(msg.name):
                return False
            norm = normalize_character_name(msg.name)
            if semantic and norm in (SCENE_ALIASES | BGM_ALIASES):
                if not str(msg.vibe or "").strip() and str(msg.asset_id or "") == "-1":
                    return False
        return True

    def can_parse(self, raw: str) -> bool:
        text = str(raw or "")
        unwrapped = _strip_optional_fences(text)
        if not unwrapped or unwrapped[0] in "{[":
            return False
        if not NEXT_STAGE_OPEN_RE.search(unwrapped):
            return False
        return bool(self.parse_complete(text))

    def serialize(self, items: Sequence[LLMDialogMessage]) -> str | None:
        lines: list[str] = []
        for item in items:
            norm = normalize_character_name(item.name)
            speech = item.text or ""
            tr_part = f" <tr>{_xml_escape(item.translate)}</tr>" if item.translate else ""
            if norm in COT_ALIASES:
                lines.append(f"<cot>{_escape_cot_body(speech)}</cot>")
            elif norm in SCENE_ALIASES:
                attrs = _fmt_attrs(
                    sprite=None if item.asset_id is None else str(item.asset_id),
                    vibe=item.vibe,
                    transition=item.transition,
                    effect=item.effect,
                )
                lines.append(
                    f"<scene{attrs}>{_xml_escape(speech)}</scene>"
                    if speech
                    else f"<scene{attrs} />"
                )
            elif norm in BGM_ALIASES:
                attrs = _fmt_attrs(
                    sprite=None if item.asset_id is None else str(item.asset_id),
                    vibe=item.vibe,
                    effect=item.effect,
                )
                lines.append(
                    f"<bgm{attrs}>{_xml_escape(speech)}</bgm>"
                    if speech
                    else f"<bgm{attrs} />"
                )
            elif norm in CG_ALIASES:
                attrs = _fmt_attrs(
                    sprite=None if item.asset_id is None else str(item.asset_id),
                    vibe=item.vibe,
                    effect=item.effect,
                )
                lines.append(f"<cg{attrs}>{_xml_escape(speech)}</cg>")
            elif norm in NARR_ALIASES:
                attrs = _fmt_attrs(effect=item.effect, voice_instruct=item.voice_instruct)
                lines.append(f"<narr{attrs}>{_xml_escape(speech)}{tr_part}</narr>")
            elif norm in STAT_ALIASES:
                lines.append(f"<stat>{_xml_escape(speech)}</stat>")
            elif norm in CHOICE_ALIASES:
                lines.append(f"<choice>{_xml_escape(speech)}</choice>")
            else:
                asset_str = "" if item.asset_id is None else str(item.asset_id)
                eff_upper = str(item.effect or "").strip().upper()
                if (eff_upper == "LEAVE" or asset_str.strip().upper() == "LEAVE") and not speech:
                    lines.append(f"<leave{_fmt_attrs(char=item.name)} />")
                else:
                    attrs = _fmt_attrs(
                        char=item.name,
                        sprite=asset_str or "-1",
                        vibe=item.vibe,
                        outfit=item.outfit,
                        motion=item.motion,
                        effect=item.effect,
                        voice_instruct=item.voice_instruct,
                    )
                    lines.append(f"<say{attrs}>{_xml_escape(speech)}{tr_part}</say>")
        return "\n".join(lines)

    def render_schema_hint(
        self,
        *,
        media_field: str,
        translate_required: bool,
        locale: str,
        prompt_context: DialogFormatPromptContext | None = None,
    ) -> str | None:
        return render_xml_schema_hint(
            media_field=media_field,
            translate_required=translate_required,
            locale=locale,
            prompt_context=prompt_context,
        )

    def render_requirements(
        self,
        prompt_context: DialogFormatPromptContext,
    ) -> Sequence[RequirementSpec] | None:
        return render_xml_requirements(prompt_context)

    def render_outfit_hint(
        self,
        context: DialogOutfitHintContext,
    ) -> DialogOutfitHint | None:
        return render_xml_outfit_hint(context)

    def render_player_hint(
        self,
        context: DialogPlayerHintContext,
    ) -> str | None:
        return render_xml_player_hint(context)

    def render_format_reminder(
        self,
        *,
        locale: str,
        translate: Callable[..., str] | None = None,
    ) -> str | None:
        return render_xml_format_reminder(locale=locale, translate=translate)

    def render_tool_protocol(
        self,
        *,
        locale: str,
        translate: Callable[..., str] | None = None,
    ) -> str | None:
        return render_xml_tool_protocol(locale=locale, translate=translate)

    def render_tools_intro(
        self,
        *,
        locale: str,
        translate: Callable[..., str] | None = None,
    ) -> str | None:
        return render_xml_tools_intro(locale=locale, translate=translate)

    def render_repair_prompt(
        self,
        *,
        media_field: str,
        retry: bool,
        locale: str,
        allow_unbound_speakers: bool = False,
        bound_speakers: Sequence[str] = (),
    ) -> str | None:
        return render_xml_repair_prompt(
            media_field=media_field,
            retry=retry,
            locale=locale,
            allow_unbound_speakers=allow_unbound_speakers,
            bound_speakers=bound_speakers,
        )


__all__ = ["XmlTagsDialogFormat", "XmlTagsStreamParser"]
