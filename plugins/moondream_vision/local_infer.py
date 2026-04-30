from __future__ import annotations

import importlib
import io
import logging
import threading
from typing import Any

from PIL import Image

from plugins.moondream_vision.config_model import MoondreamVisionConfig

logger = logging.getLogger(__name__)

_model: Any = None
_model_key: tuple[str, str, str, str, str, str] | None = None
_lock = threading.Lock()

# Moondream2 的 vision 用自定义 F.linear；bitsandbytes 量化后权重为 int8，与 float 激活在 F.linear 里不兼容，须跳过量化。
_MOONDREAM_BNB_SKIP_MODULES: tuple[str, ...] = ("vision",)


def _moondream_inner(model: Any) -> Any | None:
    """定位带 vision.patch_emb 的 Moondream 核心模块（可能被 CausalLM 包装）。"""
    cur: Any = model
    for _ in range(12):
        vis = getattr(cur, "vision", None)
        if vis is not None:
            try:
                if "patch_emb" in vis:
                    return cur
            except TypeError:
                pass
        nxt = getattr(cur, "model", None) or getattr(cur, "base_model", None)
        if nxt is None or nxt is cur:
            break
        cur = nxt
    return None


def _patch_moondream_prepare_crops(inner: Any) -> None:
    """上游 prepare_crops 固定用 bfloat16；非 bf16 权重时需与 patch_emb.dtype 一致。"""
    try:
        import numpy as np
        import torch
        from PIL import Image as PILImage
    except ImportError:
        return
    try:
        wdt = inner.vision["patch_emb"].weight.dtype
    except Exception:
        return
    if wdt == torch.bfloat16:
        return
    mod_name = inner.__class__.__module__
    if not mod_name or "transformers_modules" not in mod_name:
        return
    pkg = mod_name.rsplit(".", 1)[0]
    try:
        image_crops_mod = importlib.import_module(f"{pkg}.image_crops")
        vision_mod = importlib.import_module(f"{pkg}.vision")
    except Exception as e:
        logger.warning("Moondream: 无法 patch prepare_crops（import 失败）: %s", e)
        return

    def prepare_crops(
        image: PILImage.Image,
        config: Any,
        device: Any,
    ) -> tuple[Any, Any]:
        np_image = np.array(image.convert("RGB"))
        overlap_crops = image_crops_mod.overlap_crop_image(
            np_image,
            max_crops=config.max_crops,
            overlap_margin=config.overlap_margin,
        )
        all_crops = overlap_crops["crops"]
        all_crops = np.transpose(all_crops, (0, 3, 1, 2))
        all_crops = (
            torch.from_numpy(all_crops)
            .to(device=device, dtype=wdt)
            .div_(255.0)
            .sub_(0.5)
            .div_(0.5)
        )
        return all_crops, overlap_crops["tiling"]

    vision_mod.prepare_crops = prepare_crops
    # moondream.py 里 `from .vision import prepare_crops` 已拷贝函数引用，仅改 vision 模块无效。
    try:
        moondream_mod = importlib.import_module(f"{pkg}.moondream")
        moondream_mod.prepare_crops = prepare_crops
    except Exception as e:
        logger.warning("Moondream: 无法将 prepare_crops 同步到 moondream 模块: %s", e)
    logger.info("Moondream: 已对齐 prepare_crops 与张量 dtype（%s）", wdt)


def _bitsandbytes_quant_config(mode: str) -> Any:
    import torch
    from transformers import BitsAndBytesConfig

    if mode == "int8":
        return BitsAndBytesConfig(
            load_in_8bit=True,
            llm_int8_skip_modules=list(_MOONDREAM_BNB_SKIP_MODULES),
        )
    if mode == "int4":
        return BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=(
                torch.bfloat16
                if torch.cuda.is_available() and torch.cuda.is_bf16_supported()
                else torch.float16
            ),
            bnb_4bit_use_double_quant=True,
            # transformers bitsandbytes 集成在 4bit 下仍用该字段跳过指定子模块的 Linear4bit 替换
            llm_int8_skip_modules=list(_MOONDREAM_BNB_SKIP_MODULES),
        )
    raise ValueError(f"unknown quantization mode: {mode!r}")


def _torch_load_kw(device: str) -> dict[str, Any]:
    import torch

    pref = (device or "auto").strip().lower()
    # Moondream2 的自定义 vision 模块在 float16 下会在 layer_norm 等处出现
    # 「expected scalar type Float but found Half」。非量化路径统一用 float32 加载。
    if pref == "auto":
        if torch.cuda.is_available():
            return {"device_map": "cuda", "torch_dtype": torch.float32}
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return {"device_map": "mps", "torch_dtype": torch.float32}
        return {"device_map": {"": "cpu"}, "torch_dtype": torch.float32}
    if pref == "cuda":
        return {"device_map": "cuda", "torch_dtype": torch.float32}
    if pref == "mps":
        return {"device_map": "mps", "torch_dtype": torch.float32}
    return {"device_map": {"": "cpu"}, "torch_dtype": torch.float32}


def _model_load_fp_kw(
    cfg: MoondreamVisionConfig,
) -> dict[str, Any]:
    """from_pretrained 中除 trust_remote_code / revision / cache_dir 外的关键字。"""
    import torch

    q = (cfg.quantization or "none").strip().lower()
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
        # 勿传顶层 modules_to_not_convert：trust_remote_code 的 HfMoondream 会把它原样传入 __init__ 并报错。
        return {
            "device_map": "auto",
            "quantization_config": _bitsandbytes_quant_config(q),
        }
    return _torch_load_kw((cfg.device or "auto").strip().lower())


def _model_cache_key(cfg: MoondreamVisionConfig) -> tuple[str, str, str, str, str, str]:
    q = (cfg.quantization or "none").strip().lower()
    # 与 _model_load_fp_kw 的非量化 dtype 策略一致；变更时需 bump 以丢弃旧缓存。
    dtype_tag = "bnb_skip_vision" if q in ("int8", "int4") else "fp32_md_v4"
    return (
        (cfg.model_id or "").strip() or "vikhyatk/moondream2",
        (cfg.revision or "").strip(),
        (cfg.cache_dir or "").strip(),
        (cfg.device or "auto").strip().lower(),
        q,
        dtype_tag,
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
        quant = key[4]
        if quant not in ("int8", "int4"):
            try:
                _model.float()
            except Exception:
                logger.exception("Moondream: model.float() 未完全成功，将仍尝试推理")
        try:
            _model.eval()
        except Exception:
            pass
        inner = _moondream_inner(_model)
        if inner is not None:
            _patch_moondream_prepare_crops(inner)
        else:
            logger.warning(
                "Moondream: 未找到 vision 子模块，若推理报 dtype 错误请检查 transformers 版本与模型结构。"
            )
        _model_key = key
        logger.info("Moondream 模型已就绪。")
        return _model


def infer_screen_png(png: bytes, question: str, cfg: MoondreamVisionConfig) -> str:
    from contextlib import nullcontext

    import torch

    model = get_model(cfg)
    image = Image.open(io.BytesIO(png)).convert("RGB")
    text_q = (question or "").strip() or "简要描述画面内容。"
    dev = next(model.parameters()).device
    if dev.type == "cuda":
        amp_ctx = torch.autocast(device_type="cuda", enabled=False)
    elif dev.type == "mps":
        try:
            amp_ctx = torch.autocast(device_type="mps", enabled=False)
        except (TypeError, ValueError, RuntimeError):
            amp_ctx = nullcontext()
    else:
        amp_ctx = nullcontext()
    with torch.inference_mode():
        with amp_ctx:
            out = model.query(image, text_q)
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
