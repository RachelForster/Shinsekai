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


def _realtimestt_compute_sanitize(device: str, user_pref: str) -> str:
    """RealtimeSTT 在子进程内加载模型且无回退；CUDA 上 int8_float16 常在用户环境下报错。"""
    d = (device or "cpu").strip().lower()
    raw = (user_pref or "").strip()
    if not raw:
        return "float16" if d == "cuda" else "int8"
    c = raw.lower()
    if d == "cuda" and c == "int8_float16":
        _log.info(
            "RealtimeSTT: CUDA 下 int8_float16 已降级为 float16（可改 API 计算精度）"
        )
        return "float16"
    if d == "cpu" and c == "int8_float16":
        return "int8"
    return raw


class RealtimeSTTAdapter(ASRAdapter):
    """RealtimeSTT（realtimepy 包名 RealtimeSTT）：VAD + faster-whisper，实时字幕 + 每句结束 final。"""

    def __init__(
        self,
        language: str,
        callback: TranscriptionCallback,
        *,
        model_name: str = "small",
        device: str = "auto",
        compute_type: str = "",
    ):
        super().__init__(language, callback)
        self._model_name = (model_name or "small").strip()
        self._device_pref = device or "auto"
        self._compute_pref = compute_type or ""
        self._recorder: Any = None
        self._loop_thread: Optional[threading.Thread] = None
        self._is_running = False
        self._paused = False
        if os.name == "nt":
            venv_path = sys.prefix
            nvidia_base = os.path.join(venv_path, r"Lib\site-packages\nvidia")
            for sub in (r"cudnn\bin", r"cublas\bin", r"curand\bin"):
                full_path = os.path.join(nvidia_base, sub)
                if os.path.exists(full_path):
                    try:
                        os.add_dll_directory(full_path)
                    except (OSError, AttributeError):
                        pass

    @staticmethod
    def _device_resolved(pref: str) -> str:
        p = (pref or "auto").strip().lower()
        if p == "cpu":
            return "cpu"
        if p == "cuda":
            try:
                import torch

                return "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                return "cpu"
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    def _compute_resolved(self, device: str) -> str:
        c = (self._compute_pref or "").strip()
        if c:
            return c
        return "float16" if device == "cuda" else "int8"

    def _compute_for_recorder(self, device: str) -> str:
        base = self._compute_resolved(device)
        return _realtimestt_compute_sanitize(device, base)

    def _initial_prompt_optional(self) -> Optional[str]:
        lang = (self.language or "").strip().lower()
        if lang.startswith("en"):
            return "English speech."
        if lang in ("ja", "jp"):
            return "日本語の会話です。"
        return None

    def _setup_recorder(self) -> None:
        from RealtimeSTT import AudioToTextRecorder

        dev = self._device_resolved(self._device_pref)
        ct = self._compute_for_recorder(dev)
        _log.info(
            "RealtimeSTT setup_recorder: model=%r device=%r compute_type=%r lang=%r",
            self._model_name,
            dev,
            ct,
            (self.language or "").strip(),
        )

        def on_rt_update(text: str) -> None:
            t = (text or "").strip()
            if t:
                _log.debug(
                    "RealtimeSTT realtime partial: %s",
                    t[:200] + ("…" if len(t) > 200 else ""),
                )
                self.callback(t, True)

        self._recorder = AudioToTextRecorder(
            model=self._model_name,
            language=(self.language or "").strip(),
            compute_type=ct,
            device=dev,
            enable_realtime_transcription=True,
            use_main_model_for_realtime=True,
            on_realtime_transcription_update=on_rt_update,
            spinner=False,
            initial_prompt=self._initial_prompt_optional(),
        )

    def _text_loop(self) -> None:
        cycle = 0
        while self._is_running:
            if self._paused:
                time.sleep(0.08)
                continue
            rec = self._recorder
            if rec is None:
                _log.warning("RealtimeSTT _text_loop: recorder is None, exit loop")
                break
            try:
                cycle += 1
                _log.debug("RealtimeSTT text() cycle #%s start", cycle)
                final = rec.text()
                if not self._is_running:
                    _log.info("RealtimeSTT text() returned but _is_running=False, stop")
                    break
                if self._paused:
                    _log.debug(
                        "RealtimeSTT text() returned while paused (len=%s), skip final",
                        len(final or ""),
                    )
                    continue
                ft = (final or "").strip()
                if ft:
                    _log.info(
                        "RealtimeSTT text() cycle #%s final: %s",
                        cycle,
                        ft[:300] + ("…" if len(ft) > 300 else ""),
                    )
                    self.callback(ft, False)
                else:
                    _log.debug(
                        "RealtimeSTT text() cycle #%s empty final (interrupted?)",
                        cycle,
                    )
            except Exception:
                if self._is_running:
                    _log.exception("RealtimeSTT _text_loop exception (cycle #%s)", cycle)

    def start(self) -> None:
        if self._is_running:
            _log.warning("RealtimeSTT start: already running")
            return
        try:
            if self._recorder is None:
                self._setup_recorder()
        except ImportError as e:
            _log.error("RealtimeSTT import failed: %s (pip install realtimestt)", e)
            return
        except Exception:
            _log.exception("RealtimeSTT setup_recorder failed")
            self._recorder = None
            return
        _log.info("RealtimeSTT starting loop thread")
        self._is_running = True
        self._paused = False
        self._loop_thread = threading.Thread(
            target=self._text_loop, name="realtimestt_loop", daemon=True
        )
        self._loop_thread.start()
        _log.info("RealtimeSTT started (thread=%s)", self._loop_thread.name)

    def stop(self) -> None:
        rec = self._recorder
        loop_thread = self._loop_thread
        if not self._is_running and rec is None:
            _log.debug("RealtimeSTT stop: idle, skip")
            return
        _log.info("RealtimeSTT stopping…")
        self._is_running = False
        self._paused = False
        self._recorder = None
        self._loop_thread = None
        if rec is not None:
            try:
                # 勿先 abort：Windows 下转写为子进程，管道已断时 abort 可能阻塞
                # was_interrupted.wait() 且加剧 poll_connection 的 BrokenPipe 刷屏。
                rec.shutdown()
            except Exception:
                _log.warning("RealtimeSTT stop: shutdown()", exc_info=True)
        if loop_thread is not None and loop_thread.is_alive():
            loop_thread.join(timeout=15.0)
            if loop_thread.is_alive():
                _log.warning("RealtimeSTT stop: loop thread still alive after join")
        _log.info("RealtimeSTT stopped")

    def get_status(self) -> str:
        return "Running" if self._is_running else "Stopped"

    def pause(self) -> None:
        # sendMessage 与 TTS 都会 pause；勿在主线程（Qt 槽）里同步 abort()——库内 was_interrupted.wait 易死锁
        if self._paused:
            _log.debug("RealtimeSTT pause: already paused, skip")
            return
        self._paused = True
        _log.info("RealtimeSTT pause: scheduling abort on helper thread")
        rec = self._recorder
        if rec is not None:

            def _abort_safe() -> None:
                try:
                    _log.debug(
                        "RealtimeSTT abort() on %s",
                        threading.current_thread().name,
                    )
                    rec.abort()
                    _log.debug("RealtimeSTT abort() finished")
                except Exception:
                    _log.exception("RealtimeSTT abort() failed")

            threading.Thread(
                target=_abort_safe, daemon=True, name="realtimestt_abort"
            ).start()

    def resume(self) -> None:
        _log.info("RealtimeSTT resume: clear pause + events + listen()")
        self._paused = False
        rec = self._recorder
        if rec is None:
            _log.warning("RealtimeSTT resume: recorder is None")
            return
        for attr in ("interrupt_stop_event", "was_interrupted"):
            ev = getattr(rec, attr, None)
            if ev is not None:
                try:
                    ev.clear()
                    _log.debug("RealtimeSTT resume: cleared %s", attr)
                except Exception:
                    _log.warning(
                        "RealtimeSTT resume: clear %s failed", attr, exc_info=True
                    )
        try:
            rec.listen()
            _log.info("RealtimeSTT resume: listen() ok")
        except Exception:
            _log.exception("RealtimeSTT resume: listen() failed")

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

        # 暂停事件
        self._pause_event = threading.Event()
        self._pause_event.set()  # 初始状态为“不暂停”
        
        # 音频配置
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
        stream = p.open(format=pyaudio.paInt16,
                        channels=1,
                        rate=self.samplerate,
                        input=True,
                        frames_per_buffer=self.chunk_size)

        recognizer = KaldiRecognizer(self.model, self.samplerate)
        stream.start_stream()
        
        while self._is_running:
            if not self._pause_event.is_set():
                # 如果处于暂停状态，休眠一小会，避免占用 CPU
                time.sleep(0.1)
                continue

            data = stream.read(self.chunk_size, exception_on_overflow=False)
            if recognizer.AcceptWaveform(data):
                # 最终结果 (Final Result)
                result_json = json.loads(recognizer.Result())
                if result_json.get('text'):
                    self.callback(result_json['text'], is_partial=False)
            else:
                # 部分结果 (Partial Result)
                result_json = json.loads(recognizer.PartialResult())
                if result_json.get('partial'):
                    self.callback(result_json['partial'], is_partial=True)

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
            self._thread.join() # 等待线程安全退出
        _log.info("Vosk stopped")

    def get_status(self) -> str:
        """获取 Vosk 的运行状态。"""
        return "Running" if self._is_running else "Stopped"
    
    def pause(self):
        """暂停 Vosk 识别。"""
        if self._is_running:
            _log.info("Vosk pause")
            self._pause_event.clear()  # 设置为暂停状态
    
    def resume(self):
        """恢复 Vosk 识别。"""
        if self._is_running:
            _log.info("Vosk resume")
            self._pause_event.set()  # 设置为运行状态


def _resolve_whisper_device_compute(device_pref: str, compute_pref: str) -> tuple[str, str]:
    dp = (device_pref or "auto").strip().lower()
    cp = (compute_pref or "").strip()
    if dp == "auto":
        cuda_ok = False
        try:
            import torch

            cuda_ok = bool(torch.cuda.is_available())
        except Exception:
            cuda_ok = False
        if cuda_ok:
            return "cuda", cp or "float16"
        return "cpu", cp or "int8"
    if dp == "cuda":
        return "cuda", cp or "float16"
    return "cpu", cp or "int8"


def _whisper_compute_fallback_chain(device: str, preferred: str) -> list[str]:
    """在首选 compute_type 加载失败时依次尝试（如 int8 在当前后端不可用）。"""
    d = (device or "cpu").strip().lower()
    p = (preferred or "").strip().lower()
    if d == "cuda":
        order = ("float16", "int8_float16", "int8", "float32")
    else:
        order = ("int8", "int8_float32", "float32")
    out: list[str] = []
    if p:
        out.append(p)
    for x in order:
        if x not in out:
            out.append(x)
    return out


def _whisper_load_recoverable_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return (
        "int8" in msg
        or "compute type" in msg
        or "compute_type" in msg
        or ("backend" in msg and "support" in msg)
        or "efficient" in msg
    )


class FasterWhisperAdapter(ASRAdapter):
    """faster-whisper 适配器：PyAudio 采集 + 端点检测 + WhisperModel.transcribe。"""

    SAMPLERATE = 16000
    CHUNK = 1024
    MIN_UTTER_SAMPLES = int(16000 * 0.9)
    PARTIAL_EVERY_SAMPLES = int(16000 * 1.4)
    SILENCE_SAMPLES_END = int(0.42 * 16000)

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        return {
            "rms_threshold": {
                "type": "float",
                "label": "RMS threshold",
                "default": 38.0,
                "min": 1.0,
                "max": 500.0,
                "step": 0.5,
            }
        }

    def __init__(
        self,
        language: str,
        callback: TranscriptionCallback,
        *,
        model_size: str = "small",
        device: str = "auto",
        compute_type: str = "",
        rms_threshold: float = 38.0,
    ):
        super().__init__(language, callback)
        self._model_size = (model_size or "small").strip()
        self._device_pref = device or "auto"
        self._compute_pref = compute_type or ""
        self._rms_threshold = float(rms_threshold)
        self._model: Any = None
        self._is_running = False
        self._thread: Optional[threading.Thread] = None
        self._pause_event = threading.Event()
        self._pause_event.set()

    def _load_model(self) -> None:
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            _log.error("faster-whisper not installed: %s", e)
            return
        dev, ct = _resolve_whisper_device_compute(self._device_pref, self._compute_pref)
        chain = _whisper_compute_fallback_chain(dev, ct)
        last_err: Optional[BaseException] = None
        for i, ctry in enumerate(chain):
            _log.info(
                "faster-whisper load try model=%r device=%s compute_type=%s",
                self._model_size,
                dev,
                ctry,
            )
            try:
                self._model = WhisperModel(self._model_size, device=dev, compute_type=ctry)
            except Exception as e:
                last_err = e
                if _whisper_load_recoverable_error(e) and i + 1 < len(chain):
                    continue
                _log.warning("faster-whisper load error: %s", e)
                self._model = None
                return
            if ctry != ct:
                _log.info(
                    "faster-whisper compute_type adjusted %r -> %r",
                    ct,
                    ctry,
                )
            return
        _log.error("faster-whisper load failed after retries: %s", last_err)
        self._model = None

    def _transcribe_numpy(self, audio_i16: Any) -> str:
        import numpy as np

        if self._model is None:
            return ""
        audio = np.asarray(audio_i16, dtype=np.float32) / 32768.0
        if audio.size < 256:
            return ""
        lang = (self.language or "").strip() or None
        segments, _ = self._model.transcribe(
            audio,
            language=lang,
            beam_size=5,
            vad_filter=True,
            without_timestamps=True,
        )
        return "".join(seg.text for seg in segments).strip()

    def _recognition_loop(self) -> None:
        import numpy as np
        import pyaudio

        p = pyaudio.PyAudio()
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.SAMPLERATE,
            input=True,
            frames_per_buffer=self.CHUNK,
        )
        stream.start_stream()
        chunks: list[Any] = []
        silent_acc = 0
        last_partial_total = 0

        while self._is_running:
            if not self._pause_event.is_set():
                time.sleep(0.08)
                continue
            try:
                data = stream.read(self.CHUNK, exception_on_overflow=False)
            except Exception:
                _log.warning("faster-whisper stream.read failed, exit loop", exc_info=True)
                break
            np16 = np.frombuffer(data, dtype=np.int16)
            rms = float(
                np.sqrt(np.mean(np.square(np16.astype(np.float64))))
            )
            voice = rms >= self._rms_threshold

            if voice:
                silent_acc = 0
                chunks.append(np16)
                total = int(sum(len(c) for c in chunks))
                if (
                    total >= self.MIN_UTTER_SAMPLES
                    and total - last_partial_total >= self.PARTIAL_EVERY_SAMPLES
                ):
                    text = self._transcribe_numpy(np.concatenate(chunks))
                    if text:
                        self.callback(text, True)
                    last_partial_total = total
            else:
                if chunks:
                    silent_acc += len(np16)
                    if silent_acc >= self.SILENCE_SAMPLES_END:
                        audio = np.concatenate(chunks)
                        chunks = []
                        last_partial_total = 0
                        silent_acc = 0
                        text = self._transcribe_numpy(audio)
                        if text:
                            self.callback(text, False)
                else:
                    silent_acc = 0

        stream.stop_stream()
        stream.close()
        p.terminate()
        if chunks:
            text = self._transcribe_numpy(np.concatenate(chunks))
            if text:
                self.callback(text, False)
        _log.info("faster-whisper recognition loop ended")

    def start(self) -> None:
        if self._is_running:
            _log.warning("faster-whisper start: already running")
            return
        self._load_model()
        if self._model is None:
            _log.error("faster-whisper start: model not loaded")
            return
        _log.info("faster-whisper starting thread…")
        self._is_running = True
        self._thread = threading.Thread(
            target=self._recognition_loop, name="faster_whisper_asr", daemon=True
        )
        self._thread.start()
        _log.info("faster-whisper started")

    def stop(self) -> None:
        if not self._is_running:
            _log.debug("faster-whisper stop: not running")
            return
        _log.info("faster-whisper stopping…")
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=8.0)
        self._thread = None
        _log.info("faster-whisper stopped")

    def get_status(self) -> str:
        return "Running" if self._is_running else "Stopped"

    def pause(self) -> None:
        if self._is_running:
            _log.info("faster-whisper pause")
            self._pause_event.clear()

    def resume(self) -> None:
        if self._is_running:
            _log.info("faster-whisper resume")
            self._pause_event.set()


def create_default_asr_adapter(callback: TranscriptionCallback) -> ASRAdapter:
    """按 data/config/system_config.yaml 中 asr_provider 创建默认 ASR 适配器。"""
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
    if prov in ("faster_whisper", "fasterwhisper", "whisper"):
        _kw = filter_kwargs_for_ctor(FasterWhisperAdapter, extras)
        _kw.update(model_size=model_sz, device=dev, compute_type=ct)
        return FasterWhisperAdapter(lang, callback, **_kw)
    if prov in ("realtime_stt", "realtimestt"):
        _kw = filter_kwargs_for_ctor(RealtimeSTTAdapter, extras)
        _kw.update(model_name=model_sz, device=dev, compute_type=ct)
        return RealtimeSTTAdapter(lang, callback, **_kw)
    _kw = filter_kwargs_for_ctor(VoskAdapter, extras)
    model_path = str(_kw.get("model_path") or VOSK_MODEL_PATH)
    return VoskAdapter(language=lang, callback=callback, model_path=model_path)