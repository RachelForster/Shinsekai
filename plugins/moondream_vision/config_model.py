from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class MoondreamVisionConfig:
    enabled: bool = False
    model_id: str = "vikhyatk/moondream2"
    """Hugging Face 模型 ID；首次推理时下载到本地缓存。"""
    revision: str = ""
    """可选：固定 git 修订，如 2025-01-09；留空则用默认分支。"""
    cache_dir: str = ""
    """可选：HF 缓存目录；留空则用系统默认（通常含 ~/.cache/huggingface）。"""
    device: str = "auto"
    """auto | cuda | mps | cpu"""
    quantization: str = "none"
    """none | int8 | int4。INT8/INT4 依赖 bitsandbytes，通常仅 NVIDIA CUDA 有效。"""
    motion_poll_sec: float = 0.35
    """差分/鼠标/窗口采样的时间间隔（秒）。"""
    diff_threshold: float = 0.018
    """缩略图变化比例阈值；越大越不敏感（约 0.003~0.35）。"""
    mouse_move_px: int = 12
    """鼠标移动超过该像素数视为活动。"""
    interval_sec: float = 20.0
    """满足触发条件后，两次送模型推理的最短间隔（秒）。"""
    monitor_index: int = 1
    """mss 显示器序号：1 为主屏，0 为虚拟全屏组合。"""
    question: str = "用一两句话描述当前屏幕上对聊天助手最有用的可见内容。"
    message_prefix: str = "[屏幕识别] "

    def clamp(self) -> None:
        self.motion_poll_sec = max(0.12, min(3.0, float(self.motion_poll_sec)))
        self.diff_threshold = max(0.003, min(0.35, float(self.diff_threshold)))
        self.mouse_move_px = max(2, min(128, int(self.mouse_move_px)))
        self.interval_sec = max(5.0, min(600.0, float(self.interval_sec)))
        self.monitor_index = max(0, min(32, int(self.monitor_index)))
        d = (self.device or "auto").strip().lower()
        if d not in ("auto", "cuda", "mps", "cpu"):
            d = "auto"
        self.device = d
        q = (self.quantization or "none").strip().lower()
        if q not in ("none", "int8", "int4"):
            q = "none"
        self.quantization = q


def default_config_path(plugin_root: Path) -> Path:
    return plugin_root / "config.json"


def load_config(path: Path) -> MoondreamVisionConfig:
    if not path.is_file():
        return MoondreamVisionConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return MoondreamVisionConfig()
        c = MoondreamVisionConfig(
            enabled=bool(raw.get("enabled", False)),
            model_id=str(raw.get("model_id", "vikhyatk/moondream2") or "vikhyatk/moondream2"),
            revision=str(raw.get("revision", "") or ""),
            cache_dir=str(raw.get("cache_dir", "") or ""),
            device=str(raw.get("device", "auto") or "auto"),
            quantization=str(raw.get("quantization", "none") or "none"),
            motion_poll_sec=float(
                raw.get("motion_poll_sec", MoondreamVisionConfig.motion_poll_sec)
            ),
            diff_threshold=float(
                raw.get("diff_threshold", MoondreamVisionConfig.diff_threshold)
            ),
            mouse_move_px=int(
                raw.get("mouse_move_px", MoondreamVisionConfig.mouse_move_px)
            ),
            interval_sec=float(raw.get("interval_sec", 20)),
            monitor_index=int(raw.get("monitor_index", 1)),
            question=str(raw.get("question", MoondreamVisionConfig.question)),
            message_prefix=str(
                raw.get("message_prefix", MoondreamVisionConfig.message_prefix)
            ),
        )
        c.clamp()
        return c
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return MoondreamVisionConfig()


def save_config(path: Path, cfg: MoondreamVisionConfig) -> None:
    cfg.clamp()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8"
    )
