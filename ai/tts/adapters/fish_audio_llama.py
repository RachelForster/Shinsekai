"""Local llama.cpp GGUF discovery, process command, and speech payload helpers for Fish Audio S2 Pro."""

from __future__ import annotations

import array
import base64
import io
import os
from pathlib import Path
import shlex
import struct
import sys
from typing import Any
from urllib.parse import urlparse, urlunparse
import wave

from ai.tts.adapters.local_http import format_http_error
from ai.tts.adapters.qwen3_tts_discovery import _pick_gguf, _resolve_server_executable
from core.storage.layout import StorageLayout

DEFAULT_FISH_AUDIO_LLAMA_URL = "http://127.0.0.1:9882"
FISH_AUDIO_BACKEND_API = "api"
FISH_AUDIO_BACKEND_LLAMA_CPP = "llama-cpp"
FISH_AUDIO_BACKEND_CHOICES = [FISH_AUDIO_BACKEND_API, FISH_AUDIO_BACKEND_LLAMA_CPP]
FISH_AUDIO_CLOUD_HOSTS = frozenset({"api.fish.audio"})

_LLAMA_BACKEND_ALIASES = frozenset({"llama", "llama-cpp", "llama.cpp", "llamacpp", "gguf"})
_NAN_BUZZ_FRAMES = 512
_NAN_BUZZ_FRAME_SAMPLES = 2048
_NAN_BUZZ_MIN_SAMPLES = _NAN_BUZZ_FRAMES * _NAN_BUZZ_FRAME_SAMPLES
_NAN_BUZZ_SAMPLE_RATE = 44100


class FishAudioLlamaPoisonedError(RuntimeError):
    """Raised when llama-server returns a poisoned 512-frame periodic NaN buzz WAV."""


def normalize_fish_audio_backend(raw: str | None) -> str:
    """Normalize backend selector to ``api`` or ``llama-cpp``."""
    clean = str(raw or "").strip().lower()
    if clean in _LLAMA_BACKEND_ALIASES:
        return FISH_AUDIO_BACKEND_LLAMA_CPP
    return FISH_AUDIO_BACKEND_API


def resolve_fish_audio_llama_endpoints(server_url: str | None) -> tuple[str, str, str]:
    """Return ``(base_url_with_slash, speech_endpoint, health_endpoint)`` for llama-server."""
    raw = str(server_url or "").strip()
    parsed = urlparse(raw) if raw else None
    host = (parsed.hostname or "").lower() if parsed else ""
    if not raw or host in FISH_AUDIO_CLOUD_HOSTS or not parsed or not parsed.scheme:
        parsed = urlparse(DEFAULT_FISH_AUDIO_LLAMA_URL)

    clean_path = parsed.path.rstrip("/")
    for suffix in ("/v1/audio/speech", "/v1/tts", "/v1", "/tts"):
        if clean_path.endswith(suffix):
            clean_path = clean_path[: -len(suffix)]
            break
    base_url = urlunparse((parsed.scheme, parsed.netloc, clean_path, "", "", "")).rstrip("/")
    return f"{base_url}/", f"{base_url}/v1/audio/speech", f"{base_url}/health"


def discover_fish_audio_gguf_files(
    *,
    work_path: str | Path | None = None,
    model_path: str = "",
    mmproj_path: str = "",
    llama_server_path: str = "",
    project_root: str | os.PathLike[str] | None = None,
) -> tuple[str, str, str]:
    """Resolve ``(llama_server, model_gguf, mmproj_gguf)`` from explicit args or StorageLayout."""
    layout = StorageLayout.from_env(project_root)
    weight_dirs: list[Path] = []
    work_str = str(work_path or "").strip()
    if work_str:
        w = Path(work_str).expanduser()
        weight_dirs.append(w.parent if w.is_file() else w)
    weight_dirs.extend(
        [
            layout.model_dir("fish-audio-s2-pro-gguf"),
            layout.model_dir("fish-audio-s2-pro"),
            layout.cache_dir / "fish-audio-s2-pro-gguf",
        ]
    )

    raw_model = str(model_path or "").strip()
    if raw_model:
        candidate = Path(raw_model).expanduser()
        if candidate.is_dir():
            resolved_model = _pick_gguf([candidate], is_mmproj=False)
        else:
            resolved_model = candidate.resolve().as_posix()
    else:
        resolved_model = _pick_gguf(weight_dirs, is_mmproj=False)

    raw_mmproj = str(mmproj_path or "").strip()
    if raw_mmproj:
        resolved_mmproj = Path(raw_mmproj).expanduser().resolve().as_posix()
    else:
        resolved_mmproj = (
            _pick_gguf([Path(resolved_model).parent], is_mmproj=True) if resolved_model else ""
        )
        if not resolved_mmproj:
            resolved_mmproj = _pick_gguf(weight_dirs, is_mmproj=True)

    binary_dirs = [
        *weight_dirs,
        layout.model_dir("perception-gguf"),
        layout.cache_dir / "perception-gguf",
    ]
    resolved_server = _resolve_server_executable(llama_server_path, binary_dirs)
    return resolved_server, resolved_model, resolved_mmproj


def build_fish_audio_llama_server_cmd(
    *,
    llama_server: str,
    model_path: str,
    mmproj_path: str = "",
    server_url: str,
    n_gpu_layers: int = 99,
    ctx_size: int = 4096,
    threads: int = 0,
    extra_args: str = "",
) -> list[str]:
    """Assemble the ``llama-server`` CLI command for Fish Audio S2 Pro GGUF."""
    parsed = urlparse(server_url)
    host = (parsed.hostname or "").strip().lower()
    bind_host = "0.0.0.0" if host == "0.0.0.0" else "127.0.0.1"
    port = int(parsed.port or 9882)
    cmd = [
        llama_server,
        "-m",
        model_path,
    ]
    if mmproj_path:
        cmd.extend(["--mmproj", mmproj_path])
    cmd.extend(
        [
            "--host",
            bind_host,
            "--port",
            str(port),
            "-ngl",
            str(int(n_gpu_layers)),
            "--ctx-size",
            str(max(512, int(ctx_size))),
            "--parallel",
            "1",
            "--no-webui",
        ]
    )
    if int(threads) > 0:
        cmd.extend(["-t", str(int(threads))])
    clean_extra = str(extra_args or "").strip()
    if clean_extra:
        cmd.extend(shlex.split(clean_extra, posix=(os.name != "nt")))
    return cmd


def prepare_fish_audio_llama_launch(
    *,
    work_path: str | Path | None = None,
    model_path: str = "",
    mmproj_path: str = "",
    llama_server_path: str = "",
    server_url: str,
    n_gpu_layers: int = 99,
    ctx_size: int = 4096,
    threads: int = 0,
    extra_args: str = "",
    project_root: str | os.PathLike[str] | None = None,
) -> tuple[list[str], Path]:
    """Validate local GGUF + llama-server files and return ``(cmd, cwd)``."""
    llama_server, model, mmproj = discover_fish_audio_gguf_files(
        work_path=work_path,
        model_path=model_path,
        mmproj_path=mmproj_path,
        llama_server_path=llama_server_path,
        project_root=project_root,
    )
    default_dir = StorageLayout.from_env(project_root).model_dir("fish-audio-s2-pro-gguf")
    if not llama_server or not Path(llama_server).is_file():
        raise FileNotFoundError(
            f"llama-server executable not found (checked {default_dir / 'llama.cpp'} and perception-gguf)."
        )
    if not model or not Path(model).is_file():
        raise FileNotFoundError(
            f"Fish Audio S2 Pro GGUF backbone not found (expected under {default_dir})."
        )
    if not mmproj or not Path(mmproj).is_file():
        raise FileNotFoundError(
            f"Fish Audio S2 Pro mmproj GGUF not found (expected under {default_dir})."
        )
    cmd = build_fish_audio_llama_server_cmd(
        llama_server=llama_server,
        model_path=model,
        mmproj_path=mmproj,
        server_url=server_url,
        n_gpu_layers=n_gpu_layers,
        ctx_size=ctx_size,
        threads=threads,
        extra_args=extra_args,
    )
    return cmd, Path(llama_server).parent


def _decode_wav_pcm16(audio_bytes: bytes) -> tuple[int, array.array, bool] | None:
    if (
        len(audio_bytes) < 44
        or not audio_bytes.startswith(b"RIFF")
        or audio_bytes[8:12] != b"WAVE"
    ):
        return None
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
            nchannels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            sr = wf.getframerate()
            nframes = wf.getnframes()
            if sampwidth != 2 or nchannels < 1 or sr <= 0 or nframes <= 0:
                return None
            raw = wf.readframes(nframes)
    except (wave.Error, EOFError, ValueError):
        return None

    usable_bytes = len(raw) - (len(raw) % (2 * nchannels))
    if usable_bytes <= 0:
        return None
    samples = array.array("h")
    samples.frombytes(raw[:usable_bytes])
    if sys.byteorder != "little":
        samples.byteswap()
    if nchannels == 1:
        return sr, samples, True
    mono = array.array(
        "h",
        (
            sum(samples[i + ch] for ch in range(nchannels)) // nchannels
            for i in range(0, len(samples), nchannels)
        ),
    )
    return sr, mono, False


def _decode_audio_with_pyav(audio_bytes: bytes) -> tuple[int, array.array, bool] | None:
    try:
        import av  # type: ignore[import-not-found]
    except ImportError:
        return None

    try:
        with av.open(io.BytesIO(audio_bytes)) as container:
            stream = next((s for s in container.streams if s.type == "audio"), None)
            if stream is None:
                return None
            sr = int(getattr(stream, "rate", 0) or _NAN_BUZZ_SAMPLE_RATE)
            resampler = av.AudioResampler(format="s16", layout="mono", rate=sr)
            samples = array.array("h")

            def _append(frames: Any) -> None:
                for out_frame in frames:
                    pcm = out_frame.to_ndarray().reshape(-1).astype("<i2", copy=False).tobytes()
                    chunk = array.array("h")
                    chunk.frombytes(pcm)
                    if sys.byteorder != "little":
                        chunk.byteswap()
                    samples.extend(chunk)

            for frame in container.decode(stream):
                _append(resampler.resample(frame))
            _append(resampler.resample(None))
            return (sr, samples, False) if samples else None
    except Exception:
        return None


def _encode_mono_pcm16_wav(sr: int, samples: array.array) -> bytes:
    buf = io.BytesIO()
    pcm = array.array("h", samples)
    if sys.byteorder != "little":
        pcm.byteswap()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def sanitize_fish_audio_llama_ref_wav(ref_audio_bytes: bytes) -> bytes:
    """Trim leading digital silence and apply inaudible +-1 LSB dither for CUDA spkenc stability."""
    decoded = _decode_wav_pcm16(ref_audio_bytes) or _decode_audio_with_pyav(ref_audio_bytes)
    if decoded is None:
        return ref_audio_bytes
    sr, samples, was_mono_pcm16_wav = decoded
    if not samples:
        return ref_audio_bytes

    lead_silence = next((i for i, val in enumerate(samples) if abs(val) > 2), len(samples))
    prefix_len = min(len(samples), max(8192, sr))
    zero_run = 0
    has_long_zero_run = False
    for val in samples[:prefix_len]:
        zero_run = zero_run + 1 if val == 0 else 0
        if zero_run >= 16:
            has_long_zero_run = True
            break

    if was_mono_pcm16_wav and lead_silence <= 128 and not has_long_zero_run:
        return ref_audio_bytes

    if lead_silence > 128 and (len(samples) - lead_silence) >= max(512, sr // 20):
        samples = array.array("h", samples[lead_silence:])

    state = 0x12345678
    for idx, val in enumerate(samples):
        if val == 0:
            state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
            samples[idx] = 1 if (state & 0x10000) else -1

    return _encode_mono_pcm16_wav(sr, samples)


def is_fish_audio_llama_nan_buzz_wav(content: bytes) -> bool:
    """Return True when WAV bytes match llama-server's 512-frame periodic NaN buzz output."""
    if (
        len(content) < 44 + (_NAN_BUZZ_MIN_SAMPLES * 2)
        or not content.startswith(b"RIFF")
        or content[8:12] != b"WAVE"
    ):
        return False
    try:
        with wave.open(io.BytesIO(content), "rb") as wf:
            if (
                wf.getnchannels() != 1
                or wf.getsampwidth() != 2
                or wf.getframerate() != _NAN_BUZZ_SAMPLE_RATE
                or wf.getnframes() < _NAN_BUZZ_MIN_SAMPLES
            ):
                return False
            window_len = _NAN_BUZZ_FRAME_SAMPLES * 2
            wf.setpos(max(0, (wf.getnframes() - window_len) // 2))
            raw = wf.readframes(window_len)
    except (wave.Error, EOFError, ValueError):
        return False

    if len(raw) < window_len * 2:
        return False
    window = struct.unpack(f"<{window_len}h", raw[: window_len * 2])
    peak = max(abs(x) for x in window) / 32768.0
    mean_abs = sum(abs(x) for x in window) / window_len
    diff_2048 = (
        sum(
            abs(window[i] - window[i + _NAN_BUZZ_FRAME_SAMPLES])
            for i in range(_NAN_BUZZ_FRAME_SAMPLES)
        )
        / _NAN_BUZZ_FRAME_SAMPLES
    )
    return peak < 0.08 and mean_abs > 100.0 and diff_2048 < 32.0


def write_fish_audio_wav_response(
    response: Any,
    file_path: str | None,
    *,
    reject_nan_buzz: bool = False,
) -> str:
    """Validate an HTTP WAV response and write it to ``file_path``."""
    if not response.ok:
        raise RuntimeError(format_http_error(response, "Fish Audio S2 Pro TTS"))
    content = response.content
    if len(content) <= 44 or not content.startswith(b"RIFF"):
        raise RuntimeError("Fish Audio S2 Pro returned invalid or empty WAV payload.")
    if reject_nan_buzz and is_fish_audio_llama_nan_buzz_wav(content):
        raise FishAudioLlamaPoisonedError(
            "Fish Audio S2 Pro llama-server returned poisoned 512-frame NaN buzz audio."
        )
    out_path = Path(file_path or "temp_fish_audio_s2_pro.wav")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(content)
    return os.path.abspath(out_path)


def request_fish_audio_llama_speech(
    session: Any,
    endpoint: str,
    headers: dict[str, str],
    *,
    text: str,
    ref_audio_bytes: bytes | None,
    prompt_text: str,
    file_path: str | None,
    timeout: float,
) -> str:
    """POST a speech request to llama-server and validate the returned WAV file."""
    payload = build_fish_audio_llama_speech_payload(
        text=text,
        ref_audio_bytes=ref_audio_bytes,
        prompt_text=prompt_text,
    )
    response = session.post(
        endpoint,
        json=payload,
        headers=headers,
        timeout=timeout,
    )
    return write_fish_audio_wav_response(response, file_path, reject_nan_buzz=True)


def build_fish_audio_llama_speech_payload(
    *,
    text: str,
    ref_audio_bytes: bytes | None = None,
    prompt_text: str = "",
) -> dict[str, Any]:
    """Build the ``POST /v1/audio/speech`` JSON body for Fish Audio S2 Pro on llama-server."""
    payload: dict[str, Any] = {
        "input": text,
        "response_format": "wav",
    }
    if ref_audio_bytes:
        payload["speaker_ref_b64"] = base64.b64encode(ref_audio_bytes).decode("ascii")
        clean_prompt = str(prompt_text or "").strip()
        if clean_prompt:
            payload["speaker_ref_text"] = clean_prompt
    return payload


def build_fish_audio_llama_config_schema() -> dict[str, dict[str, Any]]:
    """Return llama.cpp GGUF configuration schema fields for Fish Audio S2 Pro."""
    p = "ops.api.tts.fishAudio.extra"
    return {
        "backend": {
            "type": "str",
            "label": "Execution Backend",
            "labelKey": f"{p}.backend",
            "default": FISH_AUDIO_BACKEND_API,
            "choices": list(FISH_AUDIO_BACKEND_CHOICES),
        },
        "model_path": {
            "type": "str",
            "label": "Backbone GGUF Model Path (optional)",
            "labelKey": f"{p}.modelPath",
            "default": "",
        },
        "mmproj_path": {
            "type": "str",
            "label": "Multimodal mmproj GGUF Path (optional)",
            "labelKey": f"{p}.mmprojPath",
            "default": "",
        },
        "llama_server_path": {
            "type": "str",
            "label": "llama-server Executable Path (optional)",
            "labelKey": f"{p}.llamaServerPath",
            "default": "",
        },
        "n_gpu_layers": {
            "type": "int",
            "label": "GPU Offload Layers (-ngl)",
            "labelKey": f"{p}.nGpuLayers",
            "default": 99,
            "min": 0,
            "max": 200,
        },
        "ctx_size": {
            "type": "int",
            "label": "Context Window Size (--ctx-size)",
            "labelKey": f"{p}.ctxSize",
            "default": 4096,
            "min": 512,
            "max": 32768,
        },
        "threads": {
            "type": "int",
            "label": "CPU Threads (0 = auto)",
            "labelKey": f"{p}.threads",
            "default": 0,
            "min": 0,
            "max": 128,
        },
    }
