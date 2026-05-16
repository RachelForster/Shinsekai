from __future__ import annotations

import importlib
import json
import logging
import ssl
import threading
import time
from typing import Any

from sdk.adapters.asr import ASRAdapter, TranscriptionCallback

_LOG = logging.getLogger(__name__)


def _parse_chunk_size(raw: str | list[int] | tuple[int, ...]) -> list[int]:
    if isinstance(raw, (list, tuple)):
        vals = [int(x) for x in raw]
    else:
        vals = [int(x.strip()) for x in str(raw or "5,10,5").split(",") if x.strip()]
    if len(vals) != 3:
        raise ValueError(f"chunk_size must contain 3 integers, got {raw!r}")
    return vals


def _funasr_lang(language: str) -> str:
    lang = (language or "zh").strip().lower().replace("-", "_")
    if lang.startswith("en"):
        return "en"
    if lang.startswith("ja"):
        return "ja"
    return "zh"


class FunASRWSSAdapter(ASRAdapter):
    """FunASR WebSocket streaming ASR adapter.

    This adapter keeps the host-facing contract simple:
    - microphone PCM capture stays in Shinsekai
    - recognition runs against a user-managed FunASR websocket service
    - partial/final transcripts are mapped onto the existing callback interface
    """

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        return {
            "host": {
                "type": "str",
                "label": "FunASR host",
                "default": "127.0.0.1",
            },
            "port": {
                "type": "int",
                "label": "FunASR port",
                "default": 10096,
                "min": 1,
                "max": 65535,
            },
            "use_ssl": {
                "type": "bool",
                "label": "Use SSL (wss://)",
                "default": False,
            },
            "mode": {
                "type": "str",
                "label": "Recognition mode",
                "default": "2pass",
                "choices": ["2pass", "online", "offline"],
            },
        }

    def __init__(
        self,
        language: str,
        callback: TranscriptionCallback,
        *,
        host: str = "127.0.0.1",
        port: int = 10096,
        use_ssl: bool = False,
        mode: str = "2pass",
        chunk_size: str | list[int] | tuple[int, ...] = "5,10,5",
        chunk_interval: int = 10,
        encoder_chunk_look_back: int = 4,
        decoder_chunk_look_back: int = 0,
        audio_fs: int = 16000,
        itn: bool = True,
        hotwords: str = "",
        wav_name: str = "shinsekai_mic",
        connect_timeout_sec: float = 10.0,
        recv_timeout_sec: float = 0.5,
        final_wait_timeout_sec: float = 1.0,
    ):
        super().__init__(language, callback)
        self.host = str(host or "127.0.0.1").strip()
        self.port = int(port)
        self.use_ssl = bool(use_ssl)
        self.mode = str(mode or "2pass").strip().lower()
        self.chunk_size = _parse_chunk_size(chunk_size)
        self.chunk_interval = int(chunk_interval)
        self.encoder_chunk_look_back = int(encoder_chunk_look_back)
        self.decoder_chunk_look_back = int(decoder_chunk_look_back)
        self.audio_fs = int(audio_fs)
        self.itn = bool(itn)
        self.hotwords = str(hotwords or "")
        self.wav_name = str(wav_name or "shinsekai_mic")
        self.connect_timeout_sec = float(connect_timeout_sec)
        self.recv_timeout_sec = float(recv_timeout_sec)
        self.final_wait_timeout_sec = float(final_wait_timeout_sec)

        self._state_lock = threading.Lock()
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._stop_event = threading.Event()

        self._status = "idle"
        self._last_error: str | None = None

        self._sender_thread: threading.Thread | None = None
        self._receiver_thread: threading.Thread | None = None
        self._ws = None
        self._pyaudio_ctx = None
        self._stream = None

        self._online_text = ""
        self._offline_text = ""
        self._frame_chunk = self._compute_frame_chunk()

    def _compute_frame_chunk(self) -> int:
        chunk_ms = 60 * self.chunk_size[1] / max(1, self.chunk_interval)
        return max(1, int(self.audio_fs / 1000 * chunk_ms))

    def _set_status(self, value: str) -> None:
        with self._state_lock:
            self._status = value

    def _get_status(self) -> str:
        with self._state_lock:
            return self._status

    def _import_websocket_client(self):
        return importlib.import_module("websocket")

    def _import_pyaudio(self):
        return importlib.import_module("pyaudio")

    def _build_uri(self) -> str:
        scheme = "wss" if self.use_ssl else "ws"
        return f"{scheme}://{self.host}:{self.port}"

    def _build_sslopt(self) -> dict[str, Any] | None:
        if not self.use_ssl:
            return None
        return {
            "cert_reqs": ssl.CERT_NONE,
            "check_hostname": False,
        }

    def _build_start_payload(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "chunk_size": list(self.chunk_size),
            "chunk_interval": self.chunk_interval,
            "encoder_chunk_look_back": self.encoder_chunk_look_back,
            "decoder_chunk_look_back": self.decoder_chunk_look_back,
            "audio_fs": self.audio_fs,
            "wav_name": self.wav_name,
            "wav_format": "pcm",
            "is_speaking": True,
            "hotwords": self.hotwords,
            "itn": self.itn,
            "lang": _funasr_lang(self.language),
        }

    def _connect(self) -> None:
        websocket = self._import_websocket_client()
        pyaudio = self._import_pyaudio()

        ws = websocket.create_connection(
            self._build_uri(),
            timeout=self.connect_timeout_sec,
            sslopt=self._build_sslopt(),
            enable_multithread=True,
        )
        ws.settimeout(self.recv_timeout_sec)

        pa = pyaudio.PyAudio()
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.audio_fs,
            input=True,
            frames_per_buffer=self._frame_chunk,
        )

        ws.send(json.dumps(self._build_start_payload(), ensure_ascii=False))

        self._ws = ws
        self._pyaudio_ctx = pa
        self._stream = stream

    def _safe_send_stop_signal(self) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            ws.send(json.dumps({"is_speaking": False}, ensure_ascii=False))
        except Exception:
            _LOG.debug("FunASR stop signal send failed", exc_info=True)

    def _close_resources(self) -> None:
        self._safe_send_stop_signal()

        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop_stream()
            except Exception:
                _LOG.debug("FunASR stream stop failed", exc_info=True)
            try:
                stream.close()
            except Exception:
                _LOG.debug("FunASR stream close failed", exc_info=True)

        pa = self._pyaudio_ctx
        self._pyaudio_ctx = None
        if pa is not None:
            try:
                pa.terminate()
            except Exception:
                _LOG.debug("FunASR PyAudio terminate failed", exc_info=True)

        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                ws.close()
            except Exception:
                _LOG.debug("FunASR websocket close failed", exc_info=True)

    def _note_worker_error(self, exc: BaseException) -> None:
        if self._stop_event.is_set():
            return
        self._last_error = str(exc)
        _LOG.error("FunASR adapter worker failed: %s", exc, exc_info=True)
        self._set_status("error")
        self._stop_event.set()
        self._close_resources()

    def _sender_loop(self) -> None:
        ws = self._ws
        stream = self._stream
        if ws is None or stream is None:
            return
        try:
            while not self._stop_event.is_set():
                if not self._pause_event.is_set():
                    time.sleep(0.05)
                    continue
                data = stream.read(self._frame_chunk, exception_on_overflow=False)
                if not data:
                    self._safe_send_stop_signal()
                    break
                ws.send_binary(data)
                time.sleep(0.01)
        except Exception as exc:
            self._note_worker_error(exc)

    def _receiver_loop(self) -> None:
        ws = self._ws
        if ws is None:
            return
        websocket = self._import_websocket_client()
        timeout_types = tuple(
            t
            for t in (
                getattr(websocket, "WebSocketTimeoutException", None),
                TimeoutError,
            )
            if isinstance(t, type)
        )
        try:
            while not self._stop_event.is_set():
                try:
                    msg = ws.recv()
                except timeout_types:
                    continue
                if msg is None:
                    continue
                if isinstance(msg, bytes):
                    try:
                        msg = msg.decode("utf-8")
                    except UnicodeDecodeError:
                        continue
                try:
                    payload = json.loads(msg)
                except Exception:
                    _LOG.debug("FunASR non-JSON message ignored: %r", msg)
                    continue
                self._handle_server_message(payload)
        except Exception as exc:
            self._note_worker_error(exc)

    def _handle_server_message(self, payload: dict[str, Any]) -> None:
        text = str(payload.get("text", "") or "")
        if not text:
            return

        mode = str(payload.get("mode", "") or "").strip().lower()
        is_final = bool(payload.get("is_final", False))

        if mode in ("online", "2pass-online"):
            if mode == "2pass-online":
                self._online_text = text
                text = f"{self._offline_text}{self._online_text}"
            self.callback(text, True)
            return

        if mode in ("offline", "2pass-offline"):
            if mode == "2pass-offline":
                self._online_text = ""
                self._offline_text += text
                text = self._offline_text
            self.callback(text, False)
            return

        self.callback(text, not is_final)

    def start(self) -> None:
        status = self._get_status()
        if status in ("listening", "paused"):
            return
        if status in ("error", "stopped"):
            self.stop()

        self._stop_event.clear()
        self._pause_event.set()
        self._online_text = ""
        self._offline_text = ""
        self._last_error = None

        try:
            self._connect()
        except Exception as exc:
            self._last_error = str(exc)
            self._set_status("error")
            self._close_resources()
            raise

        self._set_status("listening")
        self._sender_thread = threading.Thread(
            target=self._sender_loop,
            name="funasr_wss_sender",
            daemon=True,
        )
        self._receiver_thread = threading.Thread(
            target=self._receiver_loop,
            name="funasr_wss_receiver",
            daemon=True,
        )
        self._sender_thread.start()
        self._receiver_thread.start()

    def stop(self) -> None:
        self._pause_event.set()
        self._safe_send_stop_signal()
        if self.final_wait_timeout_sec > 0:
            time.sleep(self.final_wait_timeout_sec)
        self._stop_event.set()

        cur = threading.current_thread()
        for thread in (self._sender_thread, self._receiver_thread):
            if thread is not None and thread.is_alive() and thread is not cur:
                thread.join(timeout=2.0)

        self._sender_thread = None
        self._receiver_thread = None
        self._close_resources()

        if self._get_status() != "error":
            self._set_status("stopped")

    def get_status(self) -> str:
        return self._get_status()

    def pause(self) -> None:
        if self._get_status() != "listening":
            return
        self._pause_event.clear()
        self._set_status("paused")

    def resume(self) -> None:
        if self._get_status() != "paused":
            return
        self._pause_event.set()
        self._set_status("listening")
