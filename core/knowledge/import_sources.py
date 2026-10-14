"""Provider-independent source preparation for knowledge imports."""

from __future__ import annotations

import codecs
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from core.chat_history.text import history_payload_to_turns

MAX_IMPORT_FILES = 50
MAX_IMPORT_FILE_BYTES = 16 * 1024 * 1024
MAX_IMPORT_TOTAL_BYTES = 64 * 1024 * 1024
SUPPORTED_IMPORT_SUFFIXES = {".json", ".txt"}


@dataclass(frozen=True)
class ImportSource:
    name: str
    kind: str
    units: tuple[str, ...]


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


def prepare_import_sources(
    paths: Sequence[str | Path],
    *,
    source_root: str | Path,
) -> tuple[ImportSource, ...]:
    """Read TXT or chat-history JSON sources without AI or target-specific state."""
    sources: list[ImportSource] = []
    for path in _normalized_paths(paths, source_root=source_root):
        units = _source_turns(path, _read_supported_text(path))
        if not units:
            raise ValueError(f"没有从文件中识别到可提取的对话消息：{path.name}")
        sources.append(ImportSource(name=path.name, kind=path.suffix.lower()[1:], units=units))
    return tuple(sources)
