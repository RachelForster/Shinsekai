"""Protocol encoding, endpoint normalization, and local server discovery for Fish Audio S2 Pro."""

from __future__ import annotations

from collections.abc import Mapping
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import struct
import sys
from typing import Any
from urllib.parse import urlparse, urlunparse

from core.storage.layout import StorageLayout

DEFAULT_FISH_AUDIO_URL = "https://api.fish.audio"
DEFAULT_FISH_AUDIO_MODEL = "s2-pro"
DEFAULT_FISH_AUDIO_DECODER_CONFIG = "modded_dac_vq"
FISH_AUDIO_CLOUD_HOSTS = frozenset({"api.fish.audio"})


def _encode_msgpack_into(value: Any, buf: bytearray) -> None:
    if value is None:
        buf.append(0xC0)
        return
    if isinstance(value, bool):
        buf.append(0xC3 if value else 0xC2)
        return
    if isinstance(value, int):
        if 0 <= value <= 0x7F:
            buf.append(value)
        elif -32 <= value < 0:
            buf.extend(struct.pack("b", value))
        elif 0 <= value <= 0xFF:
            buf.extend((0xCC, value))
        elif 0 <= value <= 0xFFFF:
            buf.append(0xCD)
            buf.extend(struct.pack(">H", value))
        elif 0 <= value <= 0xFFFFFFFF:
            buf.append(0xCE)
            buf.extend(struct.pack(">I", value))
        elif 0 <= value <= 0xFFFFFFFFFFFFFFFF:
            buf.append(0xCF)
            buf.extend(struct.pack(">Q", value))
        elif -128 <= value < -32:
            buf.append(0xD0)
            buf.extend(struct.pack(">b", value))
        elif -32768 <= value < -128:
            buf.append(0xD1)
            buf.extend(struct.pack(">h", value))
        elif -2147483648 <= value < -32768:
            buf.append(0xD2)
            buf.extend(struct.pack(">i", value))
        elif -9223372036854775808 <= value < -2147483648:
            buf.append(0xD3)
            buf.extend(struct.pack(">q", value))
        else:
            raise OverflowError(f"Integer out of range for MessagePack: {value}")
        return
    if isinstance(value, float):
        buf.append(0xCB)
        buf.extend(struct.pack(">d", value))
        return
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        length = len(encoded)
        if length <= 31:
            buf.append(0xA0 | length)
        elif length <= 0xFF:
            buf.extend((0xD9, length))
        elif length <= 0xFFFF:
            buf.append(0xDA)
            buf.extend(struct.pack(">H", length))
        elif length <= 0xFFFFFFFF:
            buf.append(0xDB)
            buf.extend(struct.pack(">I", length))
        else:
            raise OverflowError("String too long for MessagePack")
        buf.extend(encoded)
        return
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        length = len(raw)
        if length <= 0xFF:
            buf.extend((0xC4, length))
        elif length <= 0xFFFF:
            buf.append(0xC5)
            buf.extend(struct.pack(">H", length))
        elif length <= 0xFFFFFFFF:
            buf.append(0xC6)
            buf.extend(struct.pack(">I", length))
        else:
            raise OverflowError("Bytes object too long for MessagePack")
        buf.extend(raw)
        return
    if isinstance(value, (list, tuple)):
        length = len(value)
        if length <= 15:
            buf.append(0x90 | length)
        elif length <= 0xFFFF:
            buf.append(0xDC)
            buf.extend(struct.pack(">H", length))
        elif length <= 0xFFFFFFFF:
            buf.append(0xDD)
            buf.extend(struct.pack(">I", length))
        else:
            raise OverflowError("Sequence too long for MessagePack")
        for item in value:
            _encode_msgpack_into(item, buf)
        return
    if isinstance(value, Mapping):
        length = len(value)
        if length <= 15:
            buf.append(0x80 | length)
        elif length <= 0xFFFF:
            buf.append(0xDE)
            buf.extend(struct.pack(">H", length))
        elif length <= 0xFFFFFFFF:
            buf.append(0xDF)
            buf.extend(struct.pack(">I", length))
        else:
            raise OverflowError("Mapping too long for MessagePack")
        for key, item in value.items():
            _encode_msgpack_into(key, buf)
            _encode_msgpack_into(item, buf)
        return
    raise TypeError(f"Unsupported type for MessagePack encoding: {type(value).__name__}")


def pack_msgpack(value: Any) -> bytes:
    """Encode a Python value into MessagePack binary format using only stdlib."""
    buf = bytearray()
    _encode_msgpack_into(value, buf)
    return bytes(buf)


def resolve_fish_audio_endpoints(server_url: str | None) -> tuple[str, str, str]:
    """Return ``(base_url_with_slash, tts_endpoint, health_endpoint)``."""
    raw = str(server_url or "").strip() or DEFAULT_FISH_AUDIO_URL
    parsed = urlparse(raw)
    clean_path = parsed.path.rstrip("/")
    if clean_path.endswith("/v1/tts"):
        clean_path = clean_path[: -len("/v1/tts")]
    elif clean_path.endswith("/v1"):
        clean_path = clean_path[: -len("/v1")]
    base_url = urlunparse((parsed.scheme, parsed.netloc, clean_path, "", "", "")).rstrip("/")
    return f"{base_url}/", f"{base_url}/v1/tts", f"{base_url}/v1/health"


def parse_character_reference_ids(raw: str | Mapping[str, Any] | None) -> dict[str, str]:
    """Parse character->reference_id mappings from dict, JSON string, or ``Name=ID`` lines."""
    if isinstance(raw, Mapping):
        return {
            name: ref_id
            for raw_name, raw_ref in raw.items()
            if (name := str(raw_name or "").strip()) and (ref_id := str(raw_ref or "").strip())
        }
    text = str(raw or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if isinstance(loaded, Mapping):
            return parse_character_reference_ids(loaded)
        return {}
    parsed: dict[str, str] = {}
    normalized = text.replace(";", "\n").replace(",", "\n")
    for line in normalized.splitlines():
        entry = line.strip()
        if not entry:
            continue
        sep = "=" if "=" in entry else (":" if ":" in entry else "")
        if not sep:
            continue
        name, ref_id = entry.split(sep, 1)
        clean_name = name.strip()
        clean_ref = ref_id.strip()
        if clean_name and clean_ref:
            parsed[clean_name] = clean_ref
    return parsed


def _looks_like_checkpoint_dir(directory: Path) -> bool:
    if not directory.is_dir():
        return False
    if (directory / "config.json").is_file():
        return True
    return any(directory.glob("*.safetensors")) or any(directory.glob("*.pth"))


def _resolve_python_executable(explicit: str, work_dir: Path) -> str:
    clean = str(explicit or "").strip()
    if clean:
        path = Path(clean).expanduser()
        if path.is_file():
            return str(path.resolve())
        if path.is_dir():
            for candidate in (
                path / "Scripts" / "python.exe",
                path / "bin" / "python",
                path / "python.exe",
                path / "python",
            ):
                if candidate.is_file():
                    return str(candidate.resolve())
        which_hit = shutil.which(clean)
        if which_hit:
            return str(Path(which_hit).resolve())
        raise FileNotFoundError(f"Fish Speech python executable not found: {explicit}")

    for candidate in (
        work_dir / ".venv" / "Scripts" / "python.exe",
        work_dir / ".venv" / "bin" / "python",
        work_dir / "venv" / "Scripts" / "python.exe",
        work_dir / "venv" / "bin" / "python",
        work_dir / "runtime" / "python.exe",
        work_dir / "runtime" / "bin" / "python",
    ):
        if candidate.is_file():
            return str(candidate.resolve())
    return sys.executable


def find_fish_speech_server_script(work_dir: Path) -> Path | None:
    """Locate ``tools/api_server.py`` or ``api_server.py`` under ``work_dir``."""
    for candidate in (work_dir / "tools" / "api_server.py", work_dir / "api_server.py"):
        if candidate.is_file():
            return candidate.resolve()
    return None


def resolve_local_fish_speech_launch(
    *,
    work_path: str | Path | None = None,
    llama_checkpoint_path: str = "",
    decoder_checkpoint_path: str = "",
    python_path: str = "",
    project_root: str | os.PathLike[str] | None = None,
) -> tuple[str, Path, Path, Path | None, Path]:
    """Resolve ``(python_exe, api_script, llama_ckpt, decoder_ckpt, work_dir)``."""
    layout = StorageLayout.from_env(project_root)
    raw_work = str(work_path or "").strip()
    work_dir = (
        Path(raw_work).expanduser().resolve()
        if raw_work
        else layout.model_dir("fish-audio-s2-pro").resolve()
    )
    if not work_dir.is_dir():
        raise FileNotFoundError(f"Fish Speech directory not found: {work_dir}")

    api_script = find_fish_speech_server_script(work_dir)
    if api_script is None:
        raise FileNotFoundError(
            f"Fish Speech tools/api_server.py not found under {work_dir}."
        )

    python_exe = _resolve_python_executable(python_path, work_dir)

    raw_llama = str(llama_checkpoint_path or "").strip()
    if raw_llama:
        llama_ckpt = Path(raw_llama).expanduser().resolve()
        if not llama_ckpt.is_dir():
            raise FileNotFoundError(
                f"Fish Audio S2 Pro checkpoint directory not found: {llama_ckpt}"
            )
    else:
        candidates = (
            work_dir / "checkpoints" / "s2-pro",
            layout.model_dir("fish-audio-s2-pro"),
        )
        found_ckpt = next(
            (cand.resolve() for cand in candidates if _looks_like_checkpoint_dir(cand)),
            None,
        )
        if found_ckpt is None or not found_ckpt.is_dir():
            raise FileNotFoundError(
                f"Fish Audio S2 Pro weights not found (checked {candidates[0]} and {candidates[1]})."
            )
        llama_ckpt = found_ckpt

    raw_decoder = str(decoder_checkpoint_path or "").strip()
    decoder_ckpt: Path | None = None
    if raw_decoder:
        decoder_path = Path(raw_decoder).expanduser().resolve()
        if not decoder_path.is_file():
            raise FileNotFoundError(
                f"Fish Audio S2 Pro decoder checkpoint not found: {decoder_path}"
            )
        decoder_ckpt = decoder_path
    else:
        for candidate in (
            llama_ckpt / "codec.pth",
            work_dir / "checkpoints" / "s2-pro" / "codec.pth",
        ):
            if candidate.is_file():
                decoder_ckpt = candidate.resolve()
                break

    return python_exe, api_script, llama_ckpt, decoder_ckpt, work_dir


def build_fish_speech_server_cmd(
    *,
    python_exe: str,
    api_script: Path,
    server_url: str,
    llama_ckpt: Path,
    decoder_ckpt: Path | None,
    decoder_config_name: str,
    compile_model: bool = False,
    half_precision: bool = False,
    api_key: str = "",
    extra_args: str = "",
) -> list[str]:
    """Assemble the subprocess command line for ``tools/api_server.py``."""
    parsed = urlparse(server_url)
    host = (parsed.hostname or "").strip().strip("[]").lower()
    port = int(parsed.port or 8080)
    if host == "0.0.0.0":
        listen_addr = f"0.0.0.0:{port}"
    elif ":" in host:
        listen_addr = f"[{host}]:{port}"
    else:
        listen_addr = f"127.0.0.1:{port}"
    cmd = [
        python_exe,
        str(api_script),
        "--listen",
        listen_addr,
        "--llama-checkpoint-path",
        str(llama_ckpt),
    ]
    if decoder_ckpt is not None:
        cmd.extend(["--decoder-checkpoint-path", str(decoder_ckpt)])
        if decoder_config_name:
            cmd.extend(["--decoder-config-name", decoder_config_name])
    if compile_model:
        cmd.append("--compile")
    if half_precision:
        cmd.append("--half")
    if api_key:
        cmd.extend(["--api-key", api_key])
    if extra_args:
        cmd.extend(shlex.split(extra_args, posix=(os.name != "nt")))
    return cmd


def _schema_option(
    field_type: str,
    label: str,
    label_key: str,
    default: Any,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "type": field_type,
        "label": label,
        "labelKey": label_key,
        "default": default,
        **extra,
    }


def build_fish_audio_config_schema() -> dict[str, dict[str, Any]]:
    """Return configurable Fish Audio S2 Pro adapter fields for API settings."""
    p = "ops.api.tts.fishAudio.extra"
    return {
        "base_url": _schema_option(
            "str", "Fish Audio API / Local Server URL", f"{p}.baseUrl", DEFAULT_FISH_AUDIO_URL
        ),
        "api_key": _schema_option(
            "str", "Fish Audio API Key", f"{p}.apiKey", "", secret=True
        ),
        "model": _schema_option(
            "str", "Fish Audio Model (e.g. s2-pro)", f"{p}.model", DEFAULT_FISH_AUDIO_MODEL
        ),
        "reference_id": _schema_option(
            "str",
            "Default Reference Voice ID (leave blank for character audio cloning)",
            f"{p}.referenceId",
            "",
        ),
        "character_reference_ids": _schema_option(
            "str",
            "Per-character Reference IDs (JSON or Name=ID lines, optional)",
            f"{p}.characterReferenceIds",
            "",
        ),
        "enable_inline_tags": _schema_option(
            "bool",
            "Enable Inline Voice Tags (e.g. [laugh], [soft whisper])",
            f"{p}.enableInlineTags",
            True,
        ),
        "latency": _schema_option(
            "str", "Latency Mode", f"{p}.latency", "normal", choices=["normal", "balanced"]
        ),
        "chunk_length": _schema_option(
            "int", "Chunk Length", f"{p}.chunkLength", 200, min=100, max=300, step=10
        ),
        "temperature": _schema_option(
            "float", "Temperature", f"{p}.temperature", 0.7, min=0.1, max=1.0, step=0.05
        ),
        "top_p": _schema_option(
            "float", "Top-P", f"{p}.topP", 0.7, min=0.1, max=1.0, step=0.05
        ),
        "normalize": _schema_option("bool", "Normalize Text", f"{p}.normalize", True),
        "request_timeout": _schema_option(
            "float",
            "Request Timeout (seconds)",
            f"{p}.requestTimeout",
            120.0,
            min=5.0,
            max=600.0,
            step=5.0,
        ),
        "fish_speech_dir": _schema_option(
            "str",
            "Local fish-speech Directory (optional, for localhost auto-start)",
            f"{p}.fishSpeechDir",
            "",
        ),
        "llama_checkpoint_path": _schema_option(
            "str", "Local S2 Pro Checkpoint Dir (optional)", f"{p}.llamaCheckpointPath", ""
        ),
        "decoder_checkpoint_path": _schema_option(
            "str", "Local Codec Checkpoint (optional)", f"{p}.decoderCheckpointPath", ""
        ),
        "python_path": _schema_option(
            "str", "Local Python Executable (optional)", f"{p}.pythonPath", ""
        ),
        "extra_args": _schema_option(
            "str", "Extra Local api_server.py Arguments", f"{p}.extraArgs", ""
        ),
    }


def normalize_prosody_speed(raw_speed: Any) -> float | None:
    """Return a clamped speech speed multiplier when it differs materially from 1.0."""
    if raw_speed is None or raw_speed == "":
        return None
    try:
        speed = float(raw_speed)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(speed):
        return None
    clamped = max(0.5, min(2.0, speed))
    return round(clamped, 3) if abs(clamped - 1.0) > 1e-3 else None
