"""Standalone yt-dlp binary provisioning (SHA-256 verified) and bounded WAV audio extraction."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import hashlib
import os
from pathlib import Path
import platform
import re
import shutil

import requests

from application.characters.voice.pipeline.bilibili_search import DEFAULT_HTTP_UA


DIRECT_AUDIO_SUFFIXES = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
    ".wma",
}

YT_DLP_RELEASE_BASE = "https://github.com/yt-dlp/yt-dlp/releases/latest/download"


def _yt_dlp_asset_filename() -> str:
    if os.name == "nt":
        return "yt-dlp.exe"
    sys_name = platform.system().lower()
    if sys_name == "darwin":
        return "yt-dlp_macos"
    return "yt-dlp_linux"


def _parse_sha256sums(text: str, asset_name: str) -> str:
    for raw_line in str(text or "").splitlines():
        parts = raw_line.strip().split()
        if len(parts) >= 2 and parts[1].lstrip("*") == asset_name:
            digest = parts[0].strip().lower()
            if re.fullmatch(r"[0-9a-f]{64}", digest):
                return digest
    return ""


def ensure_yt_dlp_binary(
    project_root: Path,
    gsv_root: Path | None = None,
    *,
    on_log: Callable[[str], None] | None = None,
    check_cancelled: Callable[[], None] | None = None,
) -> Path:
    """Locate an existing yt-dlp binary or download + SHA-256 verify the standalone release."""
    exe_name = "yt-dlp.exe" if os.name == "nt" else "yt-dlp"
    managed_path = project_root.resolve() / "data" / "tools" / "yt-dlp" / exe_name

    candidates: list[Path] = [managed_path]
    if gsv_root is not None:
        candidates.append(gsv_root / exe_name)
        candidates.append(gsv_root / "runtime" / exe_name)
    for candidate in candidates:
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate

    found_in_path = shutil.which("yt-dlp")
    if found_in_path:
        return Path(found_in_path)

    asset_name = _yt_dlp_asset_filename()
    log = on_log or (lambda _msg: None)
    check = check_cancelled or (lambda: None)
    check()
    log(f"未检测到 yt-dlp，正在下载官方独立可执行文件 {asset_name} 并进行 SHA-256 校验...")

    managed_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = managed_path.with_suffix(managed_path.suffix + ".part")
    sums_url = f"{YT_DLP_RELEASE_BASE}/SHA2-256SUMS"
    bin_url = f"{YT_DLP_RELEASE_BASE}/{asset_name}"

    session = requests.Session()
    session.headers.update({"User-Agent": DEFAULT_HTTP_UA})
    try:
        sums_resp = session.get(sums_url, timeout=30)
        sums_resp.raise_for_status()
        expected_sha256 = _parse_sha256sums(sums_resp.text, asset_name)
        if not expected_sha256:
            raise RuntimeError(f"无法从官方 SHA2-256SUMS 解析 {asset_name} 的校验值。")

        hasher = hashlib.sha256()
        with session.get(bin_url, stream=True, timeout=60) as bin_resp:
            bin_resp.raise_for_status()
            with open(part_path, "wb") as out_f:
                for chunk in bin_resp.iter_content(chunk_size=256 * 1024):
                    check()
                    if not chunk:
                        continue
                    out_f.write(chunk)
                    hasher.update(chunk)

        actual_sha256 = hasher.hexdigest().lower()
        if actual_sha256 != expected_sha256:
            part_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"yt-dlp SHA-256 校验不匹配（预期 {expected_sha256[:12]}...，实际 {actual_sha256[:12]}...）。"
            )
        if os.name != "nt":
            part_path.chmod(0o755)
        part_path.replace(managed_path)
        log(f"yt-dlp 已准备就绪：{managed_path}")
        return managed_path
    except BaseException:
        part_path.unlink(missing_ok=True)
        raise
    finally:
        session.close()


def _format_mmss(seconds: int) -> str:
    clamped = max(15, int(seconds))
    hours, rem = divmod(clamped, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _find_ffmpeg_dir(gsv_root: Path | None) -> Path | None:
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    if gsv_root is not None:
        for folder in (gsv_root, gsv_root / "runtime"):
            if (folder / exe).is_file():
                return folder
    which = shutil.which("ffmpeg")
    return Path(which).parent if which else None


def extract_audio_with_yt_dlp(
    yt_dlp_bin: Path,
    target_spec: str,
    dest_dir: Path,
    index: int,
    *,
    gsv_root: Path | None,
    max_download_seconds: int,
    run_subprocess: Callable[[str, Sequence[str]], None],
) -> list[Path]:
    """Run yt-dlp to extract WAV audio up to `max_download_seconds`, with Edge cookie fallback on Bilibili."""
    out_template = str(dest_dir / f"video_{index:03d}_%(id)s.%(ext)s")
    base_cmd = [
        str(yt_dlp_bin),
        "--no-playlist",
        "--no-warnings",
        "--newline",
        "-f",
        "ba/best",
        "-x",
        "--audio-format",
        "wav",
        "-o",
        out_template,
    ]
    ffmpeg_dir = _find_ffmpeg_dir(gsv_root)
    if ffmpeg_dir is not None:
        base_cmd.extend(["--ffmpeg-location", str(ffmpeg_dir)])
    if max_download_seconds > 0:
        base_cmd.extend(["--download-sections", f"*00:00-{_format_mmss(max_download_seconds)}"])

    before = {path.name for path in dest_dir.iterdir() if path.is_file()}
    cmd = [*base_cmd, "--", target_spec]
    try:
        run_subprocess("yt-dlp 音轨提取", cmd)
    except RuntimeError as first_err:
        # Retry once with Edge browser cookies if Bilibili blocks anonymous extraction (e.g. HTTP 412).
        if "bilibili.com" in target_spec.lower() or "b23.tv" in target_spec.lower():
            retry_cmd = [*base_cmd, "--cookies-from-browser", "edge", "--", target_spec]
            try:
                run_subprocess("yt-dlp 音轨提取（浏览器访客重试）", retry_cmd)
            except RuntimeError:
                raise first_err from None
        else:
            raise

    produced = sorted(
        (
            path
            for path in dest_dir.iterdir()
            if path.is_file()
            and path.name not in before
            and path.suffix.lower() in DIRECT_AUDIO_SUFFIXES
            and path.stat().st_size > 44
        ),
        key=lambda item: item.name,
    )
    if not produced:
        raise RuntimeError(f"yt-dlp 未能从 {target_spec} 提取出有效音频文件。")
    return produced
