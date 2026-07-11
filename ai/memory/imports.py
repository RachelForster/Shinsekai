"""Batch TXT/JSON import orchestration for long-term memory extraction."""

from __future__ import annotations

import codecs
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from ai.memory.chunking import DEFAULT_DIALOGUE_CHUNK_TOKENS, chunk_dialogue_units
from ai.memory.extraction import (
    EXPECTED_OUTPUT_TOKENS_PER_CHUNK,
    MemoryExtractor,
    deduplicate_memories,
    estimate_extraction_input_tokens,
)
from ai.memory.operations import memory_remember
from ai.memory.token_estimator import estimate_text_tokens
from core.sprite.chat_history_text import history_payload_to_turns

MAX_IMPORT_FILES = 50
MAX_IMPORT_FILE_BYTES = 16 * 1024 * 1024
MAX_IMPORT_TOTAL_BYTES = 64 * 1024 * 1024
SUPPORTED_IMPORT_SUFFIXES = {".json", ".txt"}

ProgressCallback = Callable[[str, float, str, str | None], None]
CancelCallback = Callable[[], None]


@dataclass(frozen=True)
class PreparedMemorySource:
    name: str
    kind: str
    turns: tuple[str, ...]
    dialogue: str
    chunks: tuple[str, ...]
    source_tokens: int

    def preview_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "dialogueLineCount": len(self.turns),
            "dialogueCharacters": len(self.dialogue),
            "sourceTokens": self.source_tokens,
            "chunkCount": len(self.chunks),
        }


@dataclass(frozen=True)
class PreparedMemoryImport:
    character_name: str
    sources: tuple[PreparedMemorySource, ...]
    estimated_input_tokens: int
    estimated_output_tokens: int

    @property
    def chunks(self) -> tuple[str, ...]:
        return tuple(chunk for source in self.sources for chunk in source.chunks)

    @property
    def estimated_total_tokens(self) -> int:
        return self.estimated_input_tokens + self.estimated_output_tokens

    def preview_payload(self) -> dict[str, Any]:
        return {
            "fileCount": len(self.sources),
            "dialogueLineCount": sum(len(source.turns) for source in self.sources),
            "dialogueCharacters": sum(len(source.dialogue) for source in self.sources),
            "sourceTokens": sum(source.source_tokens for source in self.sources),
            "chunkCount": sum(len(source.chunks) for source in self.sources),
            "estimatedInputTokens": self.estimated_input_tokens,
            "estimatedOutputTokens": self.estimated_output_tokens,
            "estimatedTotalTokens": self.estimated_total_tokens,
            "files": [source.preview_payload() for source in self.sources],
            "warnings": [],
        }


def _read_supported_text(path: Path) -> str:
    raw = path.read_bytes()
    if len(raw) > MAX_IMPORT_FILE_BYTES:
        raise ValueError(f"文件过大（单个文件最多 16 MiB）：{path.name}")
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError as exc:
            raise ValueError(f"无法读取文本编码：{path.name}") from exc
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return raw.decode("gb18030")
        except UnicodeDecodeError as exc:
            raise ValueError(f"仅支持 UTF-8、UTF-16 或 GB18030 文本：{path.name}") from exc


def _source_turns(path: Path, text: str) -> tuple[str, ...]:
    if path.suffix.lower() == ".txt":
        turns = tuple(line.strip() for line in text.splitlines() if line.strip())
        if not turns and text.strip():
            turns = (text.strip(),)
        return turns
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 历史消息格式无效：{path.name}（第 {exc.lineno} 行）") from exc
    return tuple(history_payload_to_turns(payload))


def _normalized_paths(
    paths: Sequence[str | Path],
    *,
    source_root: str | Path,
) -> list[Path]:
    if not paths:
        raise ValueError("请至少选择一个 TXT 或 JSON 文件。")
    if len(paths) > MAX_IMPORT_FILES:
        raise ValueError(f"一次最多导入 {MAX_IMPORT_FILES} 个文件。")

    root = Path(source_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(root.as_posix())

    normalized: list[Path] = []
    total_bytes = 0
    for raw_path in paths:
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        path = candidate.resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError(f"文件路径不允许：{path.name}")
        if path.suffix.lower() not in SUPPORTED_IMPORT_SUFFIXES:
            raise ValueError(f"不支持的文件类型：{path.name}（仅支持 .txt 和 .json）")
        if not path.is_file():
            raise FileNotFoundError(path.as_posix())
        size = path.stat().st_size
        if size > MAX_IMPORT_FILE_BYTES:
            raise ValueError(f"文件过大（单个文件最多 16 MiB）：{path.name}")
        total_bytes += size
        if total_bytes > MAX_IMPORT_TOTAL_BYTES:
            raise ValueError("所选文件总大小超过 64 MiB。")
        normalized.append(path)
    return normalized


def prepare_memory_import(
    paths: Sequence[str | Path],
    *,
    character_name: str,
    source_root: str | Path,
    max_chunk_tokens: int = DEFAULT_DIALOGUE_CHUNK_TOKENS,
) -> PreparedMemoryImport:
    target_name = str(character_name or "").strip()
    if not target_name:
        raise ValueError("character name is required")

    sources: list[PreparedMemorySource] = []
    estimated_input_tokens = 0
    for path in _normalized_paths(paths, source_root=source_root):
        text = _read_supported_text(path)
        turns = _source_turns(path, text)
        if not turns:
            raise ValueError(f"没有从文件中识别到可提取的对话消息：{path.name}")
        chunks = tuple(chunk_dialogue_units(turns, max_tokens=max_chunk_tokens))
        dialogue = "\n".join(turns)
        source = PreparedMemorySource(
            name=path.name,
            kind="json" if path.suffix.lower() == ".json" else "txt",
            turns=turns,
            dialogue=dialogue,
            chunks=chunks,
            source_tokens=estimate_text_tokens(dialogue),
        )
        sources.append(source)
        estimated_input_tokens += sum(
            estimate_extraction_input_tokens(chunk, target_name) for chunk in source.chunks
        )

    chunk_count = sum(len(source.chunks) for source in sources)
    return PreparedMemoryImport(
        character_name=target_name,
        sources=tuple(sources),
        estimated_input_tokens=estimated_input_tokens,
        estimated_output_tokens=chunk_count * EXPECTED_OUTPUT_TOKENS_PER_CHUNK,
    )


def preview_memory_import(
    paths: Sequence[str | Path],
    *,
    character_name: str,
    source_root: str | Path,
    max_chunk_tokens: int = DEFAULT_DIALOGUE_CHUNK_TOKENS,
) -> dict[str, Any]:
    return prepare_memory_import(
        paths,
        character_name=character_name,
        source_root=source_root,
        max_chunk_tokens=max_chunk_tokens,
    ).preview_payload()


def _report(
    callback: ProgressCallback | None,
    phase: str,
    progress: float,
    message: str,
    log: str | None = None,
) -> None:
    if callback is not None:
        callback(phase, max(0.0, min(1.0, progress)), message, log)


def _raise_for_remember_failure(result: Any, memory: str) -> None:
    if isinstance(result, dict) and result.get("ok") is True:
        return
    if isinstance(result, dict):
        detail = result.get("error") or result.get("message") or result.get("status") or result.get("kind")
    else:
        detail = result
    preview = memory if len(memory) <= 80 else f"{memory[:77]}..."
    raise RuntimeError(f"写入长期记忆失败：{detail or 'unknown error'}（{preview}）")


def execute_memory_import(
    paths: Sequence[str | Path],
    *,
    character_name: str,
    source_root: str | Path,
    llm_adapter: Any,
    max_chunk_tokens: int = DEFAULT_DIALOGUE_CHUNK_TOKENS,
    remember_func: Callable[[str, str | None], dict[str, Any]] = memory_remember,
    progress_callback: ProgressCallback | None = None,
    cancel_callback: CancelCallback | None = None,
) -> dict[str, Any]:
    _report(progress_callback, "parse", 0.02, "正在读取并转换历史消息。")
    prepared = prepare_memory_import(
        paths,
        character_name=character_name,
        source_root=source_root,
        max_chunk_tokens=max_chunk_tokens,
    )
    chunks = prepared.chunks
    extractor = MemoryExtractor(llm_adapter)
    extracted: list[dict[str, Any]] = []

    for index, chunk in enumerate(chunks, start=1):
        if cancel_callback is not None:
            cancel_callback()
        _report(
            progress_callback,
            "extract",
            0.05 + 0.7 * ((index - 1) / max(1, len(chunks))),
            f"正在提取长期记忆（{index}/{len(chunks)}）。",
            f"extract chunk {index}/{len(chunks)}",
        )
        extracted.extend(
            extractor.extract_chunk(
                chunk,
                default_character_name=prepared.character_name,
                force_character_name=prepared.character_name,
            )
        )

    unique, duplicate_count = deduplicate_memories(extracted)
    saved_count = 0
    stored_duplicate_count = 0
    for index, item in enumerate(unique, start=1):
        if cancel_callback is not None:
            cancel_callback()
        _report(
            progress_callback,
            "write",
            0.77 + 0.21 * ((index - 1) / max(1, len(unique))),
            f"正在写入长期记忆（{index}/{len(unique)}）。",
            None,
        )
        result = remember_func(item["memory"], prepared.character_name)
        _raise_for_remember_failure(result, item["memory"])
        if isinstance(result, dict) and result.get("duplicate") is True:
            stored_duplicate_count += 1
            continue
        saved_count += 1

    _report(progress_callback, "write", 0.99, "长期记忆导入即将完成。")
    return {
        "fileCount": len(prepared.sources),
        "chunkCount": len(chunks),
        "extractedCount": len(unique),
        "savedCount": saved_count,
        "duplicateCount": duplicate_count + stored_duplicate_count,
        "extractionDuplicateCount": duplicate_count,
        "storedDuplicateCount": stored_duplicate_count,
        "estimatedTotalTokens": prepared.estimated_total_tokens,
        "memories": [item["memory"] for item in unique],
    }
