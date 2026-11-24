"""Document ingestion for TXT/Markdown and text-layer PDFs."""

from __future__ import annotations

import codecs
from collections.abc import Sequence
import hashlib
import io
from pathlib import Path
import re
from typing import Any

from core.document.models import ChapterEntry, IngestedDocument
from sdk.exception.types import AppError

_CHAPTER_HEADING_RE = re.compile(
    r"^(?:"
    r"第[零一二三四五六七八九十百千万兩两0-9]+\s*[章节回卷部篇](?:[\s：:.\-—].*)?"
    r"|Chapter\s+[0-9IVXLCDM]+(?:[\s：:.\-—].*)?"
    r"|Prologue(?:[\s：:.\-—].*)?"
    r"|Epilogue(?:[\s：:.\-—].*)?"
    r"|序章(?:[\s：:.\-—].*)?"
    r"|楔子(?:[\s：:.\-—].*)?"
    r"|序言(?:[\s：:.\-—].*)?"
    r"|终章(?:[\s：:.\-—].*)?"
    r"|尾声(?:[\s：:.\-—].*)?"
    r")$",
    re.IGNORECASE,
)
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*•·]|\d+[.)、])\s+")
_TERMINAL_PUNCT = frozenset("。！？!?…….”」』\"'：:")
_DIALOGUE_OPENERS = frozenset("“「『\"")
_SUPPORTED_TEXT_SUFFIXES = frozenset({".txt", ".md", ".markdown"})


def compute_doc_id(raw_bytes: bytes) -> str:
    """Compute canonical SHA-256 hex digest identifying a raw document payload."""
    return hashlib.sha256(raw_bytes).hexdigest()


def decode_text_bytes(raw_bytes: bytes) -> str:
    """Decode raw text bytes across UTF-16 BOM, UTF-8, and GB18030."""
    if raw_bytes.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw_bytes.decode("utf-16")
    if raw_bytes.startswith(codecs.BOM_UTF8):
        return raw_bytes.decode("utf-8-sig")
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw_bytes.decode(encoding, errors="strict")
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace")


def normalize_plain_text(text: str) -> str:
    """Normalize newlines and strip trailing whitespace without altering paragraphs."""
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in unified.split("\n")]
    joined = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", joined)


def _is_cjk_char(ch: str) -> bool:
    if not ch:
        return False
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x3040 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
    )


def _join_wrapped_lines(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    if left.endswith("-") and len(left) >= 2 and left[-2].isalpha() and right[0].isalpha():
        return f"{left[:-1]}{right}"
    if _is_cjk_char(left[-1]) or _is_cjk_char(right[0]):
        return f"{left}{right}"
    return f"{left} {right}"


def heal_pdf_line_breaks(text: str) -> str:
    """Join spurious PDF hard wraps inside paragraphs while keeping headings/paragraphs."""
    unified = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not unified:
        return ""
    blocks = re.split(r"\n{2,}", unified)
    healed_blocks: list[str] = []
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        merged: list[str] = [lines[0]]
        for nxt in lines[1:]:
            prev = merged[-1]
            preserve_break = (
                bool(_CHAPTER_HEADING_RE.match(prev))
                or bool(_CHAPTER_HEADING_RE.match(nxt))
                or bool(_LIST_ITEM_RE.match(nxt))
                or prev[-1] in _TERMINAL_PUNCT
                or nxt[0] in _DIALOGUE_OPENERS
            )
            if preserve_break:
                merged.append(nxt)
            else:
                merged[-1] = _join_wrapped_lines(prev, nxt)
        healed_blocks.append("\n".join(merged))
    return "\n\n".join(healed_blocks)


def detect_chapters(text: str, *, default_title: str = "Document") -> list[ChapterEntry]:
    """Detect chapter headings and compute non-overlapping [start, end) spans."""
    if not text:
        return []
    matches: list[tuple[int, str]] = []
    offset = 0
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped and len(stripped) <= 80 and _CHAPTER_HEADING_RE.match(stripped):
            matches.append((offset, stripped))
        offset += len(line) + 1

    if not matches:
        return [
            ChapterEntry(
                index=0,
                title=default_title,
                char_start=0,
                char_end=len(text),
            )
        ]

    chapters: list[ChapterEntry] = []
    if matches[0][0] > 0 and text[: matches[0][0]].strip():
        chapters.append(
            ChapterEntry(
                index=0,
                title="Opening",
                char_start=0,
                char_end=matches[0][0],
            )
        )
    base_idx = len(chapters)
    for i, (start, heading) in enumerate(matches):
        end = matches[i + 1][0] if i + 1 < len(matches) else len(text)
        if end > start:
            chapters.append(
                ChapterEntry(
                    index=base_idx + i,
                    title=heading,
                    char_start=start,
                    char_end=end,
                )
            )
    return chapters


def _flatten_pdf_outline(
    reader: Any,
    outline: Any,
    out: list[tuple[int, str]],
) -> None:
    if not isinstance(outline, list):
        return
    for item in outline:
        if isinstance(item, list):
            _flatten_pdf_outline(reader, item, out)
            continue
        title = str(getattr(item, "title", "") or "").strip()
        if not title and isinstance(item, dict):
            title = str(item.get("/Title") or "").strip()
        if not title:
            continue
        try:
            page_idx = reader.get_destination_page_number(item)
        except Exception:
            page_idx = None
        if isinstance(page_idx, int) and page_idx >= 0:
            out.append((page_idx, title))


def _chapters_from_pdf_outline(
    reader: Any,
    page_char_ranges: Sequence[tuple[int, int]],
    total_chars: int,
) -> list[ChapterEntry]:
    raw_entries: list[tuple[int, str]] = []
    try:
        outline = reader.outline
    except Exception:
        outline = None
    if outline:
        _flatten_pdf_outline(reader, outline, raw_entries)
    seen_pages: set[int] = set()
    unique: list[tuple[int, str]] = []
    for page_idx, title in sorted(raw_entries, key=lambda pair: pair[0]):
        if page_idx >= len(page_char_ranges) or page_idx in seen_pages:
            continue
        seen_pages.add(page_idx)
        unique.append((page_idx, title))
    if not unique:
        return []

    chapters: list[ChapterEntry] = []
    for idx, (page_idx, title) in enumerate(unique):
        char_start = page_char_ranges[page_idx][0]
        if idx + 1 < len(unique):
            next_page = unique[idx + 1][0]
            char_end = page_char_ranges[next_page][0]
            page_end = max(page_idx, next_page - 1)
        else:
            char_end = total_chars
            page_end = len(page_char_ranges) - 1
        if char_end > char_start:
            chapters.append(
                ChapterEntry(
                    index=len(chapters),
                    title=title,
                    char_start=char_start,
                    char_end=char_end,
                    page_start=page_idx + 1,
                    page_end=page_end + 1,
                )
            )
    return chapters


def ingest_txt(path: Path, *, title: str | None = None, raw_bytes: bytes | None = None) -> IngestedDocument:
    """Ingest a UTF-16/UTF-8/GB18030 plain text or Markdown file."""
    data = raw_bytes if raw_bytes is not None else path.read_bytes()
    doc_id = compute_doc_id(data)
    normalized = normalize_plain_text(decode_text_bytes(data))
    if not normalized.strip():
        raise AppError(
            "document.empty_content",
            {"filename": path.name},
            f"Document {path.name!r} contains no extractable text.",
            http_status=400,
        )
    resolved_title = str(title or path.stem or path.name).strip() or path.name
    chapters = detect_chapters(normalized, default_title=resolved_title)
    return IngestedDocument(
        doc_id=doc_id,
        title=resolved_title,
        source_format=path.suffix.lower().lstrip(".") or "txt",
        source_filename=path.name,
        normalized_text=normalized,
        chapters=tuple(chapters),
        page_count=None,
    )


def ingest_pdf(path: Path, *, title: str | None = None, raw_bytes: bytes | None = None) -> IngestedDocument:
    """Ingest a text-layer PDF via pypdf, rejecting scanned or encrypted files cleanly."""
    import pypdf

    data = raw_bytes if raw_bytes is not None else path.read_bytes()
    doc_id = compute_doc_id(data)
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise AppError(
            "document.pdf.unreadable",
            {"filename": path.name, "reason": str(exc)},
            f"Failed to parse PDF {path.name!r}: {exc}",
            http_status=400,
        ) from exc

    if getattr(reader, "is_encrypted", False):
        try:
            decrypted = reader.decrypt("")
        except Exception:
            decrypted = 0
        if not decrypted:
            raise AppError(
                "document.pdf.encrypted",
                {"filename": path.name},
                f"PDF {path.name!r} is password-protected.",
                http_status=400,
            )

    page_chunks: list[str] = []
    page_ranges: list[tuple[int, int]] = []
    cursor = 0
    for page in reader.pages:
        raw_page = page.extract_text() or ""
        healed_page = heal_pdf_line_breaks(raw_page)
        if page_chunks and healed_page:
            cursor += 2
        start = cursor
        page_chunks.append(healed_page)
        cursor += len(healed_page)
        page_ranges.append((start, cursor))

    normalized = "\n\n".join(part for part in page_chunks if part).strip()
    # Recompute page ranges matching exact joined text if leading blank pages were skipped
    non_empty_parts: list[str] = []
    aligned_ranges: list[tuple[int, int]] = []
    pos = 0
    for healed_page in page_chunks:
        if not healed_page:
            aligned_ranges.append((pos, pos))
            continue
        if non_empty_parts:
            pos += 2
        start = pos
        non_empty_parts.append(healed_page)
        pos += len(healed_page)
        aligned_ranges.append((start, pos))

    page_count = len(reader.pages)
    non_ws_chars = sum(1 for ch in normalized if not ch.isspace())
    if page_count == 0 or non_ws_chars < 40 or (page_count > 0 and non_ws_chars / page_count < 20):
        raise AppError(
            "document.pdf.scanned_or_empty",
            {"filename": path.name, "pageCount": page_count, "extractedChars": non_ws_chars},
            (
                f"PDF {path.name!r} appears to be scanned/image-only or lacks "
                f"sufficient extractable text ({non_ws_chars} chars across {page_count} pages)."
            ),
            http_status=400,
        )

    resolved_title = str(title or path.stem or path.name).strip() or path.name
    chapters = _chapters_from_pdf_outline(reader, aligned_ranges, len(normalized))
    if not chapters:
        chapters = detect_chapters(normalized, default_title=resolved_title)

    return IngestedDocument(
        doc_id=doc_id,
        title=resolved_title,
        source_format="pdf",
        source_filename=path.name,
        normalized_text=normalized,
        chapters=tuple(chapters),
        page_count=page_count,
    )


def ingest_document(
    source_path: str | Path,
    *,
    title: str | None = None,
    raw_bytes: bytes | None = None,
) -> IngestedDocument:
    """Ingest a supported document path (.txt, .md, .pdf)."""
    path = Path(source_path)
    if raw_bytes is None and not path.is_file():
        raise AppError(
            "document.not_found",
            {"filename": path.name},
            f"Document file not found: {path.name}",
            http_status=404,
        )
    suffix = path.suffix.lower()
    if suffix in _SUPPORTED_TEXT_SUFFIXES:
        return ingest_txt(path, title=title, raw_bytes=raw_bytes)
    if suffix == ".pdf":
        return ingest_pdf(path, title=title, raw_bytes=raw_bytes)
    raise AppError(
        "document.unsupported_format",
        {"filename": path.name, "extension": suffix},
        f"Unsupported document format: {suffix or '(none)'}",
        http_status=400,
    )


__all__ = [
    "compute_doc_id",
    "decode_text_bytes",
    "detect_chapters",
    "heal_pdf_line_breaks",
    "ingest_document",
    "ingest_pdf",
    "ingest_txt",
    "normalize_plain_text",
]
