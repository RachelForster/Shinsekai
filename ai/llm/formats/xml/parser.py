"""Incremental whitelist XML/HTML stream scanner for `xml_v1` stage tags."""

from __future__ import annotations

import html
import re
from collections.abc import Iterator

from core.messaging.stage_effects import (
    normalize_character_motion,
    normalize_scene_transition,
)
from sdk.messages import LLMDialogMessage

STAGE_TAGS: frozenset[str] = frozenset(
    {"cot", "scene", "bgm", "say", "narr", "narration", "stat", "choice", "cg", "leave"}
)
WRAPPER_TAGS: frozenset[str] = frozenset({"dialog", "script", "performance"})
ALL_KNOWN_PREFIXES: tuple[str, ...] = tuple(sorted(STAGE_TAGS | WRAPPER_TAGS | {"think"}))

NEXT_STAGE_OPEN_RE = re.compile(
    r"<(?:cot|scene|bgm|say|narr|narration|stat|choice|cg|leave)(?=[\s/>]|$)",
    re.IGNORECASE,
)

_TAG_NAME_RE = re.compile(r"^<(/?)([a-zA-Z_][a-zA-Z0-9_-]*)")
_THINK_OPEN_RE = re.compile(r"^<think(?:\s[^>]*)?>", re.IGNORECASE)
_THINK_CLOSE_RE = re.compile(r"</think\s*>", re.IGNORECASE)
_FENCE_LINE_RE = re.compile(r"^```[a-zA-Z0-9_-]*$")
_ATTR_RE = re.compile(
    r"""([a-zA-Z_][a-zA-Z0-9_:-]*)\s*(?:=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?"""
)
_TRANSLATE_RE = re.compile(
    r"<(?:tr|translate)\b[^>]*>(.*?)</(?:tr|translate)\s*>",
    re.IGNORECASE | re.DOTALL,
)
_OPTION_RE = re.compile(r"<option\b[^>]*>(.*?)</option\s*>", re.IGNORECASE | re.DOTALL)


def _find_tag_end(text: str, start: int) -> tuple[int | None, bool, str]:
    """Find unquoted closing `>` of an opening tag starting at `start`."""
    in_quote: str | None = None
    index = start + 1
    length = len(text)
    while index < length:
        ch = text[index]
        if in_quote:
            if ch == in_quote:
                in_quote = None
            index += 1
            continue
        if ch in ('"', "'"):
            in_quote = ch
            index += 1
            continue
        if ch == ">":
            before = text[start + 1 : index].rstrip()
            self_closing = before.endswith("/")
            attr_slice = before[:-1] if self_closing else before
            parts = attr_slice.strip().split(None, 1)
            attr_str = parts[1] if len(parts) > 1 else ""
            return index + 1, self_closing, attr_str
        index += 1
    return None, False, ""


def _parse_attrs(attr_str: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    if not attr_str.strip():
        return attrs
    for match in _ATTR_RE.finditer(attr_str):
        key = match.group(1).lower()
        val = match.group(2)
        if val is None:
            val = match.group(3)
        if val is None:
            val = match.group(4)
        attrs[key] = html.unescape(val) if val is not None else "true"
    return attrs


def _is_benign_prefix(prefix: str) -> bool:
    for line in prefix.splitlines():
        stripped = line.strip()
        if not stripped or _FENCE_LINE_RE.match(stripped):
            continue
        return False
    return True


def _extract_speech_and_translate(body: str, attrs: dict[str, str]) -> tuple[str, str]:
    translates = [html.unescape(m.group(1).strip()) for m in _TRANSLATE_RE.finditer(body)]
    cleaned = _TRANSLATE_RE.sub("", body)
    translate_text = " ".join(part for part in translates if part)
    if not translate_text:
        translate_text = (attrs.get("translate") or attrs.get("tr") or "").strip()
    return html.unescape(cleaned.strip()), translate_text


def _extract_choice_text(body: str) -> str:
    options = [html.unescape(m.group(1).strip()) for m in _OPTION_RE.finditer(body)]
    options = [opt for opt in options if opt]
    return " / ".join(options) if options else html.unescape(body.strip())


def _build_dialog_message(
    tag_name: str,
    attrs: dict[str, str],
    body: str,
) -> tuple[LLMDialogMessage | None, str]:
    tag = tag_name.lower()
    raw_body = body.strip()

    if tag == "cot":
        return (
            LLMDialogMessage(character_name="COT", speech=html.unescape(raw_body), sprite="-1"),
            "",
        )
    if tag == "scene":
        sprite = (attrs.get("sprite") or attrs.get("bg") or attrs.get("id") or "").strip()
        return (
            LLMDialogMessage(
                character_name="SCENE",
                sprite=sprite or "-1",
                vibe=(attrs.get("vibe") or "").strip(),
                speech=html.unescape(raw_body),
                effect=(attrs.get("effect") or "").strip(),
                transition=normalize_scene_transition(attrs.get("transition")),
            ),
            "",
        )
    if tag == "bgm":
        sprite = (
            attrs.get("sprite") or attrs.get("track") or attrs.get("bgm") or attrs.get("id") or ""
        ).strip()
        return (
            LLMDialogMessage(
                character_name="bgm",
                sprite=sprite or "-1",
                vibe=(attrs.get("vibe") or "").strip(),
                speech=html.unescape(raw_body),
                effect=(attrs.get("effect") or "").strip(),
            ),
            "",
        )
    if tag == "cg":
        return (
            LLMDialogMessage(
                character_name="CG",
                sprite=(attrs.get("sprite") or attrs.get("id") or "-1").strip() or "-1",
                vibe=(attrs.get("vibe") or "").strip(),
                speech=html.unescape(raw_body),
                effect=(attrs.get("effect") or "").strip(),
            ),
            "",
        )
    if tag in ("narr", "narration"):
        speech, translate = _extract_speech_and_translate(raw_body, attrs)
        return (
            LLMDialogMessage(
                character_name="NARR",
                sprite=(attrs.get("sprite") or "-1").strip() or "-1",
                speech=speech,
                translate=translate,
                effect=(attrs.get("effect") or "").strip(),
                voice_instruct=(
                    attrs.get("voice_instruct")
                    or attrs.get("voice_instruction")
                    or attrs.get("instruct")
                    or ""
                ).strip(),
            ),
            "",
        )
    if tag == "stat":
        return (
            LLMDialogMessage(character_name="STAT", sprite="-1", speech=html.unescape(raw_body)),
            "",
        )
    if tag == "choice":
        return (
            LLMDialogMessage(character_name="CHOICE", sprite="-1", speech=_extract_choice_text(raw_body)),
            "",
        )
    if tag == "leave":
        char_name = (
            attrs.get("char") or attrs.get("name") or attrs.get("character") or raw_body
        ).strip()
        if not char_name:
            return None, "XML tag <leave> missing 'char' attribute"
        return (
            LLMDialogMessage(
                character_name=char_name,
                sprite="-1",
                speech="",
                effect=(attrs.get("effect") or "").strip() or "LEAVE",
            ),
            "",
        )
    if tag == "say":
        char_name = (
            attrs.get("char") or attrs.get("name") or attrs.get("character") or ""
        ).strip()
        if not char_name:
            return None, "XML tag <say> missing 'char' attribute"
        speech, translate = _extract_speech_and_translate(raw_body, attrs)
        sprite = attrs.get("sprite", "-1").strip()
        effect = (attrs.get("effect") or "").strip()
        if sprite.upper() == "LEAVE":
            sprite = "-1"
            effect = effect or "LEAVE"
        elif attrs.get("leave", "").lower() in ("1", "true", "leave"):
            effect = effect or "LEAVE"
        return (
            LLMDialogMessage(
                character_name=char_name,
                sprite=sprite if sprite != "" else "-1",
                vibe=(attrs.get("vibe") or "").strip(),
                speech=speech,
                translate=translate,
                effect=effect,
                outfit=(attrs.get("outfit") or attrs.get("sprite_group") or "").strip(),
                motion=normalize_character_motion(attrs.get("motion")),
                voice_instruct=(
                    attrs.get("voice_instruct")
                    or attrs.get("voice_instruction")
                    or attrs.get("instruct")
                    or ""
                ).strip(),
            ),
            "",
        )
    return None, f"Unsupported stage tag <{tag_name}>"


def _can_flush_truncated(tag: str, attrs: dict[str, str], body: str) -> bool:
    if tag == "say":
        char_name = (attrs.get("char") or attrs.get("name") or attrs.get("character") or "").strip()
        speech, _ = _extract_speech_and_translate(body, attrs)
        return bool(char_name and speech)
    if tag in ("narr", "narration"):
        speech, _ = _extract_speech_and_translate(body, attrs)
        return bool(speech)
    if tag in ("scene", "bgm", "cg"):
        return bool((attrs.get("sprite") or attrs.get("bg") or attrs.get("track") or attrs.get("vibe") or "").strip())
    if tag == "leave":
        return bool((attrs.get("char") or attrs.get("name") or body.strip()))
    if tag in ("cot", "stat", "choice"):
        return bool(body.strip())
    return False


class XmlTagsStreamParser:
    """Stateful incremental scanner for XML/HTML stage tags."""

    def __init__(self) -> None:
        self._buffer = ""
        self.accumulated_text = ""
        self.parse_failures = 0
        self.last_error: str = ""

    @property
    def has_errors(self) -> bool:
        return self.parse_failures > 0

    @property
    def buffer(self) -> str:
        return self._buffer

    @property
    def unparsed_remainder(self) -> str:
        return self._buffer[:200].strip()

    def feed(self, chunk: str) -> Iterator[LLMDialogMessage]:
        if chunk:
            self._buffer += chunk
            self.accumulated_text += chunk
        yield from self._drain(eof=False)

    def flush(self) -> list[LLMDialogMessage]:
        return self._drain(eof=True)

    def _drain(self, *, eof: bool) -> list[LLMDialogMessage]:
        emitted: list[LLMDialogMessage] = []
        pos = 0
        while pos < len(self._buffer):
            lt = self._buffer.find("<", pos)
            if lt == -1:
                if eof and _is_benign_prefix(self._buffer):
                    self._buffer = ""
                break

            sub = self._buffer[lt:]
            if sub.startswith("<!--"):
                end_comment = self._buffer.find("-->", lt + 4)
                if end_comment == -1:
                    break
                if _is_benign_prefix(self._buffer[:lt]):
                    self._consume(end_comment + 3)
                    pos = 0
                else:
                    pos = end_comment + 3
                continue

            if not eof and sub in ("<", "</"):
                break

            m_name = _TAG_NAME_RE.match(sub)
            if not m_name:
                pos = lt + 1
                continue

            is_closing = bool(m_name.group(1))
            raw_tag = m_name.group(2).lower()
            if (
                not eof
                and len(sub) == len(m_name.group(0))
                and any(known.startswith(raw_tag) for known in ALL_KNOWN_PREFIXES)
            ):
                break

            if not is_closing and raw_tag == "think":
                if not _THINK_OPEN_RE.match(sub):
                    if not eof and ">" not in sub:
                        break
                    pos = lt + 1
                    continue
                close_think = _THINK_CLOSE_RE.search(self._buffer, lt + len(m_name.group(0)))
                if close_think is None:
                    break
                if _is_benign_prefix(self._buffer[:lt]):
                    self._consume(close_think.end())
                    pos = 0
                else:
                    pos = close_think.end()
                continue

            if raw_tag in WRAPPER_TAGS:
                tag_end, _, _ = _find_tag_end(self._buffer, lt)
                if tag_end is None:
                    if not eof:
                        break
                    pos = lt + 1
                    continue
                if _is_benign_prefix(self._buffer[:lt]):
                    self._consume(tag_end)
                    pos = 0
                else:
                    pos = tag_end
                continue

            if is_closing or raw_tag not in STAGE_TAGS:
                pos = lt + 1
                continue

            tag_end, self_closing, attr_str = _find_tag_end(self._buffer, lt)
            if tag_end is None:
                if not eof:
                    break
                pos = lt + 1
                continue

            attrs = _parse_attrs(attr_str)
            if self_closing:
                msg, err = _build_dialog_message(raw_tag, attrs, "")
                self._consume(tag_end)
                pos = 0
                if err:
                    self.parse_failures += 1
                    self.last_error = err
                elif msg is not None:
                    emitted.append(msg)
                continue

            close_re = re.compile(rf"</{re.escape(raw_tag)}\s*>", re.IGNORECASE)
            close_match = close_re.search(self._buffer, tag_end)
            if close_match is None:
                if not eof:
                    break
                tail = self._buffer[tag_end:]
                next_stage = NEXT_STAGE_OPEN_RE.search(tail) if raw_tag == "cot" else None
                if next_stage is not None:
                    body = tail[: next_stage.start()]
                    consume_end = tag_end + next_stage.start()
                elif _can_flush_truncated(raw_tag, attrs, tail):
                    body = tail
                    consume_end = len(self._buffer)
                else:
                    break
            else:
                body = self._buffer[tag_end : close_match.start()]
                consume_end = close_match.end()

            msg, err = _build_dialog_message(raw_tag, attrs, body)
            self._consume(consume_end)
            pos = 0
            if err:
                self.parse_failures += 1
                self.last_error = err
            elif msg is not None:
                emitted.append(msg)

        return emitted

    def _consume(self, end_index: int) -> None:
        self._buffer = self._buffer[end_index:].lstrip()
