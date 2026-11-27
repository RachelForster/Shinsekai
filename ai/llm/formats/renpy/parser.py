"""Incremental line-oriented streaming parser for `renpy_v1` stage scripts."""

from __future__ import annotations

import re
from collections.abc import Iterator

from sdk.messages import LLMDialogMessage

from .directives import (
    AT_MOTION_RE,
    NUMERIC_OR_ID_RE,
    parse_bare_or_quoted_say,
    parse_bgm_directive,
    parse_cg_directive,
    parse_choice_inline,
    parse_menu_option_item,
    parse_narr_directive,
    parse_say_line,
    parse_scene_directive,
    parse_stat_directive,
    strip_leading_bracket_attrs,
)
from .errors import RenpyParseError, format_renpy_parse_error, renpy_error
from .lexer import read_quoted_literal

_FENCE_LINE_RE = re.compile(r"^```[a-zA-Z0-9_-]*$")
_THINK_OPEN_RE = re.compile(r"<think(?:\s[^>]*)?>", re.IGNORECASE)
_THINK_CLOSE_RE = re.compile(r"</think\s*>", re.IGNORECASE)

RENPY_DIRECTIVE_START_RE = re.compile(
    r'^(?:cot\s*:|scene(?:\s|\[|$)|(?:play\s+music|bgm)(?:\s|\[|$)|'
    r'cg(?:\s*:|\s|\[|$)|stat(?:\s*:|\s|$)|(?:menu|choice)(?:\s*:|\s)|'
    r'(?:hide|leave)(?:\s|$)|narr(?:\s|\[|$)|show(?=\s|$))',
    re.IGNORECASE | re.MULTILINE,
)


class RenpyDslStreamParser:
    """Stateful incremental scanner for Ren'Py-like DSL stage lines."""

    def __init__(self, *, locale: str | None = None) -> None:
        self._locale = locale
        self._buffer = ""
        self.accumulated_text = ""
        self.parse_failures = 0
        self.last_error: str = ""
        self.last_error_code: str = ""
        self.last_error_params: dict[str, str] = {}
        self._last_error_obj: RenpyParseError | None = None
        self._in_think = False
        self._in_menu = False
        self._menu_options: list[str] = []
        self._pending_show: dict[str, dict[str, str]] = {}

    @property
    def has_errors(self) -> bool:
        return self.parse_failures > 0

    @property
    def buffer(self) -> str:
        return self._buffer

    @property
    def unparsed_remainder(self) -> str:
        return self._buffer[:200].strip()

    def _record_error(self, error: RenpyParseError) -> None:
        self.parse_failures += 1
        self._last_error_obj = error
        self.last_error_code = error.code
        self.last_error_params = error.params_dict()
        self.last_error = format_renpy_parse_error(error, locale=self._locale)[:240]

    def format_last_error(self, *, locale: str | None = None) -> str:
        """Render the latest parse error in an explicit locale without mutating parser state."""
        if self._last_error_obj is None:
            return self.last_error
        target_locale = locale if locale is not None else self._locale
        return format_renpy_parse_error(self._last_error_obj, locale=target_locale)[:240]

    def _emit_or_fail(
        self, result: tuple[LLMDialogMessage | None, RenpyParseError | None]
    ) -> LLMDialogMessage | None:
        msg, err = result
        if err is not None:
            self._record_error(err)
            return None
        return msg

    def feed(self, chunk: str) -> Iterator[LLMDialogMessage]:
        if chunk:
            self._buffer += chunk
            self.accumulated_text += chunk
        yield from self._drain(eof=False)

    def flush(self) -> list[LLMDialogMessage]:
        return self._drain(eof=True)

    def _flush_menu_block(self) -> LLMDialogMessage | None:
        self._in_menu = False
        options = [opt for opt in self._menu_options if opt]
        self._menu_options = []
        if not options:
            self._record_error(renpy_error("missing_choice_options"))
            return None
        return LLMDialogMessage(
            character_name="CHOICE",
            sprite="-1",
            speech=" / ".join(options),
        )

    def _consume_think(self, *, eof: bool) -> bool:
        """Consume closed `<think>...</think>` blocks. Return False if waiting for close."""
        while True:
            if self._in_think:
                close_match = _THINK_CLOSE_RE.search(self._buffer)
                if close_match is None:
                    return False
                self._buffer = self._buffer[close_match.end() :]
                self._in_think = False
                continue

            stripped = self._buffer.lstrip()
            if not stripped:
                if eof:
                    self._buffer = ""
                return True
            if not eof and "<think".startswith(stripped.lower()):
                return False
            m_open = _THINK_OPEN_RE.match(stripped)
            if not m_open:
                return True
            lead = len(self._buffer) - len(stripped)
            self._buffer = self._buffer[lead + m_open.end() :]
            self._in_think = True

    def _drain(self, *, eof: bool) -> list[LLMDialogMessage]:
        emitted: list[LLMDialogMessage] = []
        while self._buffer or (eof and self._in_menu):
            if self._buffer and not self._consume_think(eof=eof):
                break

            nl = self._buffer.find("\n")
            if nl != -1:
                raw_line = self._buffer[:nl]
                self._buffer = self._buffer[nl + 1 :]
                emitted.extend(self._process_line(raw_line, eof=False))
                continue

            if not eof:
                break

            tail = self._buffer
            self._buffer = ""
            if tail.strip():
                emitted.extend(self._process_line(tail, eof=True))
            if self._in_menu:
                menu_msg = self._flush_menu_block()
                if menu_msg is not None:
                    emitted.append(menu_msg)
            break

        if eof and self._in_menu and not self._buffer:
            menu_msg = self._flush_menu_block()
            if menu_msg is not None:
                emitted.append(menu_msg)
        return emitted

    def _process_line(self, raw_line: str, *, eof: bool) -> list[LLMDialogMessage]:
        emitted: list[LLMDialogMessage] = []
        line = raw_line.strip()
        if self._in_menu:
            if not line:
                return emitted
            indented = raw_line[: len(raw_line) - len(raw_line.lstrip(" \t"))] != ""
            if indented or line.startswith(("- ", "* ")):
                opt = parse_menu_option_item(line)
                if opt:
                    self._menu_options.append(opt)
                return emitted
            menu_msg = self._flush_menu_block()
            if menu_msg is not None:
                emitted.append(menu_msg)

        if not line or line.startswith("#") or _FENCE_LINE_RE.match(line):
            return emitted

        msg = self._parse_directive_or_dialogue(line, eof=eof)
        if msg is not None:
            emitted.append(msg)
        return emitted

    def _parse_directive_or_dialogue(
        self,
        line: str,
        *,
        eof: bool,
    ) -> LLMDialogMessage | None:
        m_cot = re.match(r"^cot\s*(?::\s*(.*)|\s+(.+))$", line, re.IGNORECASE)
        if m_cot:
            body = (m_cot.group(1) if m_cot.group(1) is not None else m_cot.group(2) or "").strip()
            if len(body) >= 2 and body[0] in ('"', "'"):
                val, next_idx, closed = read_quoted_literal(body, 0)
                if closed and not body[next_idx:].strip():
                    body = val
            if not body:
                self._record_error(renpy_error("empty_cot"))
                return None
            return LLMDialogMessage(character_name="COT", sprite="-1", speech=body)

        if m_scene := re.match(r"^scene(?=\s|\[|$)(.*)$", line, re.IGNORECASE):
            return self._emit_or_fail(parse_scene_directive(m_scene.group(1)))

        if m_bgm := re.match(r"^(?:play\s+music|bgm)(?=\s|\[|$)(.*)$", line, re.IGNORECASE):
            return self._emit_or_fail(parse_bgm_directive(m_bgm.group(1)))

        if m_cg := re.match(r"^cg(?:\s*:\s*(.*)|(?=\s|\[|$)(.*))$", line, re.IGNORECASE):
            tail = (m_cg.group(1) if m_cg.group(1) is not None else m_cg.group(2) or "").strip()
            return self._emit_or_fail(parse_cg_directive(tail, eof=eof))

        if re.match(r"^stat(?:\s*:|\s|$)", line, re.IGNORECASE):
            body = line[4:].lstrip()
            if body.startswith(":"):
                body = body[1:].strip()
            return self._emit_or_fail(parse_stat_directive(body))

        if re.match(
            r"^(?:show|hide|leave|menu|play)\s*(?:\[[^\]]*\]\s*)+[\"']",
            line,
            re.IGNORECASE,
        ):
            return self._emit_or_fail(
                parse_say_line(line, eof=eof, pending_show=self._pending_show)
            )

        if m_menu := re.match(r"^(?:menu|choice)\s*(?::\s*(.*)|\s+(.+))$", line, re.IGNORECASE):
            tail = (m_menu.group(1) if m_menu.group(1) is not None else m_menu.group(2) or "").strip()
            if not tail and line.lower().startswith("menu"):
                if eof:
                    self._record_error(renpy_error("missing_choice_options"))
                    return None
                self._in_menu = True
                self._menu_options = []
                return None
            return self._emit_or_fail(parse_choice_inline(tail))

        if m_hide := re.match(r"^(?:hide|leave)(?=\s|$)(.*)$", line, re.IGNORECASE):
            return self._parse_hide(m_hide.group(1))

        if m_show := re.match(r"^show(?=\s|$)(.*)$", line, re.IGNORECASE):
            self._parse_show(m_show.group(1))
            return None

        if m_narr := re.match(r"^narr(?=\s|\[|$)(.*)$", line, re.IGNORECASE):
            return self._emit_or_fail(parse_narr_directive(m_narr.group(1), eof=eof))

        if line[0] in ('"', "'"):
            return self._emit_or_fail(
                parse_bare_or_quoted_say(line, eof=eof, pending_show=self._pending_show)
            )

        return self._emit_or_fail(
            parse_say_line(line, eof=eof, pending_show=self._pending_show)
        )

    def _parse_hide(self, rest: str) -> LLMDialogMessage | None:
        text = rest.strip()
        if not text:
            self._record_error(renpy_error("missing_character_name", directive="hide"))
            return None
        if text[0] in ('"', "'"):
            char_name, _, closed = read_quoted_literal(text, 0)
            if not closed or not char_name.strip():
                self._record_error(renpy_error("invalid_character_name", directive="hide"))
                return None
        else:
            char_name = text.strip()
        char_name = char_name.strip()
        self._pending_show.pop(char_name, None)
        return LLMDialogMessage(
            character_name=char_name,
            sprite="-1",
            speech="",
            effect="LEAVE",
        )

    def _parse_show(self, rest: str) -> None:
        text = rest.strip()
        if not text:
            self._record_error(renpy_error("missing_character_name", directive="show"))
            return
        if text[0] in ('"', "'"):
            char_name, next_idx, closed = read_quoted_literal(text, 0)
            if not closed or not char_name.strip():
                self._record_error(renpy_error("invalid_character_name", directive="show"))
                return
            tail = text[next_idx:].strip()
        else:
            parts = re.split(r"(?=\s|\[)", text, maxsplit=1)
            char_name = parts[0].strip()
            tail = parts[1].strip() if len(parts) > 1 else ""
        attrs, tail, ok = strip_leading_bracket_attrs(tail)
        if not ok:
            self._record_error(renpy_error("unclosed_brackets", target="show"))
            return
        while tail:
            if tail.startswith("["):
                more_attrs, tail, ok2 = strip_leading_bracket_attrs(tail)
                if not ok2:
                    self._record_error(renpy_error("unclosed_brackets", target="show"))
                    return
                attrs.update(more_attrs)
                continue
            m_at = AT_MOTION_RE.match(tail)
            if m_at:
                attrs.setdefault("motion", m_at.group(1))
                tail = tail[m_at.end() :].strip()
                continue
            tok, _, tail = tail.partition(" ")
            tail = tail.strip()
            if tok and NUMERIC_OR_ID_RE.match(tok) and "sprite" not in attrs:
                attrs["sprite"] = tok
        if char_name:
            self._pending_show[char_name.strip()] = attrs
