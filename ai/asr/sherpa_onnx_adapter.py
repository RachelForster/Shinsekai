"""Zero-PyTorch dual-stage streaming ASR adapter powered by sherpa-onnx.

Stage 1 (real-time partial preview, ~100ms):
    Streaming Zipformer transducer (`csukuangfj/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20`)
Stage 2 (endpoint final polish, ~50-80ms on CPU, zh/en/ja/yue/ko + punctuation):
    SenseVoiceSmall int8 (`csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17`)
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
import threading
import time
from typing import Any, Optional

from core.model_assets.service import (
    ModelAssetSpec,
    download_model_asset,
    find_cached_huggingface_snapshot,
)
from sdk.adapters.asr import ASRAdapter, TranscriptionCallback
from sdk.logging import get_logger

_log = get_logger(__name__)

SHERPA_ZIPFORMER_REPO = "csukuangfj/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"
SHERPA_SENSEVOICE_REPO = "csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"

ZIPFORMER_ENCODER = "encoder-epoch-99-avg-1.int8.onnx"
ZIPFORMER_DECODER = "decoder-epoch-99-avg-1.onnx"
ZIPFORMER_JOINER = "joiner-epoch-99-avg-1.int8.onnx"
ZIPFORMER_TOKENS = "tokens.txt"

SENSEVOICE_MODEL = "model.int8.onnx"
SENSEVOICE_TOKENS = "tokens.txt"

SHERPA_ZIPFORMER_ASSET = ModelAssetSpec(
    asset_id="asr.sherpa-zipformer",
    title="Sherpa-ONNX Streaming Zipformer (zh-en int8)",
    variant="streaming-zipformer-bilingual-zh-en",
    repo_id=SHERPA_ZIPFORMER_REPO,
    allow_patterns=(
        ZIPFORMER_ENCODER,
        ZIPFORMER_DECODER,
        ZIPFORMER_JOINER,
        ZIPFORMER_TOKENS,
    ),
    required_file_groups=(
        (ZIPFORMER_ENCODER,),
        (ZIPFORMER_DECODER,),
        (ZIPFORMER_JOINER,),
        (ZIPFORMER_TOKENS,),
    ),
    enforce_allow_patterns=False,
)

SHERPA_SENSEVOICE_ASSET = ModelAssetSpec(
    asset_id="asr.sherpa-sensevoice",
    title="Sherpa-ONNX SenseVoiceSmall (zh/en/ja/ko/yue int8)",
    variant="sense-voice-zh-en-ja-ko-yue-int8",
    repo_id=SHERPA_SENSEVOICE_REPO,
    allow_patterns=(
        SENSEVOICE_MODEL,
        SENSEVOICE_TOKENS,
    ),
    required_file_groups=(
        (SENSEVOICE_MODEL,),
        (SENSEVOICE_TOKENS,),
    ),
    enforce_allow_patterns=False,
)

_SUPPORTED_SENSEVOICE_LANGS = frozenset({"zh", "en", "ja", "yue", "ko"})


def normalize_sensevoice_language(explicit_language: str) -> str:
    """Map an explicit UI/config language code to SenseVoice code, or '' for auto-detect."""
    raw = str(explicit_language or "").strip().lower().replace("-", "_")
    if not raw or raw == "auto":
        return ""
    if raw.startswith("zh_yue") or raw in {"yue", "cantonese"}:
        return "yue"
    if raw.startswith("zh"):
        return "zh"
    if raw in {"ja", "jp"}:
        return "ja"
    if raw.startswith("en"):
        return "en"
    if raw.startswith("ko"):
        return "ko"
    return raw if raw in _SUPPORTED_SENSEVOICE_LANGS else ""


def _download_snapshot_via_direct_http(spec: ModelAssetSpec) -> Path:
    """Fallback downloader using direct HTTP GET when HF mirrors redirect HEAD to huggingface.co."""
    import os
    from core.downloads import download_archive
    from core.model_assets.service import _huggingface_cache_roots
    from huggingface_hub import HfApi

    endpoint = (
        os.environ.get("HF_ENDPOINT", "").strip()
        or os.environ.get("HUGGINGFACE_HUB_ENDPOINT", "").strip()
        or "https://hf-mirror.com"
    ).rstrip("/")
    api = HfApi(endpoint=endpoint)
    info = api.model_info(spec.repo_id, revision=spec.revision or None, timeout=15.0)
    revision = str(getattr(info, "sha", "") or "").strip()
    if not revision or len(revision) != 40:
        raise RuntimeError(f"Could not resolve commit hash for {spec.repo_id}")

    hub_root = _huggingface_cache_roots()[0]
    repo_dir = hub_root / ("models--" + spec.repo_id.replace("/", "--"))
    snapshot_dir = repo_dir / "snapshots" / revision
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    for group in spec.required_file_groups:
        rel_path = group[0]
        target = snapshot_dir / rel_path
        if target.is_file() and target.stat().st_size > 0:
            continue
        url = f"{endpoint}/{spec.repo_id}/resolve/{revision}/{rel_path}"
        _log.info("Direct HTTP GET %s -> %s", url, target)
        download_archive(url, target, {"User-Agent": "Shinsekai-Sherpa-ASR"})

    refs_dir = repo_dir / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)
    (refs_dir / (spec.revision or "main")).write_text(revision, encoding="utf-8")
    return snapshot_dir


def _resolve_or_download_asset(
    spec: ModelAssetSpec,
    explicit_dir: str = "",
    *,
    auto_download: bool = True,
) -> Path:
    clean_dir = str(explicit_dir or "").strip()
    if clean_dir:
        local = Path(clean_dir).expanduser().resolve(strict=False)
        if local.is_dir():
            return local
        raise FileNotFoundError(f"{spec.title} local directory not found: {local}")

    cached = find_cached_huggingface_snapshot(spec)
    if cached is not None:
        return cached
    if not auto_download:
        raise FileNotFoundError(
            f"{spec.title} is not cached locally ({spec.repo_id})."
        )

    _log.info("Downloading missing ASR asset %s (%s)...", spec.asset_id, spec.repo_id)
    try:
        download_model_asset(
            spec,
            update_task=lambda **kw: _log.info(
                "ASR download [%s]: %s", spec.asset_id, kw.get("message", "")
            ),
        )
    except Exception:
        _log.warning(
            "Standard HF snapshot download failed for %s; falling back to direct HTTP GET",
            spec.repo_id,
            exc_info=True,
        )
        _download_snapshot_via_direct_http(spec)

    resolved = find_cached_huggingface_snapshot(spec)
    if resolved is None:
        raise RuntimeError(f"Failed to resolve {spec.title} after download.")
    return resolved


class SherpaOnnxAdapter(ASRAdapter):
    """Dual-stage real-time streaming ASR: Streaming Zipformer preview + SenseVoiceSmall final."""

    SAMPLERATE = 16000
    CHUNK = 1600  # 100ms @ 16kHz
    PREROLL_CHUNKS = 4  # 400ms pre-roll before speech onset
    MIN_RMS_SPEECH_CHUNKS = 3  # 300ms minimum speech for RMS-only fallback endpoint
    RMS_TRAILING_SILENCE_CHUNKS = 8  # 800ms silence after RMS speech when transducer stays blank
    MAX_UTTERANCE_CHUNKS = 250  # 25s max single segment before forced polish

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        return {
            "rms_threshold": {
                "type": "float",
                "label": "RMS threshold",
                "default": 0.012,
                "min": 0.002,
                "max": 0.2,
                "step": 0.002,
            },
            "num_threads": {
                "type": "int",
                "label": "CPU threads",
                "default": 2,
                "min": 1,
                "max": 8,
            },
            "use_itn": {
                "type": "bool",
                "label": "Auto punctuation (ITN)",
                "default": True,
            },
        }

    def __init__(
        self,
        language: str,
        callback: TranscriptionCallback,
        *,
        explicit_language: str = "",
        rms_threshold: float = 0.012,
        num_threads: int = 2,
        use_itn: bool = True,
        zipformer_model_dir: str = "",
        sensevoice_model_dir: str = "",
        auto_download: bool = True,
    ):
        super().__init__(language, callback)
        import numpy as np
        import pyaudio
        import sherpa_onnx

        self._np = np
        self._pyaudio = pyaudio
        self._sherpa_onnx = sherpa_onnx

        self._sensevoice_lang = normalize_sensevoice_language(explicit_language)
        self._rms_threshold = max(0.001, float(rms_threshold))
        self._num_threads = max(1, int(num_threads))
        self._use_itn = bool(use_itn)

        zipformer_dir = _resolve_or_download_asset(
            SHERPA_ZIPFORMER_ASSET,
            zipformer_model_dir,
            auto_download=auto_download,
        )
        sensevoice_dir = _resolve_or_download_asset(
            SHERPA_SENSEVOICE_ASSET,
            sensevoice_model_dir,
            auto_download=auto_download,
        )

        self._online_recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(zipformer_dir / ZIPFORMER_TOKENS),
            encoder=str(zipformer_dir / ZIPFORMER_ENCODER),
            decoder=str(zipformer_dir / ZIPFORMER_DECODER),
            joiner=str(zipformer_dir / ZIPFORMER_JOINER),
            num_threads=self._num_threads,
            sample_rate=self.SAMPLERATE,
            feature_dim=80,
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=1.8,
            rule2_min_trailing_silence=0.75,
            rule3_min_utterance_length=20.0,
            decoding_method="greedy_search",
            provider="cpu",
        )
        self._offline_recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(sensevoice_dir / SENSEVOICE_MODEL),
            tokens=str(sensevoice_dir / SENSEVOICE_TOKENS),
            num_threads=self._num_threads,
            sample_rate=self.SAMPLERATE,
            use_itn=self._use_itn,
            language=self._sensevoice_lang,
            provider="cpu",
        )

        self._decode_lock = threading.Lock()
        self._online_stream: Any = None
        self._preroll: deque[Any] = deque(maxlen=self.PREROLL_CHUNKS)
        self._utterance_chunks: list[Any] = []
        self._speech_chunks = 0
        self._silent_chunks = 0
        self._last_partial = ""

        self._is_running = False
        self._finalize_on_stop = False
        self._capture_error: Optional[BaseException] = None
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._thread: Optional[threading.Thread] = None

    def _reset_segment_state_locked(self) -> None:
        if self._online_stream is not None:
            self._online_recognizer.reset(self._online_stream)
        self._preroll.clear()
        self._utterance_chunks.clear()
        self._speech_chunks = 0
        self._silent_chunks = 0
        self._last_partial = ""

    def _polish_utterance_locked(self) -> str:
        np = self._np
        partial_fallback = self._last_partial.strip()
        if not self._utterance_chunks:
            return partial_fallback

        audio = np.concatenate(self._utterance_chunks)
        if audio.size < int(self.SAMPLERATE * 0.15):
            return partial_fallback

        try:
            offline_stream = self._offline_recognizer.create_stream()
            offline_stream.accept_waveform(self.SAMPLERATE, audio)
            self._offline_recognizer.decode_stream(offline_stream)
            polished = str(getattr(offline_stream.result, "text", "") or "").strip()
            if polished:
                return polished
        except Exception:
            _log.warning("SenseVoice final polish failed; falling back to streaming text", exc_info=True)
        return partial_fallback

    def _flush_segment(self, *, emit: bool) -> None:
        final_text = ""
        with self._decode_lock:
            has_content = bool(self._last_partial.strip()) or self._speech_chunks >= self.MIN_RMS_SPEECH_CHUNKS
            if emit and has_content:
                final_text = self._polish_utterance_locked()
            self._reset_segment_state_locked()
        if emit and final_text:
            self.callback(final_text, False)

    def _process_audio_chunk(self, samples: Any) -> None:
        np = self._np
        partial_to_emit: Optional[str] = None
        final_to_emit: Optional[str] = None

        rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0
        voiced = rms >= self._rms_threshold

        with self._decode_lock:
            if self._online_stream is None:
                self._online_stream = self._online_recognizer.create_stream()

            self._online_stream.accept_waveform(self.SAMPLERATE, samples)
            while self._online_recognizer.is_ready(self._online_stream):
                self._online_recognizer.decode_stream(self._online_stream)

            partial = str(self._online_recognizer.get_result(self._online_stream) or "").strip()
            active = bool(self._utterance_chunks) or voiced or bool(partial)

            if not active:
                self._preroll.append(samples)
                return

            if not self._utterance_chunks and self._preroll:
                self._utterance_chunks.extend(self._preroll)
                self._preroll.clear()
            self._utterance_chunks.append(samples)

            partial_changed = bool(partial) and partial != self._last_partial
            if voiced or partial_changed:
                if voiced:
                    self._speech_chunks += 1
                self._silent_chunks = 0
            else:
                self._silent_chunks += 1

            if partial_changed:
                self._last_partial = partial
                partial_to_emit = partial

            has_speech = bool(self._last_partial) or self._speech_chunks >= self.MIN_RMS_SPEECH_CHUNKS
            transducer_endpoint = bool(
                self._online_recognizer.is_endpoint(self._online_stream)
                and (bool(partial) or has_speech)
            )
            rms_endpoint = (
                not partial
                and has_speech
                and self._silent_chunks >= self.RMS_TRAILING_SILENCE_CHUNKS
            )
            length_cap = len(self._utterance_chunks) >= self.MAX_UTTERANCE_CHUNKS

            if transducer_endpoint or rms_endpoint or length_cap:
                final_to_emit = self._polish_utterance_locked()
                self._reset_segment_state_locked()
                partial_to_emit = None
            elif not partial and not has_speech and self._silent_chunks >= self.RMS_TRAILING_SILENCE_CHUNKS:
                # Brief ambient noise spike that never became speech: discard buffer.
                self._reset_segment_state_locked()

        if partial_to_emit:
            self.callback(partial_to_emit, True)
        if final_to_emit:
            self.callback(final_to_emit, False)

    def _recognition_loop(self) -> None:
        np = self._np
        pyaudio = self._pyaudio
        pa = pyaudio.PyAudio()
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.SAMPLERATE,
            input=True,
            frames_per_buffer=self.CHUNK,
        )
        stream.start_stream()

        try:
            while self._is_running:
                if not self._pause_event.is_set():
                    time.sleep(0.05)
                    continue
                data = stream.read(self.CHUNK, exception_on_overflow=False)
                if not self._pause_event.is_set():
                    continue
                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                self._process_audio_chunk(samples)

            if self._finalize_on_stop:
                self._flush_segment(emit=True)
        except Exception as exc:
            self._capture_error = exc
            _log.exception("Sherpa-ONNX capture failed")
        finally:
            self._is_running = False
            try:
                stream.stop_stream()
                stream.close()
            finally:
                pa.terminate()
        _log.info("Sherpa-ONNX recognition loop ended")

    def start(self) -> None:
        if self._is_running:
            _log.warning("Sherpa-ONNX start: already running")
            return
        _log.info("Sherpa-ONNX starting (sensevoice_lang=%r)...", self._sensevoice_lang or "auto")
        with self._decode_lock:
            self._online_stream = self._online_recognizer.create_stream()
            self._reset_segment_state_locked()
        self._finalize_on_stop = False
        self._capture_error = None
        self._pause_event.set()
        self._is_running = True
        self._thread = threading.Thread(
            target=self._recognition_loop,
            name="sherpa_onnx_asr",
            daemon=True,
        )
        self._thread.start()
        _log.info("Sherpa-ONNX started")

    def stop(self) -> None:
        _log.info("Sherpa-ONNX stopping...")
        self._is_running = False
        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=5.0)
        self._thread = None
        _log.info("Sherpa-ONNX stopped")

    def finish(self) -> None:
        self._finalize_on_stop = True
        self.stop()
        if self._capture_error is not None:
            raise RuntimeError("Sherpa-ONNX could not finalize voice input") from self._capture_error

    def finish_hold(self, *, cancel: bool = False) -> bool:
        if not self._is_running:
            return False
        self._pause_event.clear()
        self._flush_segment(emit=not cancel)
        return self._is_running

    def get_status(self) -> str:
        return "Running" if self._is_running else "Stopped"

    def pause(self) -> None:
        if self._is_running:
            _log.info("Sherpa-ONNX pause")
            self._pause_event.clear()
            self._flush_segment(emit=False)

    def resume(self) -> None:
        if self._is_running:
            _log.info("Sherpa-ONNX resume")
            with self._decode_lock:
                self._reset_segment_state_locked()
            self._pause_event.set()
