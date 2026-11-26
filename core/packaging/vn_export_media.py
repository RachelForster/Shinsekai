"""Media inspection, hashing, and optional FFmpeg transcoding for VN exports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit

_VIDEO_EXTENSIONS = frozenset({".m4v", ".mov", ".mp4", ".webm"})
_FFMPEG_BIN_NAME = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"


def content_hash_bytes(data: bytes, length: int = 12) -> str:
    """Return a short lowercase SHA-256 hex digest for content-hashed filenames."""
    return hashlib.sha256(data).hexdigest()[: max(8, int(length))]


def content_hash_file(path: Path, length: int = 12) -> str:
    """Stream-hash a file without loading large media assets into RAM."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 512), b""):
            digest.update(chunk)
    return digest.hexdigest()[: max(8, int(length))]


def _clean_url_path(path_or_url: str) -> str:
    raw = str(path_or_url or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    return (parsed.path or raw).lower()


def is_video_asset(path_or_url: str) -> bool:
    """Return True when a path or URL ends with a supported HTML5 video suffix."""
    cleaned = _clean_url_path(path_or_url)
    return any(cleaned.endswith(ext) for ext in _VIDEO_EXTENSIONS)


def is_static_sprite(sprite: Mapping[str, Any]) -> bool:
    """Allow static image and video sprites; skip Live2D/MMD and model JSON states."""
    avatar_type = str(sprite.get("avatarType") or "").strip().lower()
    if avatar_type and avatar_type != "static":
        return False
    model_url = str(sprite.get("modelUrl") or "").strip()
    if model_url:
        return False
    raw_path = str(sprite.get("path") or sprite.get("url") or "").strip()
    if not raw_path:
        return False
    parsed = urlsplit(raw_path)
    if parsed.path.startswith("/api/avatar/file"):
        return False
    if _clean_url_path(raw_path).endswith(".json"):
        return False
    return True


def find_ffmpeg(search_roots: Sequence[Path] = ()) -> str | None:
    """Locate a local ffmpeg executable from candidate roots or system PATH."""
    for root in search_roots:
        base = Path(root)
        for candidate in (
            base / _FFMPEG_BIN_NAME,
            base / "runtime" / _FFMPEG_BIN_NAME,
            base / "bin" / _FFMPEG_BIN_NAME,
        ):
            if candidate.is_file():
                return str(candidate)
    which = shutil.which("ffmpeg")
    return which if which else None


def transcode_audio_to_mp3(
    ffmpeg_bin: str,
    source: Path,
    target: Path,
    *,
    bitrate: str = "96k",
    timeout_seconds: float = 30.0,
) -> bool:
    """Transcode an audio clip to MP3 cleanly, removing partial files on failure."""
    target.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, object] = {
        "capture_output": True,
        "text": True,
        "timeout": timeout_seconds,
        "check": False,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    cmd = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-vn",
        "-codec:a",
        "libmp3lame",
        "-b:a",
        bitrate,
        str(target),
    ]
    try:
        completed = subprocess.run(cmd, **kwargs)  # type: ignore[arg-type]
    except (OSError, subprocess.SubprocessError):
        target.unlink(missing_ok=True)
        return False
    if completed.returncode != 0 or not target.is_file() or target.stat().st_size <= 0:
        target.unlink(missing_ok=True)
        return False
    return True


__all__ = [
    "content_hash_bytes",
    "content_hash_file",
    "find_ffmpeg",
    "is_static_sprite",
    "is_video_asset",
    "transcode_audio_to_mp3",
]
