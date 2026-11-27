"""GGUF model and llama-server discovery helpers for Qwen3-TTS."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from urllib.parse import urlparse

from core.storage.layout import StorageLayout

_LOCAL_HOSTS = frozenset({"", "127.0.0.1", "localhost", "0.0.0.0", "::1"})
_QUANT_PREFERENCE = ("q8_0", "q4_k_m", "bf16", "f16")

_LANGUAGE_ALIASES = {
    "": "",
    "auto": "",
    "all_ja": "japanese",
    "all_ko": "korean",
    "all_yue": "cantonese",
    "all_zh": "chinese",
    "cantonese": "cantonese",
    "chinese": "chinese",
    "cn": "chinese",
    "de": "german",
    "de_de": "german",
    "en": "english",
    "en_gb": "english",
    "en_us": "english",
    "english": "english",
    "es": "spanish",
    "fr": "french",
    "french": "french",
    "german": "german",
    "it": "italian",
    "italian": "italian",
    "ja": "japanese",
    "ja_jp": "japanese",
    "japanese": "japanese",
    "jp": "japanese",
    "ko": "korean",
    "ko_kr": "korean",
    "korean": "korean",
    "portuguese": "portuguese",
    "pt": "portuguese",
    "pt_br": "portuguese",
    "ru": "russian",
    "russian": "russian",
    "spanish": "spanish",
    "yue": "cantonese",
    "zh": "chinese",
    "zh_cn": "chinese",
    "zh_hk": "cantonese",
    "zh_tw": "chinese",
}


def _is_local_server_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in _LOCAL_HOSTS


def _normalize_qwen3_tts_lang(raw: str | None) -> str:
    clean = str(raw or "").strip().lower().replace("-", "_")
    if clean in _LANGUAGE_ALIASES:
        return _LANGUAGE_ALIASES[clean]
    base = clean.split("_", 1)[0]
    return _LANGUAGE_ALIASES.get(base, clean)


def _rank_gguf(path: Path) -> tuple[int, str]:
    lowered = path.name.lower()
    for idx, token in enumerate(_QUANT_PREFERENCE):
        if token in lowered:
            return (idx, lowered)
    return (len(_QUANT_PREFERENCE), lowered)


def _pick_gguf(dirs: list[Path], *, is_mmproj: bool) -> str:
    candidates: list[Path] = []
    for directory in dirs:
        if not directory.is_dir():
            continue
        for entry in directory.glob("*.gguf"):
            if not entry.is_file():
                continue
            has_mmproj = "mmproj" in entry.name.lower()
            if has_mmproj == is_mmproj:
                candidates.append(entry)
    if not candidates:
        return ""
    best = min(candidates, key=_rank_gguf)
    return best.resolve().as_posix()


def _resolve_server_executable(explicit: str, candidate_dirs: list[Path]) -> str:
    exe_name = "llama-server.exe" if os.name == "nt" else "llama-server"
    raw = str(explicit or "").strip()
    if raw:
        path = Path(raw).expanduser()
        if path.is_file():
            return path.resolve().as_posix()
        for sub in (path / "llama.cpp" / exe_name, path / exe_name):
            if sub.is_file():
                return sub.resolve().as_posix()
        return raw

    for directory in candidate_dirs:
        for sub in (directory / "llama.cpp" / exe_name, directory / exe_name):
            if sub.is_file():
                return sub.resolve().as_posix()

    which_hit = shutil.which(exe_name) or shutil.which("llama-server")
    return Path(which_hit).resolve().as_posix() if which_hit else ""


def discover_qwen3_tts_files(
    *,
    work_path: str | Path | None = None,
    model_path: str = "",
    mmproj_path: str = "",
    llama_server_path: str = "",
    project_root: str | os.PathLike[str] | None = None,
) -> tuple[str, str, str]:
    """Resolve ``(llama_server, model_gguf, mmproj_gguf)`` from explicit args or StorageLayout."""
    layout = StorageLayout.from_env(project_root)
    weight_dirs: list[Path] = []
    work_str = str(work_path or "").strip()
    if work_str:
        w = Path(work_str).expanduser()
        weight_dirs.append(w.parent if w.is_file() else w)
    weight_dirs.extend(
        [
            layout.model_dir("qwen3-tts-gguf"),
            layout.cache_dir / "qwen3-tts-gguf",
        ]
    )

    resolved_model = str(model_path or "").strip()
    if resolved_model:
        resolved_model = Path(resolved_model).expanduser().resolve().as_posix()
    else:
        resolved_model = _pick_gguf(weight_dirs, is_mmproj=False)

    resolved_mmproj = str(mmproj_path or "").strip()
    if resolved_mmproj:
        resolved_mmproj = Path(resolved_mmproj).expanduser().resolve().as_posix()
    else:
        mmproj_dirs = list(weight_dirs)
        if resolved_model:
            mmproj_dirs.insert(0, Path(resolved_model).parent)
        resolved_mmproj = _pick_gguf(mmproj_dirs, is_mmproj=True)

    binary_dirs = [
        *weight_dirs,
        layout.model_dir("perception-gguf"),
        layout.cache_dir / "perception-gguf",
    ]
    resolved_server = _resolve_server_executable(llama_server_path, binary_dirs)
    return resolved_server, resolved_model, resolved_mmproj


__all__ = [
    "_LANGUAGE_ALIASES",
    "_LOCAL_HOSTS",
    "_QUANT_PREFERENCE",
    "_is_local_server_url",
    "_normalize_qwen3_tts_lang",
    "_pick_gguf",
    "_rank_gguf",
    "_resolve_server_executable",
    "discover_qwen3_tts_files",
]
