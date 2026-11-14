"""WAV PCM signal acoustic analysis and slicer span duration utilities."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
import wave

import numpy as np


SLICE_SAMPLE_RATE = 32_000
_SLICE_SPAN_RE = re.compile(r"_(\d+)_(\d+)\.[A-Za-z0-9]+$")


@dataclass(frozen=True, slots=True)
class WavAcoustics:
    duration_seconds: float
    sample_rate: int
    rms_dbfs: float
    peak: float
    clip_ratio: float
    voiced_ratio: float
    edge_rms_dbfs: float


def audio_duration_from_span(path: Path) -> float | None:
    """Estimate duration in seconds from GPT-SoVITS slicer span suffix `_<start>_<end>.wav`."""
    match = _SLICE_SPAN_RE.search(path.name)
    if match is None:
        return None
    start = int(match.group(1))
    end = int(match.group(2))
    if end <= start:
        return None
    return (end - start) / SLICE_SAMPLE_RATE


def _pcm_bytes_to_float32(raw: bytes, sampwidth: int, channels: int) -> np.ndarray | None:
    if not raw or channels <= 0:
        return None
    if sampwidth == 1:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sampwidth == 2:
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sampwidth == 3:
        usable = (len(raw) // 3) * 3
        if usable == 0:
            return None
        triplets = np.frombuffer(raw[:usable], dtype=np.uint8).reshape(-1, 3)
        signed = (
            triplets[:, 0].astype(np.int32)
            | (triplets[:, 1].astype(np.int32) << 8)
            | (triplets[:, 2].astype(np.int8).astype(np.int32) << 16)
        )
        samples = signed.astype(np.float32) / 8388608.0
    elif sampwidth == 4:
        samples = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        return None

    if channels > 1:
        usable = (samples.size // channels) * channels
        if usable == 0:
            return None
        samples = samples[:usable].reshape(-1, channels).mean(axis=1)
    return samples


def analyze_wav_acoustics(path: Path) -> WavAcoustics | None:
    """Measure duration, loudness, clipping, active speech ratio, and edge silence."""
    if path.suffix.lower() != ".wav" or not path.is_file():
        return None
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            sampwidth = handle.getsampwidth()
            rate = handle.getframerate()
            nframes = handle.getnframes()
            if rate <= 0 or nframes <= 0:
                return None
            raw = handle.readframes(nframes)
    except (OSError, wave.Error, EOFError):
        return None

    mono = _pcm_bytes_to_float32(raw, sampwidth, channels)
    if mono is None or mono.size == 0:
        return None

    duration = float(mono.size) / float(rate)
    abs_samples = np.abs(mono)
    peak = float(np.max(abs_samples))
    rms = float(np.sqrt(np.mean(np.square(mono, dtype=np.float64))))
    rms_dbfs = 20.0 * math.log10(max(rms, 1e-7))
    clip_ratio = float(np.mean(abs_samples >= 0.995))

    frame_len = max(1, int(rate * 0.02))
    usable = (mono.size // frame_len) * frame_len
    if usable >= frame_len:
        framed = mono[:usable].reshape(-1, frame_len)
        frame_rms = np.sqrt(np.mean(np.square(framed, dtype=np.float64), axis=1))
        frame_dbfs = 20.0 * np.log10(np.maximum(frame_rms, 1e-7))
        threshold_db = max(-45.0, rms_dbfs - 18.0)
        voiced_ratio = float(np.mean(frame_dbfs > threshold_db))
    else:
        voiced_ratio = 1.0 if rms_dbfs > -42.0 else 0.0

    edge_len = min(max(1, int(rate * 0.04)), mono.size // 4 or 1)
    head_rms = float(np.sqrt(np.mean(np.square(mono[:edge_len], dtype=np.float64))))
    tail_rms = float(np.sqrt(np.mean(np.square(mono[-edge_len:], dtype=np.float64))))
    edge_rms_dbfs = 20.0 * math.log10(max(head_rms, tail_rms, 1e-7))

    return WavAcoustics(
        duration_seconds=duration,
        sample_rate=rate,
        rms_dbfs=rms_dbfs,
        peak=peak,
        clip_ratio=clip_ratio,
        voiced_ratio=voiced_ratio,
        edge_rms_dbfs=edge_rms_dbfs,
    )
