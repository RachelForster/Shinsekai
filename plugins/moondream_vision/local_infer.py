from __future__ import annotations

import io
import logging
import threading
from typing import Any

from PIL import Image

from plugins.moondream_vision.config_model import MoondreamVisionConfig

logger = logging.getLogger(__name__)

_model: Any = None
_model_key: tuple[str, str, str, str, str] | None = None
_lock = threading.Lock()


def _bitsandbytes_quant_config(mode: str) -> Any:
    import torch
    from transformers import BitsAndBytesConfig

    if mode == "int8":
        return BitsAndBytesConfig(load_in_8bit=True)
    if mode == "int4":
        compute_dtype = (
            torch.bfloat16
            if torch.cuda.is_bf16_supported()
            else torch.float16
        )
        return BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=compute_dtype,
            bnb_4bit_use_double_quant=True,
        )
    raise ValueError(f"unknown quantization mode: {mode!r}")


def _torch_load_kw(device: str) -> dict[str, Any]:
    import torch

    pref = (device or "auto").strip().lower()
    if pref == "auto":
        if torch.cuda.is_available():
            dt = (
                torch.bfloat16
                if torch.cuda.is_bf16_supported()
                else torch.float16
            )
            return {"device_map": "cuda", "torch_dtype": dt}
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return {"device_map": "mps", "torch_dtype": torch.float16}
        return {"device_map": {"": "cpu"}, "torch_dtype": torch.float32}
    if pref == "cuda":
        dt = (
            torch.bfloat16
            if torch.cuda.is_available() and torch.cuda.is_bf16_supported()
            else torch.float16
        )
        return {"device_map": "cuda", "torch_dtype": dt}
    if pref == "mps":
        return {"device_map": "mps", "torch_dtype": torch.float16}
    return {"device_map": {"": "cpu"}, "torch_dtype": torch.float32}


def _model_load_fp_kw(
    cfg: MoondreamVisionConfig,
) -> dict[str, Any]:
    """from_pretrained 中除 trust_remote_code / revision / cache_dir 外的关键字。"""
    import torch

    q = (cfg.quantization or "none").strip().lower()
    dev_pref = (cfg.device or "auto").strip().lower()
    if q in ("int8", "int4"):
        if not torch.cuda.is_available():
            raise RuntimeError(
                "INT8 / INT4 量化需要 NVIDIA GPU 与 CUDA。"
                "当前未检测到 CUDA，请将「量化」设为「无」或换用支持 CUDA 的环境。"
            )
        try:
            import bitsandbytes  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "INT8 / INT4 量化需要安装 bitsandbytes："
                "pip install bitsandbytes"
            ) from e
        return {
            "device_map": "auto",
            "quantization_config": _bitsandbytes_quant_config(q),
        }
    return _torch_load_kw(dev_pref)


def _model_cache_key(cfg: MoondreamVisionConfig) -> tuple[str, str, str, str, str]:
    return (
        (cfg.model_id or "").strip() or "vikhyatk/moondream2",
        (cfg.revision or "").strip(),
        (cfg.cache_dir or "").strip(),
        (cfg.device or "auto").strip().lower(),
        (cfg.quantization or "none").strip().lower(),
    )


def get_model(cfg: MoondreamVisionConfig) -> Any:
    """懒加载 HuggingFace 上的 Moondream2（首次调用会下载权重到本地缓存）。"""
    global _model, _model_key
    key = _model_cache_key(cfg)
    with _lock:
        if _model is not None and _model_key == key:
            return _model
        if _model is not None:
            try:
                del _model
            except Exception:
                pass
            _model = None
            _model_key = None
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
        try:
            from transformers import AutoModelForCausalLM
        except ImportError as e:
            raise RuntimeError(
                "请安装插件依赖：pip install -r plugins/moondream_vision/requirements.txt"
            ) from e

        mid = key[0]
        revision = key[1]
        cache_dir = key[2] or None
        load_kw = _model_load_fp_kw(cfg)
        fp_kw: dict[str, Any] = {
            "trust_remote_code": True,
            **load_kw,
        }
        if revision:
            fp_kw["revision"] = revision
        if cache_dir:
            fp_kw["cache_dir"] = cache_dir

        logger.info("Moondream 正在加载模型 %s（如需下载请稍候）…", mid)
        _model = AutoModelForCausalLM.from_pretrained(mid, **fp_kw)
        _model_key = key
        logger.info("Moondream 模型已就绪。")
        return _model


def infer_screen_png(png: bytes, question: str, cfg: MoondreamVisionConfig) -> str:
    model = get_model(cfg)
    image = Image.open(io.BytesIO(png)).convert("RGB")
    q = (question or "").strip() or "简要描述画面内容。"
    out = model.query(image, q)
    if isinstance(out, dict):
        ans = out.get("answer")
        if isinstance(ans, str) and ans.strip():
            return ans.strip()
    return str(out)[:4000]


def unload_model() -> None:
    global _model, _model_key
    with _lock:
        _model = None
        _model_key = None
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
