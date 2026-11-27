"""Vosk offline streaming ASR adapter."""

from __future__ import annotations

import json
from pathlib import Path
import threading
import time
from typing import Any, Optional

from core.adapters import builtin_adapter
from core.paths import resource_path
from sdk.adapters.asr import ASRAdapter, TranscriptionCallback
from sdk.logging import get_logger

# Vosk 模型默认路径（可按本机下载模型修改）
VOSK_MODEL_PATH = str(resource_path("assets/system/models/vosk-model-small-cn-0.22"))

_log = get_logger("ai.asr.asr_adapter")


@builtin_adapter("vosk", label="Vosk", order=20)
class VoskAdapter(ASRAdapter):
    """Vosk 库的适配器。将 Vosk 的流式处理逻辑映射到 ASRAdapter 接口。"""

    @classmethod
    def get_config_schema(cls) -> dict[str, dict[str, Any]]:
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
    ) -> None:
        super().__init__(language, callback)
        # 禁止在模块顶层 import vosk：会立刻执行其 open_dll/add_dll_directory，冻结时路径常无效。
        import pyaudio
        from vosk import KaldiRecognizer, Model  # noqa: E402

        self._pyaudio = pyaudio
        self._KaldiRecognizer = KaldiRecognizer
        raw_model_path = Path(model_path).expanduser()
        self.model_path = (
            raw_model_path.resolve(strict=False)
            if raw_model_path.is_absolute()
            else resource_path(raw_model_path)
        ).as_posix()
        self._is_running = False
        self._finalize_on_stop = False
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

    def _vosk_recognition_loop(self) -> None:
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

        try:
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

            if self._finalize_on_stop:
                result_json = json.loads(recognizer.FinalResult())
                if result_json.get("text"):
                    self.callback(result_json["text"], is_partial=False)
        except Exception as exc:
            self._capture_error = exc
            _log.exception("Vosk capture failed")
        finally:
            self._is_running = False
            stream.stop_stream()
            stream.close()
            p.terminate()
        _log.info("Vosk recognition loop ended")

    def start(self) -> None:
        """启动 Vosk 识别线程。"""
        if self._is_running:
            _log.warning("Vosk start: already running")
            return

        if self.model is None:
            message = f"Vosk model is unavailable: {self.model_path}"
            _log.error(message)
            raise RuntimeError(message)

        _log.info("Vosk starting…")
        self._finalize_on_stop = False
        self._capture_error = None
        self._pause_event.set()
        self._is_running = True
        self._thread = threading.Thread(target=self._vosk_recognition_loop)
        self._thread.start()
        _log.info("Vosk started")

    def stop(self) -> None:
        """停止 Vosk 识别线程。"""
        _log.info("Vosk stopping…")
        self._is_running = False
        if (
            self._thread
            and self._thread.is_alive()
            and self._thread is not threading.current_thread()
        ):
            self._thread.join()
        _log.info("Vosk stopped")

    def get_status(self) -> str:
        """获取 Vosk 的运行状态。"""
        return "Running" if self._is_running else "Stopped"

    def finish(self) -> None:
        self._finalize_on_stop = True
        self.stop()
        if getattr(self, "_capture_error", None) is not None:
            raise RuntimeError("Vosk could not finalize voice input") from self._capture_error

    def pause(self) -> None:
        """暂停 Vosk 识别。"""
        if self._is_running:
            _log.info("Vosk pause")
            self._pause_event.clear()

    def resume(self) -> None:
        """恢复 Vosk 识别。"""
        if self._is_running:
            _log.info("Vosk resume")
            self._pause_event.set()
