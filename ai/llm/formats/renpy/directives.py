"""Stateless single-line directive and dialogue parsers for `renpy_v1`."""

from __future__ import annotations

import re

from core.messaging.stage_effects import (
    normalize_character_motion,
    normalize_scene_transition,
)
from sdk.messages import LLMDialogMessage

from .errors import RenpyParseError, renpy_error
from .lexer import (
    find_closing_bracket,
    parse_bracket_attrs,
    parse_inline_translate,
    read_quoted_literal,
    split_top_level_pipes,
    split_trailing_with_clause,
    unquote_dsl_string,
)

AT_MOTION_RE = re.compile(r"^at\s+([a-zA-Z0-9_-]+)(?=\s|$)", re.IGNORECASE)
NUMERIC_OR_ID_RE = re.compile(r"^(?:-1|[0-9]+|[a-zA-Z0-9_.-]+)$")


def strip_leading_bracket_attrs(text: str) -> tuple[dict[str, str], str, bool]:
    trimmed = text.strip()
    if not trimmed.startswith("["):
        return {}, trimmed, True
    end = find_closing_bracket(trimmed, 0)
    if end == -1:
        return {}, trimmed, False
    return parse_bracket_attrs(trimmed[1:end]), trimmed[end + 1 :].strip(), True


def parse_menu_option_item(raw: str) -> str:
    text = raw.strip()
    if not text or text.startswith("#"):
        return ""
    if text.startswith(("- ", "* ")):
        text = text[2:].strip()
    if text.endswith(":") and not text.startswith(":") and len(text) > 1:
        text = text[:-1].strip()
    if len(text) >= 2 and text[0] in ('"', "'"):
        val, next_idx, closed = read_quoted_literal(text, 0)
        if closed and not text[next_idx:].strip():
            return val.strip()
    return unquote_dsl_string(text).strip()


def extract_speaker_prefix(line: str) -> tuple[str, str] | None:
    if not line:
        return None
    if line[0] in ('"', "'"):
        speaker, next_idx, closed = read_quoted_literal(line, 0)
        if not closed or not speaker.strip():
            return None
        rest = line[next_idx:].strip()
        return (speaker.strip(), rest) if rest else None
    cuts = [pos for pos in (line.find("["), line.find('"'), line.find("'")) if pos > 0]
    m_at = re.search(r"\s+at\s+[a-zA-Z0-9_-]+(?=\s+(?:\[|[\"']))", line, re.IGNORECASE)
    if m_at:
        cuts.append(m_at.start())
    if not cuts:
        return None
    speaker = line[: min(cuts)].strip()
    return (speaker, line[min(cuts) :].strip()) if speaker else None


def parse_media_attrs(
    rest: str, *, directive: str
) -> tuple[dict[str, str] | None, RenpyParseError | None]:
    attrs: dict[str, str] = {}
    remainder = rest.strip()
    while remainder:
        if remainder.startswith("["):
            bracket_attrs, remainder, ok = strip_leading_bracket_attrs(remainder)
            if not ok:
                return None, renpy_error("unclosed_brackets", target=directive)
            attrs.update(bracket_attrs)
            continue
        if remainder[0] in ('"', "'"):
            val, next_idx, closed = read_quoted_literal(remainder, 0)
            if not closed:
                return None, renpy_error("unclosed_quote", target=directive)
            if "vibe" not in attrs and "sprite" not in attrs:
                attrs["vibe"] = val
            remainder = remainder[next_idx:].strip()
            continue
        m_kv = re.match(r'^([a-zA-Z_][a-zA-Z0-9_-]*)=(".*?"|\'.*?\'|\S+)\s*(.*)$', remainder)
        if m_kv:
            attrs.update(parse_bracket_attrs(f"{m_kv.group(1)}={m_kv.group(2)}"))
            remainder = m_kv.group(3).strip()
            continue
        parts = remainder.split(None, 1)
        target = parts[0].strip()
        remainder = parts[1].strip() if len(parts) > 1 else ""
        if target and "sprite" not in attrs:
            attrs["sprite"] = target
    return attrs, None


def _read_speech_and_translate(
    tail: str,
    attrs: dict[str, str],
    *,
    target: str,
    eof: bool,
) -> tuple[str, str, RenpyParseError | None]:
    if not tail or tail[0] not in ('"', "'"):
        return "", "", renpy_error("missing_quoted_text", target=target)
    speech, next_idx, closed = read_quoted_literal(tail, 0)
    if not closed and not (eof and speech.strip()):
        return "", "", renpy_error("unclosed_speech", target=target)
    translate, tr_err = parse_inline_translate(tail[next_idx:], eof=eof)
    if tr_err is not None:
        return "", "", tr_err
    if not translate:
        translate = (attrs.get("translate") or "").strip()
    return speech.strip(), translate, None


def parse_scene_directive(
    rest: str,
) -> tuple[LLMDialogMessage | None, RenpyParseError | None]:
    cleaned, transition_word = split_trailing_with_clause(rest)
    attrs, err = parse_media_attrs(cleaned, directive="scene")
    if attrs is None:
        return None, err
    sprite = (attrs.get("sprite") or "").strip()
    vibe = (attrs.get("vibe") or "").strip()
    if not sprite and not vibe:
        return None, renpy_error("missing_scene_media")
    transition = normalize_scene_transition(transition_word or attrs.get("transition"))
    extra_fields: dict[str, str] = {"asset_id": sprite} if sprite else {}
    return (
        LLMDialogMessage(
            character_name="SCENE",
            vibe=vibe,
            speech="",
            effect=(attrs.get("effect") or "").strip(),
            transition=transition,
            **extra_fields,
        ),
        None,
    )


def parse_bgm_directive(
    rest: str,
) -> tuple[LLMDialogMessage | None, RenpyParseError | None]:
    attrs, err = parse_media_attrs(rest, directive="play music")
    if attrs is None:
        return None, err
    sprite = (attrs.get("sprite") or "").strip()
    vibe = (attrs.get("vibe") or "").strip()
    if not sprite and not vibe:
        return None, renpy_error("missing_bgm_media")
    extra_fields: dict[str, str] = {"asset_id": sprite} if sprite else {}
    return (
        LLMDialogMessage(
            character_name="bgm",
            vibe=vibe,
            speech="",
            effect=(attrs.get("effect") or "").strip(),
            **extra_fields,
        ),
        None,
    )


def parse_cg_directive(
    rest: str, *, eof: bool
) -> tuple[LLMDialogMessage | None, RenpyParseError | None]:
    attrs, remainder, ok = strip_leading_bracket_attrs(rest)
    if not ok:
        return None, renpy_error("unclosed_brackets", target="cg")
    speech = ""
    if remainder:
        if remainder[0] in ('"', "'"):
            val, next_idx, closed = read_quoted_literal(remainder, 0)
            if not closed and not (eof and val.strip()):
                return None, renpy_error("unclosed_quote", target="cg")
            trailing = remainder[next_idx:].strip()
            if closed and trailing:
                return None, renpy_error(
                    "unexpected_trailing", target="cg", snippet=trailing[:60]
                )
            speech = val.strip()
        else:
            speech = remainder.strip()
    sprite = (attrs.get("sprite") or "").strip() or "-1"
    vibe = (attrs.get("vibe") or "").strip()
    if not speech and sprite == "-1" and not vibe:
        return None, renpy_error("missing_cg_content")
    return (
        LLMDialogMessage(
            character_name="CG",
            sprite=sprite,
            vibe=vibe,
            speech=speech,
            effect=(attrs.get("effect") or "").strip(),
        ),
        None,
    )


def parse_stat_directive(
    body: str,
) -> tuple[LLMDialogMessage | None, RenpyParseError | None]:
    text = body.strip()
    if not text:
        return None, renpy_error("empty_stat")
    if text[0] in ('"', "'"):
        val, next_idx, closed = read_quoted_literal(text, 0)
        if not closed:
            return None, renpy_error("unclosed_quote", target="stat")
        trailing = text[next_idx:].strip()
        if trailing:
            return None, renpy_error(
                "unexpected_trailing", target="stat", snippet=trailing[:60]
            )
        text = val
    return LLMDialogMessage(character_name="STAT", sprite="-1", speech=text.strip()), None


def parse_choice_inline(
    tail: str,
) -> tuple[LLMDialogMessage | None, RenpyParseError | None]:
    options = [
        opt
        for raw_opt in split_top_level_pipes(tail)
        if (opt := parse_menu_option_item(raw_opt))
    ]
    if not options:
        return None, renpy_error("missing_choice_options")
    return LLMDialogMessage(character_name="CHOICE", sprite="-1", speech=" / ".join(options)), None


def parse_narr_directive(
    rest: str, *, eof: bool
) -> tuple[LLMDialogMessage | None, RenpyParseError | None]:
    attrs, tail, ok = strip_leading_bracket_attrs(rest)
    if not ok:
        return None, renpy_error("unclosed_brackets", target="narr")
    speech, translate, err = _read_speech_and_translate(tail, attrs, target="narr", eof=eof)
    if err is not None:
        return None, err
    return (
        LLMDialogMessage(
            character_name="NARR",
            sprite=(attrs.get("sprite") or "-1").strip() or "-1",
            speech=speech,
            translate=translate,
            effect=(attrs.get("effect") or "").strip(),
        ),
        None,
    )


def parse_bare_or_quoted_say(
    line: str,
    *,
    eof: bool,
    pending_show: dict[str, dict[str, str]],
) -> tuple[LLMDialogMessage | None, RenpyParseError | None]:
    val, next_idx, closed = read_quoted_literal(line, 0)
    if not closed:
        if eof and val.strip():
            return LLMDialogMessage(character_name="NARR", sprite="-1", speech=val.strip()), None
        return None, renpy_error("unclosed_narration")
    trailing = line[next_idx:].strip()
    if not trailing or trailing.startswith("|"):
        translate, tr_err = parse_inline_translate(trailing, eof=eof)
        if tr_err is not None:
            return None, tr_err
        return (
            LLMDialogMessage(
                character_name="NARR",
                sprite="-1",
                speech=val.strip(),
                translate=translate,
            ),
            None,
        )
    return parse_say_line(line, eof=eof, pending_show=pending_show)


def parse_say_line(
    line: str,
    *,
    eof: bool,
    pending_show: dict[str, dict[str, str]],
) -> tuple[LLMDialogMessage | None, RenpyParseError | None]:
    extracted = extract_speaker_prefix(line)
    if extracted is None:
        return None, renpy_error("unrecognized_line", snippet=line[:80])
    speaker, tail = extracted
    attrs = dict(pending_show.pop(speaker, {}))
    while tail:
        if tail.startswith("["):
            inline_attrs, tail, ok = strip_leading_bracket_attrs(tail)
            if not ok:
                return None, renpy_error("unclosed_brackets", target=speaker)
            attrs.update(inline_attrs)
            continue
        m_at = AT_MOTION_RE.match(tail)
        if m_at:
            attrs["motion"] = m_at.group(1)
            tail = tail[m_at.end() :].strip()
            continue
        break

    speech, translate, err = _read_speech_and_translate(
        tail, attrs, target=speaker, eof=eof
    )
    if err is not None:
        return None, err

    raw_sprite = attrs.get("sprite")
    has_explicit_sprite = raw_sprite is not None and str(raw_sprite).strip() != ""
    sprite = str(raw_sprite).strip() if has_explicit_sprite else "-1"
    effect = (attrs.get("effect") or "").strip()
    if sprite.upper() == "LEAVE":
        sprite = "-1"
        has_explicit_sprite = False
        effect = effect or "LEAVE"
    elif attrs.get("leave", "").lower() in ("1", "true", "leave"):
        effect = effect or "LEAVE"

    extra_fields: dict[str, str] = {"asset_id": sprite} if has_explicit_sprite else {}
    return (
        LLMDialogMessage(
            character_name=speaker,
            vibe=(attrs.get("vibe") or "").strip(),
            speech=speech,
            translate=translate,
            effect=effect,
            outfit=(attrs.get("outfit") or "").strip(),
            motion=normalize_character_motion(attrs.get("motion")),
            **extra_fields,
        ),
        None,
    )
