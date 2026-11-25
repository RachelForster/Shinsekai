"""Chapter- and quote-aware elastic document chunker with bounded lookahead."""

from __future__ import annotations

from collections.abc import Sequence
import re

from core.document.models import ChapterEntry, DocumentChunk

_PARA_BREAK_RE = re.compile(r"\n{2,}")
_OPEN_CLOSE_PAIRS: dict[str, str] = {
    "“": "”",
    "「": "」",
    "『": "』",
}
_CLOSE_QUOTES = frozenset(_OPEN_CLOSE_PAIRS.values())
_STRONG_TERMINATORS = frozenset("。！？")
_ASCII_TERMINATORS = frozenset(".!?")


def _paragraph_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    segment = text[start:end]
    spans: list[tuple[int, int]] = []
    cursor = 0
    for match in _PARA_BREAK_RE.finditer(segment):
        p_start = start + cursor
        p_end = start + match.start()
        if segment[cursor : match.start()].strip():
            trimmed_start = p_start + (len(text[p_start:p_end]) - len(text[p_start:p_end].lstrip()))
            trimmed_end = p_end - (len(text[p_start:p_end]) - len(text[p_start:p_end].rstrip()))
            spans.append((trimmed_start, trimmed_end))
        cursor = match.end()
    if cursor < len(segment) and segment[cursor:].strip():
        p_start = start + cursor
        p_end = end
        trimmed_start = p_start + (len(text[p_start:p_end]) - len(text[p_start:p_end].lstrip()))
        trimmed_end = p_end - (len(text[p_start:p_end]) - len(text[p_start:p_end].rstrip()))
        spans.append((trimmed_start, trimmed_end))
    return spans


def _split_long_span(
    text: str,
    span_start: int,
    span_end: int,
    *,
    target_chars: int,
    min_chars: int,
    max_chars: int,
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    pos = span_start
    while pos < span_end:
        while pos < span_end and text[pos].isspace():
            pos += 1
        if pos >= span_end:
            break
        remaining = span_end - pos
        if remaining <= max_chars:
            spans.append((pos, span_end))
            break

        limit = min(span_end, pos + max_chars)
        quote_stack: list[str] = []
        in_straight_quote = False
        best_sentence_cut: int | None = None
        best_target_dist = limit
        fallback_ws_cut: int | None = None

        i = pos
        while i < limit:
            ch = text[i]
            if ch in _OPEN_CLOSE_PAIRS:
                quote_stack.append(_OPEN_CLOSE_PAIRS[ch])
            elif ch in _CLOSE_QUOTES:
                if quote_stack and quote_stack[-1] == ch:
                    quote_stack.pop()
            elif ch == '"':
                in_straight_quote = not in_straight_quote

            length_here = i + 1 - pos
            is_boundary_punct = (
                ch in _STRONG_TERMINATORS
                or (ch == "…" and (i + 1 >= span_end or text[i + 1] != "…"))
                or (
                    ch in _ASCII_TERMINATORS
                    and (i + 1 >= span_end or text[i + 1].isspace() or text[i + 1] in _CLOSE_QUOTES or text[i + 1] == '"')
                )
            )
            if is_boundary_punct:
                cut_at = i + 1
                peek_stack = list(quote_stack)
                peek_straight = in_straight_quote
                while cut_at < limit:
                    nxt_ch = text[cut_at]
                    if peek_stack and peek_stack[-1] == nxt_ch:
                        peek_stack.pop()
                        cut_at += 1
                    elif nxt_ch == '"' and peek_straight:
                        peek_straight = False
                        cut_at += 1
                    else:
                        break
                if not peek_stack and not peek_straight and (cut_at - pos) >= min_chars:
                    dist = abs(cut_at - pos - target_chars)
                    if best_sentence_cut is None or dist < best_target_dist:
                        best_sentence_cut = cut_at
                        best_target_dist = dist
            if ch.isspace() and length_here >= min_chars and not quote_stack and not in_straight_quote:
                fallback_ws_cut = i + 1
            i += 1

        split_at = best_sentence_cut or fallback_ws_cut or limit
        piece_end = split_at
        while piece_end > pos and text[piece_end - 1].isspace():
            piece_end -= 1
        if piece_end <= pos:
            piece_end = split_at
        spans.append((pos, piece_end))
        pos = split_at
    return spans


def chunk_document(
    text: str,
    chapters: Sequence[ChapterEntry] = (),
    *,
    target_chars: int = 800,
    min_chars: int = 500,
    max_chars: int = 1300,
    lookahead_chars: int = 120,
) -> list[DocumentChunk]:
    """Split normalized text into chapter-bounded elastic chunks with lookahead."""
    if not text or not text.strip():
        return []
    effective_target = max(100, int(target_chars))
    effective_min = max(50, min(int(min_chars), effective_target))
    effective_max = max(effective_target, int(max_chars))
    effective_lookahead = max(0, int(lookahead_chars))

    chapter_list = (
        list(chapters)
        if chapters
        else [ChapterEntry(index=0, title="Document", char_start=0, char_end=len(text))]
    )

    raw_chunks: list[tuple[int, int, int]] = []
    for chapter in chapter_list:
        para_spans = _paragraph_spans(text, chapter.char_start, chapter.char_end)
        atomic_spans: list[tuple[int, int]] = []
        for p_start, p_end in para_spans:
            if p_end - p_start > effective_max:
                atomic_spans.extend(
                    _split_long_span(
                        text,
                        p_start,
                        p_end,
                        target_chars=effective_target,
                        min_chars=effective_min,
                        max_chars=effective_max,
                    )
                )
            else:
                atomic_spans.append((p_start, p_end))

        cur_start: int | None = None
        cur_end: int | None = None
        for s_start, s_end in atomic_spans:
            if cur_start is None or cur_end is None:
                cur_start, cur_end = s_start, s_end
                continue
            cur_len = cur_end - cur_start
            combined_len = s_end - cur_start
            should_flush = (
                combined_len > effective_max
                or (cur_len >= effective_target and combined_len > effective_target)
            )
            if should_flush:
                raw_chunks.append((chapter.index, cur_start, cur_end))
                cur_start, cur_end = s_start, s_end
            else:
                cur_end = s_end
        if cur_start is not None and cur_end is not None and cur_end > cur_start:
            raw_chunks.append((chapter.index, cur_start, cur_end))

    chunks: list[DocumentChunk] = []
    for idx, (chapter_index, c_start, c_end) in enumerate(raw_chunks):
        chunk_text = text[c_start:c_end]
        if idx + 1 < len(raw_chunks) and effective_lookahead > 0:
            _, next_start, next_end = raw_chunks[idx + 1]
            lookahead = text[next_start : min(next_end, next_start + effective_lookahead)]
        else:
            lookahead = ""
        chunks.append(
            DocumentChunk(
                chunk_id=f"chunk_{idx:05d}",
                index=idx,
                chapter_index=chapter_index,
                text=chunk_text,
                lookahead=lookahead,
                char_start=c_start,
                char_end=c_end,
            )
        )
    return chunks


__all__ = ["chunk_document"]
