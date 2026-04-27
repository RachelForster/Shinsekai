"""根据 gpu_list 枚举 GPU/显存/厂商，并决定推荐下载的 TTS 整合包。"""

from __future__ import annotations

import platform
import re
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


def get_default_project_root() -> Path:
    """与 ConfigManager 一致：在含 data/config 的仓库根上解析路径。"""
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "data" / "config").is_dir():
            return anc
    return Path.cwd()


def get_gpu_list() -> list[dict[str, Any]]:
    if _gpu_get_info is None:
        return []
    try:
        out = _gpu_get_info()
        return out if isinstance(out, list) else []
    except Exception:  # pragma: no cover
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
