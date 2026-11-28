"""Sentence-aware runtime narration splitter for crisp visual-novel pacing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
import re
from typing import Any

from core.messaging.dialog_tokens import NARR_ALIASES, normalize_character_name

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_OPEN_CLOSE_QUOTES: dict[str, str] = {"“": "”", "「": "」", "『": "』"}
_TRAILING_CLOSERS = frozenset("”」』’\"')）】]")
_STRONG_CJK_PUNCT = frozenset("。！？")
_CLAUSE_PUNCT = frozenset("，；、,;—")


def _contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def _strip_edge_spaces(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


def _advance_closers(text: str, pos: int) -> int:
    n = len(text)
    while pos < n and text[pos] in _TRAILING_CLOSERS:
        pos += 1
    return pos


def _split_atomic_sentences(paragraph: str) -> list[str]:
    """Split one paragraph into complete sentences without breaking short inline quotes."""
    sentences: list[str] = []
    n = len(paragraph)
    start = 0
    quote_stack: list[str] = []
    in_straight = False
    i = 0
    while i < n:
        ch = paragraph[i]
        if ch in _OPEN_CLOSE_QUOTES:
            quote_stack.append(_OPEN_CLOSE_QUOTES[ch])
        elif ch in _OPEN_CLOSE_QUOTES.values() and quote_stack and quote_stack[-1] == ch:
            quote_stack.pop()
        elif ch == '"':
            in_straight = not in_straight

        is_end = False
        cut = i + 1
        if ch in _STRONG_CJK_PUNCT:
            is_end = True
        elif ch == "…" and (i + 1 >= n or paragraph[i + 1] != "…"):
            is_end = True
        elif ch in ".!?" and (
            i + 1 >= n or paragraph[i + 1].isspace() or paragraph[i + 1] in _TRAILING_CLOSERS
        ):
            is_end = True

        if is_end:
            cut = _advance_closers(paragraph, cut)
            # Only treat quote as atomic if the quote started after the current sentence start
            # and hasn't stretched across many sentences yet.
            inside_short_quote = (bool(quote_stack) or in_straight) and (cut - start) < 90
            if not inside_short_quote:
                piece = _strip_edge_spaces(paragraph[start:cut])
                if piece:
                    sentences.append(piece)
                start = cut
                quote_stack.clear()
                in_straight = False
                i = cut
                continue
        i += 1

    tail = _strip_edge_spaces(paragraph[start:])
    if tail:
        sentences.append(tail)
    return sentences


def _split_long_sentence(sentence: str, limit: int) -> list[str]:
    """Break a single overlong sentence along clause punctuation or safe boundaries."""
    if len(sentence) <= int(limit * 1.25):
        return [sentence]
    parts: list[str] = []
    n = len(sentence)
    start = 0
    best_clause_cut: int | None = None
    best_ws_cut: int | None = None
    i = 0
    while i < n:
        ch = sentence[i]
        seg_len = i + 1 - start
        if ch in _CLAUSE_PUNCT:
            best_clause_cut = _advance_closers(sentence, i + 1)
        elif ch.isspace() and seg_len >= max(10, limit // 3):
            best_ws_cut = i + 1

        if seg_len >= limit:
            cut = best_clause_cut or best_ws_cut or (i + 1)
            piece = _strip_edge_spaces(sentence[start:cut])
            if piece:
                parts.append(piece)
            start = cut
            while start < n and sentence[start].isspace():
                start += 1
            i = start
            best_clause_cut = None
            best_ws_cut = None
            continue
        i += 1
    tail = _strip_edge_spaces(sentence[start:])
    if tail:
        parts.append(tail)
    return parts


def _pack_units(units: Sequence[str], limit: int) -> list[str]:
    """Pack short sentences together without crossing ``limit``."""
    packed: list[str] = []
    current = ""
    for unit in units:
        clean = _strip_edge_spaces(unit)
        if not clean:
            continue
        if not current:
            current = clean
            continue
        sep = "" if (_contains_cjk(current[-1:]) or current[-1:] in "。！？…，；、”」』") else " "
        candidate = f"{current}{sep}{clean}"
        if len(candidate) <= limit:
            current = candidate
        else:
            packed.append(current)
            current = clean
    if current:
        packed.append(current)
    return packed


def _split_narration_text(text: str, *, max_cjk_chars: int, max_latin_chars: int) -> list[str]:
    cleaned = "\n".join(line.strip() for line in str(text or "").splitlines() if line.strip())
    if not cleaned:
        return []
    limit = max_cjk_chars if _contains_cjk(cleaned) else max_latin_chars
    if len(cleaned) <= limit:
        return [cleaned]

    chunks: list[str] = []
    for paragraph in cleaned.split("\n"):
        atomic: list[str] = []
        for sentence in _split_atomic_sentences(paragraph):
            atomic.extend(_split_long_sentence(sentence, limit))
        chunks.extend(_pack_units(atomic, limit))
    return chunks or [cleaned]


def split_long_narration_dialogs(
    dialogs: Sequence[Mapping[str, Any]],
    *,
    max_cjk_chars: int = 65,
    max_latin_chars: int = 160,
) -> list[dict[str, Any]]:
    """Split overlong ``NARR`` dialog entries into short visual-novel narration cards."""
    result: list[dict[str, Any]] = []
    for raw_item in dialogs:
        if not isinstance(raw_item, Mapping):
            continue
        item = copy.deepcopy(dict(raw_item))
        speaker = str(item.get("character_name", item.get("name", "")) or "").strip()
        is_narr = normalize_character_name(speaker) in NARR_ALIASES
        speech = item.get("speech", item.get("text", ""))
        if not is_narr or not isinstance(speech, str) or not speech.strip():
            result.append(item)
            continue

        pieces = _split_narration_text(
            speech,
            max_cjk_chars=max(20, int(max_cjk_chars)),
            max_latin_chars=max(40, int(max_latin_chars)),
        )
        if len(pieces) <= 1:
            result.append(item)
            continue

        speech_key = "speech" if "speech" in item or "name" not in item else "text"
        effect_val = str(item.get("effect") or "").strip()
        effect_on_last = effect_val.lower().startswith("after:")
        total = len(pieces)
        for idx, piece in enumerate(pieces):
            clone = copy.deepcopy(item)
            clone[speech_key] = piece
            if idx > 0 and "translate" in clone:
                clone["translate"] = ""
            if effect_val:
                keep_effect = (idx == total - 1) if effect_on_last else (idx == 0)
                clone["effect"] = effect_val if keep_effect else ""
            result.append(clone)
    return result


__all__ = ["split_long_narration_dialogs"]
