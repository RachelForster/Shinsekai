from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

from i18n import normalize_lang
from sdk.adapters.asr import ASRAdapter, TranscriptionCallback

# Vosk 模型默认路径（可按本机下载模型修改）
VOSK_MODEL_PATH = "./assets/system/models/vosk-model-small-cn-0.22"


def get_asr_log() -> logging.Logger:
    """ASR 专用 logger：默认 stderr。级别可用环境变量 EASYAI_ASR_LOG（DEBUG/INFO/WARNING）。"""
    log = logging.getLogger("easyai.asr")
    if log.handlers:
        return log
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(threadName)s] easyai.asr: %(message)s"
        )
    )
    log.addHandler(h)
    _name = (os.environ.get("EASYAI_ASR_LOG") or "INFO").upper()
    _lvl = getattr(logging, _name, logging.INFO)
    log.setLevel(_lvl if isinstance(_lvl, int) else logging.INFO)
    log.propagate = False
    return log


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
    """与 API 页 ASR 下拉 userData 一致的存储键（vosk / faster_whisper / realtime_stt）。"""
    p = (prov or "vosk").strip().lower().replace("-", "_")
    if p in ("faster_whisper", "fasterwhisper", "whisper"):
        return "faster_whisper"
    if p in ("realtime_stt", "realtimestt"):
        return "realtime_stt"
    return "vosk"


class VoskAdapter(ASRAdapter):
    """
    Vosk 库的适配器。
    将 Vosk 的流式处理逻辑映射到 ASRAdapter 接口。
    """

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        return {
            "model_path": {
                "type": "str",
                "label": "Vosk model path",
                "default": VOSK_MODEL_PATH,
            }
        }

    def __init__(
        self,
        language: str,
        callback: TranscriptionCallback,
        model_path: str = VOSK_MODEL_PATH,
    ):
        super().__init__(language, callback)
        # 禁止在模块顶层 import vosk：会立刻执行其 open_dll/add_dll_directory，冻结时路径常无效。
        import pyaudio
        from vosk import Model, KaldiRecognizer  # noqa: E402

        self._pyaudio = pyaudio
        self._KaldiRecognizer = KaldiRecognizer
        self.model_path = Path(model_path).absolute().as_posix()
        self._is_running = False
        self._thread: Optional[threading.Thread] = None

        self._pause_event = threading.Event()
        self._pause_event.set()

        self.samplerate = 16000
        self.chunk_size = 8192

        try:
            self.model = Model(model_path=self.model_path)
        except Exception as e:
            _log.error("Vosk model load failed: %s path=%s", e, self.model_path)
            self.model = None

    def _vosk_recognition_loop(self):
        """在独立线程中运行的 Vosk 识别循环。"""
        if self.model is None:
            return
        pyaudio = self._pyaudio
        KaldiRecognizer = self._KaldiRecognizer

        p = pyaudio.PyAudio()
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.samplerate,
            input=True,
            frames_per_buffer=self.chunk_size,
        )

        recognizer = KaldiRecognizer(self.model, self.samplerate)
        stream.start_stream()

        while self._is_running:
            if not self._pause_event.is_set():
                time.sleep(0.1)
                continue

            data = stream.read(self.chunk_size, exception_on_overflow=False)
            if recognizer.AcceptWaveform(data):
                result_json = json.loads(recognizer.Result())
                if result_json.get("text"):
                    self.callback(result_json["text"], is_partial=False)
            else:
                result_json = json.loads(recognizer.PartialResult())
                if result_json.get("partial"):
                    self.callback(result_json["partial"], is_partial=True)

        stream.stop_stream()
        stream.close()
        p.terminate()
        _log.info("Vosk recognition loop ended")

    def start(self):
        """启动 Vosk 识别线程。"""
        if self._is_running:
            _log.warning("Vosk start: already running")
            return

        if self.model is None:
            _log.error("Vosk start: model load failed, cannot start")
            return

        _log.info("Vosk starting…")
        self._is_running = True
        self._thread = threading.Thread(target=self._vosk_recognition_loop)
        self._thread.start()
        _log.info("Vosk started")

    def stop(self):
        """停止 Vosk 识别线程。"""
        if not self._is_running:
            return

        _log.info("Vosk stopping…")
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join()
        _log.info("Vosk stopped")

    def get_status(self) -> str:
        """获取 Vosk 的运行状态。"""
        return "Running" if self._is_running else "Stopped"

    def pause(self):
        """暂停 Vosk 识别。"""
        if self._is_running:
            _log.info("Vosk pause")
            self._pause_event.clear()

    def resume(self):
        """恢复 Vosk 识别。"""
        if self._is_running:
            _log.info("Vosk resume")
            self._pause_event.set()


def create_default_asr_adapter(callback: TranscriptionCallback) -> ASRAdapter:
    """按 system_config.asr_provider 创建 ASR；Whisper 等由插件注册进 ``ASRAdapterFactory._adapters``。"""
    from asr.asr_manager import ASRAdapterFactory

    from config.adapter_extra_kwargs import filter_kwargs_for_ctor
    from config.config_manager import ConfigManager

    sys_cfg = ConfigManager().config.system_config
    lang = system_config_to_asr_lang(sys_cfg)
    prov = (sys_cfg.asr_provider or "vosk").strip().lower().replace("-", "_")
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

    adapter_cls = ASRAdapterFactory._adapters.get(storage_key)

    if adapter_cls is None:
        if storage_key != "vosk":
            _log.warning(
                "ASR provider %r not registered (e.g. enable Whisper ASR plugin); "
                "falling back to vosk.",
                storage_key,
            )
        adapter_cls = VoskAdapter

    if adapter_cls is VoskAdapter:
        _kw = filter_kwargs_for_ctor(VoskAdapter, extras)
        model_path = str(_kw.get("model_path") or VOSK_MODEL_PATH)
        return VoskAdapter(language=lang, callback=callback, model_path=model_path)

    _kw = filter_kwargs_for_ctor(adapter_cls, extras)
    if storage_key == "faster_whisper":
        _kw.update(model_size=model_sz, device=dev, compute_type=ct)
    elif storage_key == "realtime_stt":
        _kw.update(model_name=model_sz, device=dev, compute_type=ct)
    return adapter_cls(lang, callback, **_kw)