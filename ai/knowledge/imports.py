"""Knowledge import with shared file preparation and setting extraction."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Sequence

from ai.memory.imports import PreparedMemoryImport, prepare_memory_import
from ai.knowledge.bindings import knowledge_operation_lock
from ai.knowledge.extraction import (
    EXPECTED_OUTPUT_TOKENS_PER_CHUNK,
    KnowledgeExtractor,
    KnowledgeEntry,
    deduplicate_knowledge_entries,
    estimate_knowledge_extraction_input_tokens,
)
from ai.knowledge.operations import add_knowledge_entry


def prepare_knowledge_import(
    paths: Sequence[str | Path],
    *,
    knowledge_id: str,
    source_root: str | Path,
    max_chunk_tokens: int,
) -> PreparedMemoryImport:
    if not str(knowledge_id or "").strip():
        raise ValueError("knowledge id is required")
    prepared = prepare_memory_import(
        paths,
        character_name=knowledge_id,
        source_root=source_root,
        max_chunk_tokens=max_chunk_tokens,
    )
    return replace(
        prepared,
        estimated_input_tokens=sum(
            estimate_knowledge_extraction_input_tokens(chunk) for chunk in prepared.chunks
        ),
        estimated_output_tokens=len(prepared.chunks) * EXPECTED_OUTPUT_TOKENS_PER_CHUNK,
    )


def preview_knowledge_import(
    paths: Sequence[str | Path],
    *,
    knowledge_id: str,
    source_root: str | Path,
    max_chunk_tokens: int,
) -> dict[str, Any]:
    return prepare_knowledge_import(
        paths,
        knowledge_id=knowledge_id,
        source_root=source_root,
        max_chunk_tokens=max_chunk_tokens,
    ).preview_payload()


def execute_knowledge_import(
    paths: Sequence[str | Path],
    *,
    knowledge_id: str,
    source_root: str | Path,
    llm_adapter: Any,
    max_chunk_tokens: int,
    progress_callback: Callable[[str, float, str, str | None], None] | None = None,
    cancel_callback: Callable[[], None] | None = None,
) -> dict[str, Any]:
    knowledge_id = str(knowledge_id or "").strip()
    prepared = prepare_knowledge_import(
        paths,
        knowledge_id=knowledge_id,
        source_root=source_root,
        max_chunk_tokens=max_chunk_tokens,
    )
    extractor = KnowledgeExtractor(llm_adapter)
    extracted: list[KnowledgeEntry] = []
    chunks = prepared.chunks
    for index, chunk in enumerate(chunks, start=1):
        if cancel_callback:
            cancel_callback()
        if progress_callback:
            progress_callback(
                "extract",
                0.05 + 0.7 * ((index - 1) / max(1, len(chunks))),
                f"正在提取资料知识（{index}/{len(chunks)}）。",
                f"extract knowledge chunk {index}/{len(chunks)}",
            )
        extracted.extend(
            extractor.extract_chunk(
                chunk,
                knowledge_id=knowledge_id,
            )
        )
    unique, duplicate_count = deduplicate_knowledge_entries(extracted)
    saved = 0
    stored_duplicates = 0
    with knowledge_operation_lock:
        for index, item in enumerate(unique, start=1):
            if cancel_callback:
                cancel_callback()
            if progress_callback:
                progress_callback(
                    "write",
                    0.77 + 0.21 * ((index - 1) / max(1, len(unique))),
                    f"正在写入资料知识（{index}/{len(unique)}）。",
                    None,
                )
            result = add_knowledge_entry(item["content"], item["knowledge_id"])
            if not isinstance(result, dict) or result.get("ok") is not True:
                detail = (result.get("error") or result.get("message") or result.get("status")) if isinstance(result, dict) else result
                raise RuntimeError(f"写入资料知识失败：{detail or 'unknown error'}")
            if result.get("duplicate") is True:
                stored_duplicates += 1
                continue
            saved += 1
    if progress_callback:
        progress_callback("completed", 1.0, "资料知识导入完成。", None)
    return {
        "fileCount": len(prepared.sources),
        "chunkCount": len(chunks),
        "extractedCount": len(unique),
        "savedCount": saved,
        "duplicateCount": duplicate_count + stored_duplicates,
        "estimatedTotalTokens": prepared.estimated_total_tokens,
        "memories": [item["content"] for item in unique],
        "knowledge_id": knowledge_id,
    }
