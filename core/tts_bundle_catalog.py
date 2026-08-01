"""TTS bundle metadata and hardware recommendation for non-UI runtimes."""

from __future__ import annotations

import json
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sdk.file_transactions import (
    portable_name_key,
    read_text_snapshot_without_links,
)
from core.paths import (
    require_regular_file_without_links,
    resource_path,
    safe_path_component,
)
from sdk.process_launch import (
    capture_command_executable,
    run_with_stable_paths,
)

try:
    from gpu_list import get_info as _gpu_get_info
except ImportError:  # pragma: no cover - optional dependency
    _gpu_get_info = None  # type: ignore[misc, assignment]


MIN_VRAM_GB_GPT = 6.0


@dataclass(frozen=True)
class TtsBundleManifestEntry:
    kind: str
    bundle_dir_key: str
    filename: str
    download_url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class TtsBundleChoice:
    kind: str
    download_url: str
    bundle_dir_key: str


def _manifest_path() -> Path:
    return require_regular_file_without_links(
        resource_path("core/model_assets/tts_bundle_manifest.json"),
        field="TTS bundle manifest",
    )


def _validated_download_url(value: object) -> str:
    raw = str(value)
    if (
        not raw
        or raw != raw.strip()
        or "\\" in raw
        or any(
            ord(character) < 32
            or ord(character) == 127
            or 0xD800 <= ord(character) <= 0xDFFF
            for character in raw
        )
    ):
        raise ValueError("TTS bundle URL is empty or contains non-portable characters")
    try:
        parsed = urlsplit(raw)
        # Python defers malformed and out-of-range port validation until the
        # property is read.  Validate it while loading the catalog rather than
        # after a user has already started a download.
        parsed.port
    except ValueError as exc:
        raise ValueError("TTS bundle URL is malformed") from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or "%" in parsed.netloc
        or any(character.isspace() for character in parsed.netloc)
    ):
        raise ValueError(
            "TTS bundle URL must be an absolute HTTP(S) URL without "
            "credentials, an ambiguous authority, or a fragment"
        )
    return raw


def _entry_from_dict(raw: dict[str, Any]) -> TtsBundleManifestEntry:
    kind = safe_path_component(str(raw["kind"]), field="TTS bundle kind")
    bundle_dir_key = safe_path_component(
        str(raw["bundle_dir_key"]),
        field="TTS bundle directory key",
    )
    filename = safe_path_component(
        str(raw["filename"]),
        field="TTS bundle filename",
    )
    download_url = _validated_download_url(raw["download_url"])
    size = int(raw["size"])
    if size <= 0:
        raise ValueError("TTS bundle size must be positive")
    sha256 = str(raw["sha256"]).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError("TTS bundle sha256 must contain exactly 64 hex digits")
    return TtsBundleManifestEntry(
        kind=kind,
        bundle_dir_key=bundle_dir_key,
        filename=filename,
        download_url=download_url,
        size=size,
        sha256=sha256,
    )


def load_tts_bundle_manifest(
    path: Path | None = None,
) -> dict[str, TtsBundleManifestEntry]:
    source = require_regular_file_without_links(
        path if path is not None else _manifest_path(),
        field="TTS bundle manifest",
    )
    payload_text, _identity = read_text_snapshot_without_links(source)
    payload = json.loads(payload_text)
    if not isinstance(payload, dict) or not isinstance(payload.get("bundles"), list):
        raise ValueError("TTS bundle manifest must contain a bundles list")

    by_kind: dict[str, TtsBundleManifestEntry] = {}
    directory_keys: set[str] = set()
    filenames: set[str] = set()
    for raw_entry in payload["bundles"]:
        if not isinstance(raw_entry, dict):
            raise ValueError("TTS bundle manifest entries must be objects")
        entry = _entry_from_dict(raw_entry)
        if entry.kind in by_kind:
            raise ValueError(f"duplicate TTS bundle kind: {entry.kind}")
        directory_key = portable_name_key(entry.bundle_dir_key)
        filename_key = portable_name_key(entry.filename)
        if directory_key in directory_keys:
            raise ValueError(
                f"duplicate TTS bundle directory key: {entry.bundle_dir_key}"
            )
        if filename_key in filenames:
            raise ValueError(f"duplicate TTS bundle filename: {entry.filename}")
        by_kind[entry.kind] = entry
        directory_keys.add(directory_key)
        filenames.add(filename_key)
    return by_kind


TTS_BUNDLE_MANIFEST = load_tts_bundle_manifest()
_TTS_BUNDLE_MANIFEST_BY_KEY = {
    entry.bundle_dir_key: entry for entry in TTS_BUNDLE_MANIFEST.values()
}


def bundle_manifest_for_kind(kind: str) -> TtsBundleManifestEntry | None:
    return TTS_BUNDLE_MANIFEST.get(kind)


def bundle_manifest_for_key(
    bundle_dir_key: str,
) -> TtsBundleManifestEntry | None:
    return _TTS_BUNDLE_MANIFEST_BY_KEY.get(bundle_dir_key)


def bundle_choice_for_kind(kind: str) -> TtsBundleChoice:
    entry = bundle_manifest_for_kind(kind)
    if entry is None:
        entry = bundle_manifest_for_kind("genie")
    if entry is None:
        raise RuntimeError("TTS bundle manifest does not define the genie fallback")
    return TtsBundleChoice(
        kind=entry.kind,
        download_url=entry.download_url,
        bundle_dir_key=entry.bundle_dir_key,
    )


def is_nvidia_vendor(info: dict[str, Any]) -> bool:
    vendor = str(info.get("vendor", "") or "").lower()
    vendor_id = str(info.get("vendor_id", "") or "").lower()
    return "nvidia" in vendor or vendor_id in {"10de", "0x10de"}


def _vram_gb(info: dict[str, Any]) -> float:
    try:
        return float(info.get("vram_gb", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _needs_display_enrichment(info: dict[str, Any]) -> bool:
    def missing(value: object) -> bool:
        return str(value or "").strip().lower() in {
            "",
            "unknown",
            "generic",
            "?",
            "n/a",
            "na",
            "other",
        }

    return missing(info.get("vendor")) or missing(info.get("device"))


def _nvidia_smi_query_gpus() -> list[tuple[str, float]]:
    try:
        executable = capture_command_executable(
            "nvidia-smi",
            field="NVIDIA SMI executable",
        )
    except (OSError, PermissionError, RuntimeError, ValueError):
        return []

    kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "timeout": 8,
    }
    if sys.platform == "win32":
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if creation_flags:
            kwargs["creationflags"] = creation_flags
    try:
        process = run_with_stable_paths(
            [
                executable.path,
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            cwd=executable.parent,
            executable=executable,
            **kwargs,
        )
    except (OSError, PermissionError, subprocess.TimeoutExpired):
        return []
    if process.returncode != 0:
        return []

    rows: list[tuple[str, float]] = []
    for raw_line in str(process.stdout or "").splitlines():
        parts = [part.strip() for part in raw_line.strip().split(",", 1)]
        if len(parts) != 2 or not parts[0]:
            continue
        try:
            memory_mib = float(re.sub(r"[^\d.]", "", parts[1]) or "nan")
        except ValueError:
            continue
        if memory_mib != memory_mib:
            continue
        rows.append((parts[0], memory_mib / 1024.0))
    return rows


def _enrich_gpu_entries_with_nvidia_smi(
    gpus: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = _nvidia_smi_query_gpus()
    if not rows:
        return list(gpus)

    output = [dict(gpu) for gpu in gpus]
    missing_indexes = [
        index for index, gpu in enumerate(output) if _needs_display_enrichment(gpu)
    ]
    used_rows: set[int] = set()
    for index in missing_indexes:
        vram = _vram_gb(output[index])
        candidates = [
            (abs(vram - row_vram) if vram > 0.15 else 0.0, row_index)
            for row_index, (_name, row_vram) in enumerate(rows)
            if row_index not in used_rows
        ]
        if not candidates:
            continue
        difference, row_index = min(candidates)
        if vram > 0.15 and difference > 2.25:
            continue
        if vram <= 0.15 and len(rows) > 1 and len(missing_indexes) > 1:
            continue
        used_rows.add(row_index)
        name, row_vram = rows[row_index]
        output[index]["vendor"] = "NVIDIA"
        output[index]["device"] = name
        if vram <= 0.15:
            output[index]["vram_gb"] = round(row_vram, 2)
    return output


def is_rtx_50_series(device: str) -> bool:
    return bool(
        device
        and re.search(r"(?:GeForce\s*)?RTX\s*50[0-9]{2}\b", device, re.IGNORECASE)
    )


def pick_nvidia_gpus(gpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [gpu for gpu in gpus if is_nvidia_vendor(gpu)]


def pick_best_nvidia(gpus: list[dict[str, Any]]) -> dict[str, Any] | None:
    nvidia_gpus = pick_nvidia_gpus(gpus)
    return max(nvidia_gpus, key=_vram_gb) if nvidia_gpus else None


def recommend_tts_bundle(
    gpus: list[dict[str, Any]] | None,
) -> TtsBundleChoice:
    best = pick_best_nvidia(gpus or [])
    if best is not None and _vram_gb(best) >= MIN_VRAM_GB_GPT:
        return bundle_choice_for_kind(
            "gptso50"
            if is_rtx_50_series(str(best.get("device", "") or ""))
            else "gptso"
        )
    return bundle_choice_for_kind("genie")


def get_gpu_list() -> list[dict[str, Any]]:
    if _gpu_get_info is None:
        rows = _nvidia_smi_query_gpus()
        return [
            {
                "vendor": "NVIDIA",
                "device": name,
                "vram_gb": round(vram, 2),
            }
            for name, vram in rows
        ]
    try:
        detected = _gpu_get_info()
    except Exception:  # pragma: no cover - third-party probe
        return []
    gpus = detected if isinstance(detected, list) else []
    enriched = _enrich_gpu_entries_with_nvidia_smi(gpus)
    if enriched:
        return enriched
    return [
        {
            "vendor": "NVIDIA",
            "device": name,
            "vram_gb": round(vram, 2),
        }
        for name, vram in _nvidia_smi_query_gpus()
    ]


def format_platform() -> str:
    try:
        return platform.platform(aliased=True, terse=True)
    except Exception:  # pragma: no cover
        return f"{platform.system()} {platform.release()}"


__all__ = [
    "TtsBundleChoice",
    "TtsBundleManifestEntry",
    "bundle_choice_for_kind",
    "bundle_manifest_for_key",
    "bundle_manifest_for_kind",
    "format_platform",
    "get_gpu_list",
    "load_tts_bundle_manifest",
    "recommend_tts_bundle",
]
