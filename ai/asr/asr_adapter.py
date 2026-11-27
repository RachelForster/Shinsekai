from __future__ import annotations

from pathlib import Path
from typing import Any

from ai.asr.adapters.vosk import VOSK_MODEL_PATH, VoskAdapter as _RealVoskAdapter
from sdk.adapters.asr import ASRAdapter, TranscriptionCallback
from sdk.lang import normalize_lang
from sdk.logging import get_logger

VoskAdapter = _RealVoskAdapter


def get_asr_log():
    """Return the ASR logger managed by the host logging configuration."""
    return get_logger(__name__)


_log = get_asr_log()


def voice_ui_to_asr_lang(voice_ui: str) -> str:
    """将 system_config.voice_language（及菜单所选）映射到 ASR / Whisper 语言代码。"""
    s = (voice_ui or "zh").strip().lower().replace("-", "_")
    if s.startswith("zh"):
        return "zh"
    if s in ("ja", "jp"):
        return "ja"
    if s.startswith("en"):
        return "en"
    if s in ("yue", "cantonese", "zh_yue"):
        # Whisper 无 yue 独立码，粤语会话用 zh 识别常可接受
        return "zh"
    return "zh"


def ui_lang_to_asr_lang(ui_lang: str | None) -> str:
    """将 system_config.ui_language（zh_CN / en / ja）映射到 ASR 语言代码。"""
    code = normalize_lang(ui_lang)
    if code == "en":
        return "en"
    if code == "ja":
        return "ja"
    return "zh"


def system_config_to_asr_lang(sys_cfg: Any) -> str:
    """asr_language 非空则用其映射，否则与 ui_language 一致。"""
    raw = getattr(sys_cfg, "asr_language", None)
    if raw is not None and str(raw).strip():
        return voice_ui_to_asr_lang(str(raw))
    return ui_lang_to_asr_lang(str(getattr(sys_cfg, "ui_language", "") or ""))


def _whisper_triplet_from_sys(sys_cfg: Any) -> tuple[str, str, str]:
    """从 system_config 读取 Whisper / RealtimeSTT 共用的模型与设备选项。"""
    return (
        str(getattr(sys_cfg, "asr_whisper_model_size", None) or "small"),
        str(getattr(sys_cfg, "asr_whisper_device", None) or "auto"),
        str(getattr(sys_cfg, "asr_whisper_compute_type", None) or ""),
    )


def normalize_asr_provider_storage_key(prov: str) -> str:
    """与 API 页 ASR 下拉 userData 一致的存储键。

    内置兼容键会归一化到既有 slug；其他插件 provider 则保持其标准化后的原值，
    以便 ``register_asr_adapter("my_plugin_asr", ...)`` 这类扩展后端能被正确选择。
    """
    p = (prov or "sherpa_onnx").strip().lower().replace("-", "_")
    if p in ("sherpa_onnx", "sherpaonnx", "sherpa"):
        return "sherpa_onnx"
    if p in ("faster_whisper", "fasterwhisper", "whisper"):
        return "faster_whisper"
    if p in ("realtime_stt", "realtimestt"):
        return "realtime_stt"
    return p or "sherpa_onnx"


def create_default_asr_adapter(
    callback: TranscriptionCallback,
    *,
    registry: Any | None = None,
) -> ASRAdapter:
    """按 system_config.asr_provider 创建 ASR；Whisper 等由插件注册进 ASR ``AdapterRegistry``。"""
    from ai.asr.registry import get_asr_adapter_registry
    from config.adapter_extra_kwargs import filter_kwargs_for_ctor
    from config.config_manager import ConfigManager

    active_registry = registry if registry is not None else get_asr_adapter_registry()
    sys_cfg = ConfigManager().config.system_config
    lang = system_config_to_asr_lang(sys_cfg)
    prov = (sys_cfg.asr_provider or "sherpa_onnx").strip().lower().replace("-", "_")
    storage_key = normalize_asr_provider_storage_key(prov)
    extras = ConfigManager().get_adapter_extra_config("asr", storage_key)
    model_sz, dev, ct = _whisper_triplet_from_sys(sys_cfg)
    _log.info(
        "create_default_asr_adapter: provider=%r language=%r whisper_model=%r device=%r compute=%r",
        prov,
        lang,
        model_sz,
        dev,
        ct,
    )

    adapter_cls = active_registry.get(storage_key)

    if adapter_cls is None:
        fallback_key = "sherpa_onnx" if "sherpa_onnx" in active_registry else "vosk"
        if storage_key != fallback_key:
            _log.warning(
                "ASR provider %r not registered (e.g. enable Whisper ASR plugin); "
                "falling back to %s.",
                storage_key,
                fallback_key,
            )
        storage_key = fallback_key
        adapter_cls = active_registry.get(fallback_key) or VoskAdapter

    if adapter_cls is _RealVoskAdapter or adapter_cls is VoskAdapter:
        _kw = filter_kwargs_for_ctor(VoskAdapter, extras) if isinstance(VoskAdapter, type) else {}
        model_path = str(_kw.get("model_path") or VOSK_MODEL_PATH)
        return VoskAdapter(language=lang, callback=callback, model_path=model_path)

    _kw = filter_kwargs_for_ctor(adapter_cls, extras) if isinstance(adapter_cls, type) else {}
    if storage_key == "sherpa_onnx":
        _kw.setdefault("explicit_language", str(getattr(sys_cfg, "asr_language", "") or "").strip())
        try:
            return adapter_cls(lang, callback, **_kw)
        except ModuleNotFoundError as exc:
            if exc.name != "sherpa_onnx" or "vosk" not in active_registry:
                raise
            vosk_kw = filter_kwargs_for_ctor(
                VoskAdapter,
                ConfigManager().get_adapter_extra_config("asr", "vosk"),
            )
            vosk_model_path = str(vosk_kw.get("model_path") or VOSK_MODEL_PATH)
            if not Path(vosk_model_path).is_dir():
                raise
            _log.warning(
                "sherpa_onnx is not installed in the current Python runtime; "
                "falling back to Vosk (%s).",
                vosk_model_path,
            )
            return VoskAdapter(language=lang, callback=callback, model_path=vosk_model_path)
    elif storage_key == "faster_whisper":
        _kw.update(model_size=model_sz, device=dev, compute_type=ct)
    elif storage_key == "realtime_stt":
        _kw.update(model_name=model_sz, device=dev, compute_type=ct)
    return adapter_cls(lang, callback, **_kw)
