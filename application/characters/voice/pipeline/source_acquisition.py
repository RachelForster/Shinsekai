"""Unified voice source acquisition (SSRF-hardened direct audio URLs, local files, or video compilations)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
import ipaddress
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import urlparse

import requests

from application.characters.voice.pipeline.bilibili_search import (
    DEFAULT_HTTP_UA,
    search_bilibili_voice_urls,
)
from application.characters.voice.pipeline.wav_acoustics import analyze_wav_acoustics
from application.characters.voice.pipeline.yt_dlp_extractor import (
    DIRECT_AUDIO_SUFFIXES,
    ensure_yt_dlp_binary,
    extract_audio_with_yt_dlp,
)
from application.media.resource_paths import MediaResourcePaths
from sdk.path_utils import safe_existing_path


_URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


@dataclass(frozen=True, slots=True)
class AcquiredVoiceSources:
    files: tuple[Path, ...]
    resolved_sources: tuple[str, ...]
    needs_uvr_by_default: bool
    yt_dlp_used: bool


def validate_external_http_url(url: str) -> str:
    """Validate an external HTTP(S) URL and reject loopback, private, link-local, or reserved IPs."""
    cleaned = str(url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"不支持的音频/视频链接协议：{cleaned}")
    host = parsed.hostname.strip().lower()
    if host in {"localhost", "0.0.0.0"} or host.endswith(".localhost"):
        raise ValueError(f"禁止访问本地回环地址：{cleaned}")
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return cleaned
    if (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    ):
        raise ValueError(f"禁止访问内网或保留地址：{cleaned}")
    return cleaned


def _has_uri_scheme(value: str) -> bool:
    return bool(_URI_SCHEME_RE.match(str(value or "").strip()))


def _looks_like_direct_audio_url(url: str) -> bool:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    return suffix in DIRECT_AUDIO_SUFFIXES


def _download_direct_audio_url(
    url: str,
    dest_dir: Path,
    index: int,
    *,
    check_cancelled: Callable[[], None],
) -> Path | None:
    """Attempt direct HTTP audio download; return None if response is an HTML webpage."""
    validated = validate_external_http_url(url)
    parsed = urlparse(validated)
    suffix = Path(parsed.path).suffix.lower()

    session = requests.Session()
    session.headers.update({"User-Agent": DEFAULT_HTTP_UA})
    try:
        with session.get(validated, stream=True, timeout=45, allow_redirects=True) as resp:
            if resp.url:
                validate_external_http_url(resp.url)
            resp.raise_for_status()
            content_type = str(resp.headers.get("Content-Type") or "").lower()
            is_audio_ct = content_type.startswith("audio/") or content_type in {
                "application/ogg",
                "application/octet-stream",
            }
            if "text/html" in content_type:
                return None
            if suffix not in DIRECT_AUDIO_SUFFIXES and not is_audio_ct:
                return None

            ext = suffix if suffix in DIRECT_AUDIO_SUFFIXES else ".wav"
            target = dest_dir / f"direct_{index:03d}{ext}"
            total_bytes = 0
            max_bytes = 250 * 1024 * 1024
            with open(target, "wb") as out_f:
                for chunk in resp.iter_content(chunk_size=128 * 1024):
                    check_cancelled()
                    if not chunk:
                        continue
                    total_bytes += len(chunk)
                    if total_bytes > max_bytes:
                        raise ValueError(f"音频文件超过大小上限（250MB）：{validated}")
                    out_f.write(chunk)
            if total_bytes <= 44:
                target.unlink(missing_ok=True)
                raise ValueError(f"下载到的音频文件为空：{validated}")
            return target
    finally:
        session.close()


def _default_run_subprocess(label: str, command: Sequence[str]) -> None:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    completed = subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"{label}失败：{detail[:600] or completed.returncode}")


def acquire_voice_sources(
    *,
    sources: Sequence[str],
    query: str = "",
    raw_dir: Path,
    project_root: Path,
    gsv_root: Path | None,
    allowed_roots: Iterable[Path] = (),
    max_download_seconds: int = 180,
    on_log: Callable[[str], None] | None = None,
    check_cancelled: Callable[[], None] | None = None,
    run_subprocess: Callable[[str, Sequence[str]], None] | None = None,
) -> AcquiredVoiceSources:
    """Download or stage character voice audio files into `raw_dir`."""
    log = on_log or (lambda _msg: None)
    check = check_cancelled or (lambda: None)
    raw_dir.mkdir(parents=True, exist_ok=True)

    normalized_sources = [str(item or "").strip() for item in sources if str(item or "").strip()]
    cleaned_query = str(query or "").strip()

    if not normalized_sources and not cleaned_query:
        raise ValueError("请提供角色语音来源链接/路径（sources）或搜索关键词（query）。")

    if not normalized_sources and cleaned_query:
        log(f"正在检索角色语音来源：{cleaned_query}")
        found_urls = search_bilibili_voice_urls(cleaned_query, max_results=1)
        if found_urls:
            log(f"已匹配到语音视频：{found_urls[0]}")
            normalized_sources = found_urls
        else:
            search_kw = (
                cleaned_query
                if any(k in cleaned_query for k in ("语音", "台词"))
                else f"{cleaned_query} 语音合集"
            )
            normalized_sources = [f"bilisearch1:{search_kw}"]

    roots = MediaResourcePaths(
        project_root, file_access_roots=tuple(allowed_roots)
    ).file_access_roots
    runner = run_subprocess or _default_run_subprocess

    collected_files: list[Path] = []
    resolved_labels: list[str] = []
    needs_uvr = False
    yt_dlp_used = False
    yt_dlp_bin: Path | None = None

    for idx, spec in enumerate(normalized_sources, start=1):
        check()
        if spec.startswith(("bilisearch", "ytsearch")):
            if yt_dlp_bin is None:
                yt_dlp_bin = ensure_yt_dlp_binary(
                    project_root, gsv_root, on_log=log, check_cancelled=check
                )
            extracted = extract_audio_with_yt_dlp(
                yt_dlp_bin,
                spec,
                raw_dir,
                idx,
                gsv_root=gsv_root,
                max_download_seconds=max_download_seconds,
                run_subprocess=runner,
            )
            collected_files.extend(extracted)
            resolved_labels.append(spec)
            needs_uvr = True
            yt_dlp_used = True
            continue

        if _has_uri_scheme(spec):
            validated = validate_external_http_url(spec)
            if _looks_like_direct_audio_url(validated):
                direct_file = _download_direct_audio_url(
                    validated, raw_dir, idx, check_cancelled=check
                )
                if direct_file is not None:
                    collected_files.append(direct_file)
                    resolved_labels.append(validated)
                    continue

            if yt_dlp_bin is None:
                yt_dlp_bin = ensure_yt_dlp_binary(
                    project_root, gsv_root, on_log=log, check_cancelled=check
                )
            extracted = extract_audio_with_yt_dlp(
                yt_dlp_bin,
                validated,
                raw_dir,
                idx,
                gsv_root=gsv_root,
                max_download_seconds=max_download_seconds,
                run_subprocess=runner,
            )
            collected_files.extend(extracted)
            resolved_labels.append(validated)
            needs_uvr = True
            yt_dlp_used = True
            continue

        local_path = safe_existing_path(spec, roots=roots, field="voiceSource")
        if local_path.is_dir():
            local_audio = sorted(
                (
                    p
                    for p in local_path.iterdir()
                    if p.is_file() and p.suffix.lower() in DIRECT_AUDIO_SUFFIXES and p.stat().st_size > 44
                ),
                key=lambda item: item.name,
            )
            if not local_audio:
                raise ValueError(f"本地音频目录中未找到有效音频文件：{local_path}")
            for sub_idx, src_file in enumerate(local_audio, start=1):
                dst = raw_dir / f"local_{idx:02d}_{sub_idx:03d}{src_file.suffix.lower()}"
                shutil.copy2(src_file, dst)
                collected_files.append(dst)
                acoustics = analyze_wav_acoustics(dst)
                if acoustics is None or acoustics.duration_seconds > 25.0:
                    needs_uvr = True
            resolved_labels.append(str(local_path))
        elif local_path.is_file():
            if local_path.suffix.lower() not in DIRECT_AUDIO_SUFFIXES:
                raise ValueError(f"不支持的本地音频格式：{local_path.name}")
            dst = raw_dir / f"local_{idx:03d}{local_path.suffix.lower()}"
            shutil.copy2(local_path, dst)
            collected_files.append(dst)
            acoustics = analyze_wav_acoustics(dst)
            if acoustics is None or acoustics.duration_seconds > 25.0:
                needs_uvr = True
            resolved_labels.append(str(local_path))
        else:
            raise FileNotFoundError(f"找不到本地音频来源：{spec}")

    if not collected_files:
        raise RuntimeError("未能获取到任何可用的角色语音文件。")

    return AcquiredVoiceSources(
        files=tuple(collected_files),
        resolved_sources=tuple(resolved_labels),
        needs_uvr_by_default=needs_uvr,
        yt_dlp_used=yt_dlp_used,
    )
