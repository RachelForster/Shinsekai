"""Built-in XML / HTML tag dialog output format (`xml_v1`)."""

from __future__ import annotations

from collections.abc import Sequence
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
from core.messaging.formats.xml_tags_parser import (
    NEXT_STAGE_OPEN_RE,
    XmlTagsStreamParser,
)
from sdk.adapters.dialog_format import (
    XML_DIALOG_FORMAT_ID,
    DialogOutputFormat,
    DialogStreamParser,
)
from sdk.messages import LLMDialogMessage


def _fmt_attrs(**kwargs: str | None) -> str:
    parts: list[str] = []
    for key, val in kwargs.items():
        if val is None or val == "":
            continue
        parts.append(f"{key}={_xml_quoteattr(str(val))}")
    return (" " + " ".join(parts)) if parts else ""


_COT_CLOSE_RE = re.compile(r"</(\s*cot\b)", re.IGNORECASE)


def _escape_cot_body(text: str) -> str:
    """Prevent literal ``</cot>`` inside reasoning from closing the outer tag."""
    return _COT_CLOSE_RE.sub(r"&lt;/\1", text)


class XmlTagsDialogFormat(DialogOutputFormat):
    """Streaming XML / HTML tag DSL output format."""

    format_id = XML_DIALOG_FORMAT_ID
    label = "XML / HTML Tags"
    api_response_format = {"type": "text"}

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
        if not NEXT_STAGE_OPEN_RE.search(text):
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
                    f"<scene{attrs}>{_xml_escape(speech)}</scene>" if speech else f"<scene{attrs} />"
                )
            elif norm in BGM_ALIASES:
                attrs = _fmt_attrs(
                    sprite=None if item.asset_id is None else str(item.asset_id),
                    vibe=item.vibe,
                    effect=item.effect,
                )
                lines.append(
                    f"<bgm{attrs}>{_xml_escape(speech)}</bgm>" if speech else f"<bgm{attrs} />"
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


__all__ = ["XmlTagsDialogFormat", "XmlTagsStreamParser"]
