"""Unit tests for core.document ingestion and chapter/quote-aware chunking."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from core.document import (
    ChapterEntry,
    chunk_document,
    decode_text_bytes,
    detect_chapters,
    heal_pdf_line_breaks,
    ingest_document,
)
from sdk.exception.types import AppError


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_minimal_pdf(pages: Sequence[str]) -> bytes:
    """Construct a valid minimal PDF 1.4 byte payload with Helvetica text streams."""
    objects: list[bytes] = []
    kid_refs = " ".join(f"{4 + i * 2} 0 R" for i in range(len(pages)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kid_refs}] /Count {len(pages)} >>".encode("ascii"))
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for idx, page_text in enumerate(pages):
        content_obj_num = 5 + idx * 2
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_obj_num} 0 R >>".encode("ascii")
        )
        stream_body = (
            f"BT /F1 12 Tf 72 720 Td ({_escape_pdf_text(page_text)}) Tj ET\n".encode("latin-1")
            if page_text
            else b""
        )
        objects.append(
            f"<< /Length {len(stream_body)} >>\nstream\n".encode("ascii")
            + stream_body
            + b"endstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = [0]
    for obj_id, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{obj_id} 0 obj\n".encode("ascii"))
        out.extend(body)
        out.extend(b"\nendobj\n")
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


@pytest.mark.parametrize(
    ("encoding", "sample"),
    [
        ("utf-8", "第一章 初见\n\n夜雨落下来，廊灯一盏盏亮起。"),
        ("utf-8-sig", "Chapter 1\n\nMorning light spilled across the desk."),
        ("utf-16", "第一章 重逢\n\n风吹过车站月台。"),
        ("gb18030", "第二章 归途\n\n炉火边的茶已经温好。"),
    ],
)
def test_decode_and_ingest_txt_across_encodings(
    tmp_path: Path, encoding: str, sample: str
) -> None:
    target = tmp_path / "story.txt"
    raw = sample.encode(encoding)
    target.write_bytes(raw)

    assert decode_text_bytes(raw) == sample
    doc = ingest_document(target)
    assert doc.source_format == "txt"
    assert len(doc.doc_id) == 64
    assert "夜雨" in doc.normalized_text or "Morning" in doc.normalized_text or "车站" in doc.normalized_text or "茶" in doc.normalized_text


def test_detect_chapters_and_default_fallback() -> None:
    text = "序言文本\n\n第1章 启程\n内容一\n\nChapter 2 Arrival\nContent two"
    chapters = detect_chapters(text)
    assert [c.title for c in chapters] == ["Opening", "第1章 启程", "Chapter 2 Arrival"]
    assert all(c.char_end > c.char_start for c in chapters)

    plain = "Just a single short essay without headings."
    fallback = detect_chapters(plain, default_title="Essay")
    assert len(fallback) == 1
    assert fallback[0].title == "Essay"
    assert fallback[0].char_start == 0
    assert fallback[0].char_end == len(plain)


def test_heal_pdf_line_breaks_merges_wraps_and_preserves_paragraphs() -> None:
    raw = "这是被硬换行\n打断的同一段话。\n\n第1章 新标题\n“下一句对话开始。”\n- 列表条目"
    healed = heal_pdf_line_breaks(raw)
    assert "这是被硬换行打断的同一段话。" in healed
    assert "\n\n第1章 新标题\n“下一句对话开始。”\n- 列表条目" in healed


def test_ingest_pdf_text_and_scanned_detection(tmp_path: Path) -> None:
    text_pdf = tmp_path / "lecture.pdf"
    long_line = (
        "Chapter 1 Quantum State and Measurement. "
        "Observe how coherent superpositions evolve linearly until projection."
    )
    text_pdf.write_bytes(_build_minimal_pdf([long_line]))
    ingested = ingest_document(text_pdf)
    assert ingested.source_format == "pdf"
    assert ingested.page_count == 1
    assert "Quantum State" in ingested.normalized_text

    scanned_pdf = tmp_path / "scanned.pdf"
    scanned_pdf.write_bytes(_build_minimal_pdf([""]))
    with pytest.raises(AppError) as exc_info:
        ingest_document(scanned_pdf)
    assert exc_info.value.error_code == "document.pdf.scanned_or_empty"
    assert exc_info.value.http_status == 400


def test_ingest_unsupported_extension_raises_app_error(tmp_path: Path) -> None:
    bin_file = tmp_path / "notes.docx"
    bin_file.write_bytes(b"binary")
    with pytest.raises(AppError) as exc_info:
        ingest_document(bin_file)
    assert exc_info.value.error_code == "document.unsupported_format"


def test_chunk_document_respects_chapters_quotes_bounds_and_lookahead() -> None:
    ch0_para = "“这是第一句带引号的话，里面有。但是引号不能被拆开。”" + ("旁白补充句子。" * 80)
    ch1_para = "新章节的开端段落非常清晰。" + ("细雨打在青石板上。" * 30)
    text = f"{ch0_para}\n\n{ch1_para}"
    sep = text.index(ch1_para)
    chapters = [
        ChapterEntry(index=0, title="Ch1", char_start=0, char_end=sep),
        ChapterEntry(index=1, title="Ch2", char_start=sep, char_end=len(text)),
    ]

    chunks = chunk_document(
        text,
        chapters,
        target_chars=800,
        min_chars=500,
        max_chars=1300,
        lookahead_chars=120,
    )
    assert len(chunks) >= 2
    assert chunks[0].chunk_id == "chunk_00000"
    assert "“这是第一句带引号的话，里面有。但是引号不能被拆开。”" in chunks[0].text
    assert all(len(c.text) <= 1300 for c in chunks)
    # Chapter transitions must never merge across chapters
    ch0_chunks = [c for c in chunks if c.chapter_index == 0]
    ch1_chunks = [c for c in chunks if c.chapter_index == 1]
    assert ch0_chunks and ch1_chunks
    assert all(c.char_end <= sep for c in ch0_chunks)
    assert all(c.char_start >= sep for c in ch1_chunks)
    # Lookahead continuity
    for idx in range(len(chunks) - 1):
        assert chunks[idx].lookahead == chunks[idx + 1].text[:120]
    assert chunks[-1].lookahead == ""


def test_detect_chapters_generates_virtual_chapters_for_long_headingless_text() -> None:
    paragraphs = [f"第{i}段测试正文：夜风沿着长廊缓缓吹过，屋檐下的铜铃发出清脆声响。" * 4 for i in range(100)]
    long_text = "\n\n".join(paragraphs)
    assert len(long_text) > 10000

    chapters = detect_chapters(long_text, default_title="PlainBook")
    assert len(chapters) >= 2
    assert chapters[0].char_start == 0
    assert chapters[-1].char_end == len(long_text)
    for idx in range(len(chapters) - 1):
        assert chapters[idx].char_end == chapters[idx + 1].char_start

    chunks = chunk_document(long_text, chapters, target_chars=800, min_chars=500, max_chars=1300)
    chapter_indices = {c.chapter_index for c in chunks}
    assert len(chapter_indices) >= 2


def test_pdf_outline_starting_after_page_one_keeps_opening_front_matter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import types

    page1 = "Cover Page Front Matter Introduction. " * 4
    page2 = "Chapter One Begins Here With Full Text. " * 4
    pdf_path = tmp_path / "book_with_late_toc.pdf"
    pdf_path.write_bytes(_build_minimal_pdf([page1, page2]))

    class _Bookmark(dict):
        title = "Bookmark Chapter 1"

    bm = _Bookmark()
    orig_pdf_reader = __import__("pypdf").PdfReader

    class _PatchedReader(orig_pdf_reader):
        @property
        def outline(self):
            return [bm]

        def get_destination_page_number(self, item):
            return 1

    monkeypatch.setitem(
        __import__("sys").modules,
        "pypdf",
        types.SimpleNamespace(PdfReader=_PatchedReader),
    )

    ingested = ingest_document(pdf_path)
    assert len(ingested.chapters) == 2
    assert ingested.chapters[0].title == "Opening"
    assert ingested.chapters[0].char_start == 0
    assert ingested.chapters[0].page_start == 1
    assert ingested.chapters[1].title == "Bookmark Chapter 1"
    assert ingested.chapters[1].char_start == ingested.chapters[0].char_end
    assert "Front Matter Introduction" in ingested.normalized_text[: ingested.chapters[0].char_end]

    chunks = chunk_document(ingested.normalized_text, ingested.chapters)
    assert any(c.chapter_index == 0 and "Front Matter Introduction" in c.text for c in chunks)
    assert any(c.chapter_index == 1 and "Chapter One Begins Here" in c.text for c in chunks)
