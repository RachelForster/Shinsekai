"""Lexical helpers for quoting, attributes, and trailing clauses in `renpy_v1`."""

from __future__ import annotations

import re

from .errors import RenpyParseError, renpy_error

_ESCAPES: dict[str, str] = {
    '"': '"',
    "'": "'",
    "\\": "\\",
    "n": "\n",
    "t": "\t",
    "r": "\r",
}

_ATTR_KEY_MAP: dict[str, str] = {
    "sprite": "sprite",
    "id": "sprite",
    "bg": "sprite",
    "track": "sprite",
    "vibe": "vibe",
    "mood": "vibe",
    "motion": "motion",
    "anim": "motion",
    "effect": "effect",
    "fx": "effect",
    "outfit": "outfit",
    "sprite_group": "outfit",
    "group": "outfit",
    "tr": "translate",
    "translate": "translate",
    "transition": "transition",
    "with": "transition",
    "leave": "leave",
}

RESERVED_SPEAKER_KEYWORDS: frozenset[str] = frozenset(
    {
        "cot",
        "scene",
        "bgm",
        "cg",
        "stat",
        "menu",
        "choice",
        "hide",
        "leave",
        "narr",
        "show",
        "play",
    }
)


def format_renpy_speaker(name: str) -> str:
    """Format a character name cleanly as bare identifier or quoted literal."""
    cleaned = str(name or "").strip()
    if not cleaned:
        return quote_dsl_string(cleaned)
    first_word = cleaned.split(None, 1)[0].lower()
    if (
        first_word in RESERVED_SPEAKER_KEYWORDS
        or any(ch in cleaned for ch in ('"', "'", "[", "]", "\n", "\r"))
    ):
        return quote_dsl_string(cleaned)
    return cleaned


def quote_dsl_string(value: str) -> str:
    """Serialize a Python string into a double-quoted Ren'Py DSL literal."""
    text = str(value or "")
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def unquote_dsl_string(raw: str) -> str:
    """Unescape the interior of a Ren'Py DSL quoted literal."""
    out: list[str] = []
    idx = 0
    length = len(raw)
    while idx < length:
        ch = raw[idx]
        if ch == "\\" and idx + 1 < length:
            nxt = raw[idx + 1]
            out.append(_ESCAPES.get(nxt, nxt))
            idx += 2
            continue
        out.append(ch)
        idx += 1
    return "".join(out)


def read_quoted_literal(text: str, start: int = 0) -> tuple[str, int, bool]:
    """Read a quoted string starting at `text[start]`.

    Returns ``(decoded, next_index, closed)``.
    """
    quote = text[start]
    idx = start + 1
    length = len(text)
    buf: list[str] = []
    while idx < length:
        ch = text[idx]
        if ch == "\\" and idx + 1 < length:
            nxt = text[idx + 1]
            buf.append(_ESCAPES.get(nxt, nxt))
            idx += 2
            continue
        if ch == quote:
            return "".join(buf), idx + 1, True
        buf.append(ch)
        idx += 1
    return "".join(buf), length, False


def find_closing_bracket(text: str, start: int) -> int:
    """Return index of matching `]` for `text[start] == '['`, or -1 if unclosed."""
    in_quote: str | None = None
    idx = start + 1
    length = len(text)
    while idx < length:
        ch = text[idx]
        if in_quote:
            if ch == "\\" and idx + 1 < length:
                idx += 2
                continue
            if ch == in_quote:
                in_quote = None
            idx += 1
            continue
        if ch in ('"', "'"):
            in_quote = ch
        elif ch == "]":
            return idx
        idx += 1
    return -1


def parse_bracket_attrs(raw_inside: str) -> dict[str, str]:
    """Parse `[sprite="01", motion="nod", effect="spark"]` into canonical keys."""
    attrs: dict[str, str] = {}
    idx = 0
    length = len(raw_inside)
    while idx < length:
        while idx < length and raw_inside[idx] in " \t,":
            idx += 1
        if idx >= length:
            break
        if raw_inside[idx] in ('"', "'"):
            val, idx, _ = read_quoted_literal(raw_inside, idx)
            if "sprite" not in attrs and "vibe" not in attrs:
                attrs["sprite"] = val
            continue
        key_start = idx
        while idx < length and raw_inside[idx] not in "=, \t":
            idx += 1
        token = raw_inside[key_start:idx].strip()
        while idx < length and raw_inside[idx] in " \t":
            idx += 1
        if idx < length and raw_inside[idx] == "=":
            idx += 1
            while idx < length and raw_inside[idx] in " \t":
                idx += 1
            if idx < length and raw_inside[idx] in ('"', "'"):
                val, idx, _ = read_quoted_literal(raw_inside, idx)
            else:
                val_start = idx
                while idx < length and raw_inside[idx] not in ", \t":
                    idx += 1
                val = unquote_dsl_string(raw_inside[val_start:idx].strip())
            canon = _ATTR_KEY_MAP.get(token.lower(), token.lower())
            attrs[canon] = val
        elif token:
            lowered = token.lower()
            if lowered == "leave":
                attrs["leave"] = "true"
            elif lowered == "with":
                while idx < length and raw_inside[idx] in " \t":
                    idx += 1
                if idx < length:
                    if raw_inside[idx] in ('"', "'"):
                        val, idx, _ = read_quoted_literal(raw_inside, idx)
                    else:
                        val_start = idx
                        while idx < length and raw_inside[idx] not in ", \t":
                            idx += 1
                        val = unquote_dsl_string(raw_inside[val_start:idx].strip())
                    if val:
                        attrs["transition"] = val
            elif "sprite" not in attrs:
                attrs["sprite"] = token
    return attrs


def split_top_level_pipes(text: str) -> list[str]:
    """Split on top-level `|` / `/` delimiters outside quotes and brackets."""
    parts: list[str] = []
    in_quote: str | None = None
    bracket_depth = 0
    start = 0
    idx = 0
    length = len(text)
    delimiter = "|" if "|" in text else "/"
    while idx < length:
        ch = text[idx]
        if in_quote:
            if ch == "\\" and idx + 1 < length:
                idx += 2
                continue
            if ch == in_quote:
                in_quote = None
            idx += 1
            continue
        if ch in ('"', "'"):
            in_quote = ch
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]" and bracket_depth > 0:
            bracket_depth -= 1
        elif ch == delimiter and bracket_depth == 0:
            parts.append(text[start:idx].strip())
            start = idx + 1
        idx += 1
    parts.append(text[start:].strip())
    return parts


def parse_inline_translate(
    rest: str,
    *,
    eof: bool = False,
) -> tuple[str, RenpyParseError | None]:
    """Parse optional `| tr "..."` suffix after dialogue speech.

    Returns ``(translate_text, error)``.
    """
    trimmed = rest.strip()
    if not trimmed:
        return "", None
    match = re.match(r"^\|\s*(?:tr|translate)\b\s*(.*)$", trimmed, re.IGNORECASE)
    if not match:
        return "", renpy_error("unexpected_trailing_dialogue", snippet=trimmed[:80])
    tail = match.group(1).strip()
    if not tail:
        return "", renpy_error("empty_translate")
    if tail[0] in ('"', "'"):
        val, next_idx, closed = read_quoted_literal(tail, 0)
        if not closed:
            if eof and val.strip():
                return val.strip(), None
            return "", renpy_error("unclosed_translate")
        trailing = tail[next_idx:].strip()
        if trailing:
            return "", renpy_error("unexpected_trailing_translate", snippet=trailing[:60])
        return val.strip(), None
    return unquote_dsl_string(tail), None


def split_trailing_with_clause(text: str) -> tuple[str, str]:
    """Split a top-level trailing `with <transition>` from `scene ...`."""
    in_quote: str | None = None
    bracket_depth = 0
    last_match: tuple[int, str] | None = None
    idx = 0
    length = len(text)
    while idx < length:
        ch = text[idx]
        if in_quote:
            if ch == "\\" and idx + 1 < length:
                idx += 2
                continue
            if ch == in_quote:
                in_quote = None
            idx += 1
            continue
        if ch in ('"', "'"):
            in_quote = ch
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]" and bracket_depth > 0:
            bracket_depth -= 1
        elif bracket_depth == 0:
            sub = text[idx:]
            m = re.match(r"(?:^|\s+)with\s+([a-zA-Z0-9_-]+)\s*$", sub, re.IGNORECASE)
            if m and (idx == 0 or text[idx - 1].isspace() or sub[0].isspace()):
                last_match = (idx, m.group(1).strip())
                break
        idx += 1
    if last_match is None:
        return text.strip(), ""
    cut_idx, transition = last_match
    return text[:cut_idx].strip(), transition
