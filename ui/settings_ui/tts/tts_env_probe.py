"""根据 gpu_list 枚举 GPU/显存/厂商，并决定推荐下载的 TTS 整合包。"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# PyPI: gpu-list → import gpu_list
try:
    from gpu_list import get_info as _gpu_get_info
except ImportError:  # pragma: no cover
    _gpu_get_info = None  # type: ignore[misc, assignment]


# 与 api_tab 资源区 ModelScope 链接一致
URL_GPTSOVITS_STANDARD = (
    "https://www.modelscope.cn/models/FlowerCry/gpt-sovits-7z-pacakges/"
    "resolve/master/GPT-SoVITS-v2pro-20250604.7z"
)
URL_GPTSOVITS_NVIDIA50 = (
    "https://www.modelscope.cn/models/FlowerCry/gpt-sovits-7z-pacakges/"
    "resolve/master/GPT-SoVITS-v2pro-20250604-nvidia50.7z"
)
URL_GENIE = (
    "https://www.modelscope.cn/models/twillzxy/genie-tts-server/resolve/master/"
    "Genie-TTS%20Server.7z"
)

# 8GB 及以上、N 卡 且非 50 系，使用通用 v2pro；50 系用 nvidia50 专用包
MIN_VRAM_GB_GPT = 8.0


@dataclass(frozen=True)
class TtsBundleChoice:
    """推荐下载的包类型与 URL、本地解压目录键。"""

    kind: str  # "genie" | "gptso" | "gptso50"
    download_url: str
    # data/tts_bundles/{bundle_dir_key}
    bundle_dir_key: str


def is_nvidia_vendor(info: dict[str, Any]) -> bool:
    v = str(info.get("vendor", "") or "").lower()
    vid = str(info.get("vendor_id", "") or "").lower()
    return "nvidia" in v or vid in ("10de", "0x10de", "0x10DE")


def _vram_gb(info: dict[str, Any]) -> float:
    try:
        return float(info.get("vram_gb", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _needs_display_enrichment(info: dict[str, Any]) -> bool:
    """Names missing after DXGI/WMI (common in PyInstaller); VRAM may still be valid."""

    def _bad(x: object) -> bool:
        s = str(x or "").strip().lower()
        return not s or s in ("unknown", "generic", "?", "n/a", "na", "other")

    return _bad(info.get("vendor")) or _bad(info.get("device"))


def _nvidia_smi_query_gpus() -> list[tuple[str, float]]:
    """Return [(gpu_name, vram_gb), ...] via driver CLI (reliable in frozen builds)."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    cmd = [
        exe,
        "--query-gpu=name,memory.total",
        "--format=csv,noheader,nounits",
    ]
    kwargs: dict[str, Any] = {
        "args": cmd,
        "capture_output": True,
        "text": True,
        "timeout": 8,
    }
    if sys.platform == "win32":
        cr = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if cr:
            kwargs["creationflags"] = cr
    try:
        proc = subprocess.run(**kwargs)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    stdout = (proc.stdout or "").strip()
    if not stdout:
        return []
    rows: list[tuple[str, float]] = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",", 1)]
        if len(parts) < 2:
            continue
        name, mem_s = parts[0], parts[1]
        try:
            mem_mib = float(re.sub(r"[^\d.]", "", mem_s) or "nan")
        except ValueError:
            continue
        if mem_mib != mem_mib:
            continue
        rows.append((name, mem_mib / 1024.0))
    return rows


def _enrich_gpu_entries_with_nvidia_smi(
    gpus: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = _nvidia_smi_query_gpus()
    if not rows:
        return list(gpus)

    out = [dict(g) for g in gpus]
    need_idx = [i for i, g in enumerate(out) if _needs_display_enrichment(g)]
    if not need_idx:
        return out

    used_nv: set[int] = set()
    for i in need_idx:
        vram = _vram_gb(out[i])
        best_j: int | None = None
        best_diff = 1e9
        for j, (_, gb_sm) in enumerate(rows):
            if j in used_nv:
                continue
            diff = abs(vram - gb_sm) if vram > 0.15 else 0.0
            if diff < best_diff:
                best_diff = diff
                best_j = j
        if best_j is None:
            continue
        name, gb_sm = rows[best_j]
        if vram > 0.15 and best_diff > 2.25:
            continue
        if vram <= 0.15 and len(rows) > 1 and len(need_idx) > 1:
            continue
        used_nv.add(best_j)
        out[i]["vendor"] = "NVIDIA"
        out[i]["device"] = name
        if vram <= 0.15:
            out[i]["vram_gb"] = round(gb_sm, 2)
    return out


def is_rtx_50_series(device: str) -> bool:
    """NVIDIA GeForce RTX 50xx（如 5090/5080），不含 3050/4050 等。"""
    if not device or not str(device).strip():
        return False
    s = str(device)
    if re.search(r"RTX\s*50[0-9]{2}\b", s, re.IGNORECASE):
        return True
    return bool(re.search(r"GeForce\s*RTX\s*50[0-9]{2}\b", s, re.IGNORECASE))


def pick_nvidia_gpus(gpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [g for g in gpus if is_nvidia_vendor(g)]


def pick_best_nvidia(gpus: list[dict[str, Any]]) -> dict[str, Any] | None:
    nvs = pick_nvidia_gpus(gpus)
    if not nvs:
        return None
    return max(nvs, key=_vram_gb)


def recommend_tts_bundle(gpus: list[dict[str, Any]] | None) -> TtsBundleChoice:
    """
    - NVIDIA + 显存 >= 8G + RTX 50 系 → nvidia50 整合包
    - NVIDIA + 显存 >= 8G + 非 50 系（40/30 等及更低）→ 通用 v2pro
    - 其他 → Genie TTS
    """
    gpus = gpus or []
    best = pick_best_nvidia(gpus)
    if best is not None and _vram_gb(best) >= MIN_VRAM_GB_GPT:
        dev = str(best.get("device", "") or "")
        if is_rtx_50_series(dev):
            return TtsBundleChoice(
                kind="gptso50",
                download_url=URL_GPTSOVITS_NVIDIA50,
                bundle_dir_key="gpt_sovits_nvidia50",
            )
        return TtsBundleChoice(
            kind="gptso",
            download_url=URL_GPTSOVITS_STANDARD,
            bundle_dir_key="gpt_sovits_v2pro",
        )
    return TtsBundleChoice(
        kind="genie",
        download_url=URL_GENIE,
        bundle_dir_key="genie_tts_server",
    )


def bundle_choice_for_kind(kind: str) -> TtsBundleChoice:
    """与下拉项 kind 对应；未知 kind 时回退 Genie。"""
    m: dict[str, TtsBundleChoice] = {
        "genie": TtsBundleChoice("genie", URL_GENIE, "genie_tts_server"),
        "gptso": TtsBundleChoice("gptso", URL_GPTSOVITS_STANDARD, "gpt_sovits_v2pro"),
        "gptso50": TtsBundleChoice("gptso50", URL_GPTSOVITS_NVIDIA50, "gpt_sovits_nvidia50"),
    }
    if kind in m:
        return m[kind]
    return m["genie"]


def get_default_project_root() -> Path:
    """与 ConfigManager 一致：在含 data/config 的仓库根上解析路径。"""
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "data" / "config").is_dir():
            return anc
    return Path.cwd()


def get_gpu_list() -> list[dict[str, Any]]:
    if _gpu_get_info is None:
        rows = _nvidia_smi_query_gpus()
        if not rows:
            return []
        return [
            {"vendor": "NVIDIA", "device": name, "vram_gb": round(gb, 2)}
            for name, gb in rows
        ]
    try:
        out = _gpu_get_info()
        gpus = out if isinstance(out, list) else []
    except Exception:  # pragma: no cover
        return []

    enriched = _enrich_gpu_entries_with_nvidia_smi(gpus)
    if gpus:
        return enriched

    rows = _nvidia_smi_query_gpus()
    if rows:
        return [
            {"vendor": "NVIDIA", "device": name, "vram_gb": round(gb, 2)}
            for name, gb in rows
        ]
    return []


def format_platform() -> str:
    try:
        return platform.platform(aliased=True, terse=True)
    except Exception:  # pragma: no cover
        return f"{platform.system()} {platform.release()}"


def format_gpu_lines(gpus: list[dict[str, Any]], *, none_msg: str) -> str:
    if not gpus:
        return none_msg
    lines: list[str] = []
    for i, g in enumerate(gpus, start=1):
        v = g.get("vendor", "?")
        d = g.get("device", "?")
        m = g.get("vram_gb", "?")
        lines.append(f"#{i} {v} | {d} | {m} GB (approx)")
    return "\n".join(lines)
