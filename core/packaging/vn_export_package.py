"""Self-contained static HTML/CSS/JS Visual Novel package exporter."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
from typing import Any, Literal
import uuid

from core.packaging.vn_export_media import (
    content_hash_bytes,
    content_hash_file,
    find_ffmpeg,
    is_static_sprite,
    is_video_asset,
    transcode_audio_to_mp3,
)
from core.packaging.zip_io import safe_package_name, write_directory_zip

_TEMPLATE_DIR = Path(__file__).resolve().parent / "vn_player_assets"
_MAX_INDEX_HTML_BYTES = 1024 * 1024
_SAFE_CSS_VAR_RE = re.compile(r"^--vn-[a-z0-9-]+$")
_FORBIDDEN_CSS_VAL_RE = re.compile(r"[{};<>]|url\s*\(", re.IGNORECASE)
_LANG_TAG_MAP = {"zh_CN": "zh-CN", "en": "en", "ja": "ja"}


@dataclass(frozen=True, slots=True)
class VnRawEntry:
    """Single timeline entry supplied by application/chat before asset relocation."""

    id: str
    role: str
    speaker: str
    text: str
    options: tuple[str, ...] = ()
    selected_index: int | None = None
    background: str = ""
    bgm: str = ""
    cg: str = ""
    ambient_effects: tuple[dict[str, Any], ...] = ()
    sprites: tuple[dict[str, Any], ...] = ()
    stats: tuple[dict[str, Any], ...] = ()
    player_portrait: dict[str, Any] | None = None
    voice_paths: tuple[Path, ...] = ()
    voice_volume: float = 1.0
    created_at_ms: int | None = None


@dataclass(frozen=True, slots=True)
class VnExportOptions:
    """Configuration for generating an offline & Bilibili-Toy-ready VN bundle."""

    title: str
    subtitle: str
    locale: str
    story_id: str
    output_format: Literal["zip", "directory"]
    output_path: Path
    include_voices: bool = True
    transcode_mp3: bool = True
    include_bgm: bool = True
    include_ambient: bool = True
    theme_vars: Mapping[str, str] = field(default_factory=dict)
    ui_labels: Mapping[str, str] = field(default_factory=dict)
    ffmpeg_search_roots: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class VnExportResult:
    """Metadata returned after packaging a playable Visual Novel."""

    output_path: Path
    format: Literal["zip", "directory"]
    entry_count: int
    asset_count: int
    voice_count: int
    transcoded_voice_count: int
    skipped_non_static_sprites: int
    total_bytes: int
    index_html_bytes: int
    warnings: tuple[str, ...]


class _AssetCollector:
    """Copy and deduplicate media assets into ``stage_dir/assets/<category>/``."""

    def __init__(self, stage_dir: Path, resolve_asset: Callable[[str], Path | None]) -> None:
        self.stage_dir = stage_dir
        self.resolve_asset = resolve_asset
        self.seen: dict[tuple[str, str], str] = {}
        self.missing_count = 0

    def stage_path(self, category: str, source: Path) -> str | None:
        if not source.is_file():
            return None
        safe_cat = safe_package_name(category, "asset category")
        digest = content_hash_file(source, 12)
        cache_key = (safe_cat, digest)
        cached = self.seen.get(cache_key)
        if cached is not None:
            return cached
        suffix = source.suffix.lower() or ".bin"
        rel_posix = f"assets/{safe_cat}/{digest}{suffix}"
        target = self.stage_dir / rel_posix
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        rel_url = f"./{rel_posix}"
        self.seen[cache_key] = rel_url
        return rel_url

    def stage_ref(self, category: str, raw_ref: str) -> str:
        ref = str(raw_ref or "").strip()
        if not ref:
            return ""
        resolved = self.resolve_asset(ref)
        if resolved is None or not resolved.is_file():
            self.missing_count += 1
            return ""
        return self.stage_path(category, resolved) or ""


def _render_theme_style_block(theme_vars: Mapping[str, str]) -> str:
    lines: list[str] = []
    for raw_key, raw_val in theme_vars.items():
        key = str(raw_key or "").strip()
        val = str(raw_val or "").strip()
        if not _SAFE_CSS_VAR_RE.match(key) or not val:
            continue
        if _FORBIDDEN_CSS_VAL_RE.search(val):
            continue
        lines.append(f"  {key}: {val};")
    if not lines:
        return ""
    return "<style>\n:root {\n" + "\n".join(lines) + "\n}\n</style>"


def _serialize_story_data_js(payload: Mapping[str, Any]) -> bytes:
    dumped = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    escaped = (
        dumped.replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    return f"window.__SHINSEKAI_VN__={escaped};\n".encode("utf-8")


_PUBLISH_LOCKS_GUARD = threading.Lock()
_PUBLISH_LOCKS: dict[str, threading.Lock] = {}


def _publish_lock_for(target: Path) -> threading.Lock:
    key = os.path.normcase(os.path.realpath(os.fspath(target)))
    with _PUBLISH_LOCKS_GUARD:
        lock = _PUBLISH_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _PUBLISH_LOCKS[key] = lock
        return lock


def _publish_directory(stage_dir: Path, target_dir: Path) -> None:
    target = Path(target_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _publish_lock_for(target):
        if not target.exists():
            orphaned = sorted(
                (p for p in target.parent.glob(f".{target.name}.bak.*") if p.is_dir()),
                key=lambda p: p.stat().st_mtime_ns,
                reverse=True,
            )
            if orphaned:
                os.replace(orphaned[0], target)

        tmp_dir = Path(tempfile.mkdtemp(prefix=f".{target.name}.tmp.", dir=target.parent))
        backup_dir: Path | None = None
        try:
            shutil.copytree(stage_dir, tmp_dir, dirs_exist_ok=True)
            if target.exists():
                backup_dir = target.parent / f".{target.name}.bak.{uuid.uuid4().hex[:12]}"
                os.replace(target, backup_dir)
            os.replace(tmp_dir, target)
            if backup_dir is not None and backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)
            for stale in target.parent.glob(f".{target.name}.bak.*"):
                if stale.is_dir():
                    shutil.rmtree(stale, ignore_errors=True)
        except Exception:
            if backup_dir is not None and backup_dir.exists() and not target.exists():
                os.replace(backup_dir, target)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise


def _stage_voices(
    collector: _AssetCollector,
    voice_paths: Sequence[Path],
    *,
    ffmpeg_bin: str | None,
    transcode_mp3: bool,
    transcode_dir: Path,
) -> tuple[list[str], int, bool]:
    urls: list[str] = []
    transcoded = 0
    ffmpeg_missing = False
    for index, source in enumerate(voice_paths):
        if not source.is_file():
            collector.missing_count += 1
            continue
        chosen = source
        if transcode_mp3 and source.suffix.lower() != ".mp3":
            if ffmpeg_bin:
                mp3_target = transcode_dir / f"{content_hash_file(source, 12)}-{index}.mp3"
                if transcode_audio_to_mp3(ffmpeg_bin, source, mp3_target):
                    chosen = mp3_target
                    transcoded += 1
            else:
                ffmpeg_missing = True
        staged = collector.stage_path("voice", chosen)
        if staged:
            urls.append(staged)
    return urls, transcoded, ffmpeg_missing


def export_playable_vn_package(
    entries: Sequence[VnRawEntry],
    options: VnExportOptions,
    *,
    resolve_asset: Callable[[str], Path | None],
) -> VnExportResult:
    """Compile normalized VN timeline entries and assets into a playable HTML/CSS/JS bundle."""
    if not entries:
        raise ValueError("Cannot export an empty VN timeline")

    ffmpeg_bin = (
        find_ffmpeg(options.ffmpeg_search_roots)
        if options.include_voices and options.transcode_mp3
        else None
    )

    with tempfile.TemporaryDirectory(prefix="shinsekai-vn-") as tmp_root:
        root_path = Path(tmp_root)
        stage_dir = root_path / "bundle"
        transcode_dir = root_path / "transcoded"
        stage_dir.mkdir(parents=True, exist_ok=True)
        collector = _AssetCollector(stage_dir, resolve_asset)

        serialized_entries: list[dict[str, Any]] = []
        skipped_non_static = 0
        voice_entry_count = 0
        transcoded_voice_count = 0
        ffmpeg_missing_flagged = False
        cover_url = ""

        for entry in entries:
            bg_url = collector.stage_ref("bg", entry.background)
            cg_url = collector.stage_ref("cg", entry.cg)
            bgm_url = collector.stage_ref("bgm", entry.bgm) if options.include_bgm else ""

            if not cover_url and cg_url:
                cover_url = cg_url
            elif not cover_url and bg_url:
                cover_url = bg_url

            ambient_list: list[dict[str, Any]] = []
            if options.include_ambient:
                for item in entry.ambient_effects:
                    vis_url = collector.stage_ref("ambient", str(item.get("url") or ""))
                    if not vis_url:
                        continue
                    aud_raw = str(item.get("audioUrl") or "")
                    aud_url = collector.stage_ref("ambient", aud_raw) if aud_raw else ""
                    ambient_list.append(
                        {
                            "key": str(item.get("key") or vis_url),
                            "url": vis_url,
                            "audioUrl": aud_url,
                            "layer": "front" if item.get("layer") == "front" else "back",
                        }
                    )

            sprite_list: list[dict[str, Any]] = []
            for sp in entry.sprites:
                if not is_static_sprite(sp):
                    skipped_non_static += 1
                    continue
                sp_url = collector.stage_ref(
                    "sprites",
                    str(sp.get("path") or sp.get("url") or ""),
                )
                if not sp_url:
                    continue
                sprite_list.append(
                    {
                        "id": str(sp.get("id") or sp.get("characterName") or sp.get("label") or ""),
                        "characterName": str(sp.get("characterName") or sp.get("label") or ""),
                        "label": str(sp.get("label") or sp.get("characterName") or ""),
                        "url": sp_url,
                        "slot": sp.get("slot"),
                        "x": float(sp.get("x") or 0),
                        "y": float(sp.get("y") or 0),
                        "scale": float(sp.get("scale") or 1.0),
                    }
                )

            portrait_out: dict[str, Any] | None = None
            if entry.player_portrait and entry.player_portrait.get("url"):
                p_url = collector.stage_ref("sprites", str(entry.player_portrait["url"]))
                if p_url:
                    portrait_out = {
                        "characterName": str(entry.player_portrait.get("characterName") or ""),
                        "url": p_url,
                        "crop": entry.player_portrait.get("crop"),
                    }

            voice_urls: list[str] = []
            if options.include_voices and entry.voice_paths:
                voice_urls, seg_transcoded, saw_no_ffmpeg = _stage_voices(
                    collector,
                    entry.voice_paths,
                    ffmpeg_bin=ffmpeg_bin,
                    transcode_mp3=options.transcode_mp3,
                    transcode_dir=transcode_dir,
                )
                transcoded_voice_count += seg_transcoded
                ffmpeg_missing_flagged = ffmpeg_missing_flagged or saw_no_ffmpeg
                if voice_urls:
                    voice_entry_count += 1

            serialized_entries.append(
                {
                    "id": entry.id,
                    "role": entry.role,
                    "speaker": entry.speaker,
                    "text": entry.text,
                    "options": list(entry.options),
                    "selectedIndex": entry.selected_index,
                    "background": bg_url,
                    "bgm": bgm_url,
                    "cg": cg_url,
                    "ambientEffects": ambient_list,
                    "sprites": sprite_list,
                    "stats": [dict(st) for st in entry.stats],
                    "playerPortrait": portrait_out,
                    "voices": voice_urls,
                    "voiceVolume": min(1.0, max(0.0, float(entry.voice_volume))),
                    "createdAtMs": entry.created_at_ms,
                }
            )

        story_payload = {
            "schema": 1,
            "storyId": options.story_id,
            "locale": options.locale,
            "meta": {
                "title": options.title,
                "subtitle": options.subtitle,
                "coverUrl": cover_url,
                "coverIsVideo": is_video_asset(cover_url),
                "entryCount": len(serialized_entries),
                "voiceCount": voice_entry_count,
                "exportedAt": datetime.now(timezone.utc).isoformat(),
            },
            "uiLabels": dict(options.ui_labels),
            "entries": serialized_entries,
        }

        style_bytes = (_TEMPLATE_DIR / "style.css").read_bytes()
        player_bytes = (_TEMPLATE_DIR / "player.js").read_bytes()
        data_bytes = _serialize_story_data_js(story_payload)

        style_file = f"style.{content_hash_bytes(style_bytes, 12)}.css"
        player_file = f"player.{content_hash_bytes(player_bytes, 12)}.js"
        data_file = f"story-data.{content_hash_bytes(data_bytes, 12)}.js"

        (stage_dir / style_file).write_bytes(style_bytes)
        (stage_dir / player_file).write_bytes(player_bytes)
        (stage_dir / data_file).write_bytes(data_bytes)

        html_tpl = (_TEMPLATE_DIR / "index.html").read_text(encoding="utf-8")
        index_text = (
            html_tpl.replace("__LANG__", _LANG_TAG_MAP.get(options.locale, "zh-CN"))
            .replace("__TITLE__", html.escape(options.title or "Shinsekai VN", quote=True))
            .replace("__STYLE_FILE__", style_file)
            .replace("__DATA_FILE__", data_file)
            .replace("__PLAYER_FILE__", player_file)
            .replace("__THEME_STYLE_BLOCK__", _render_theme_style_block(options.theme_vars))
        )
        index_bytes = index_text.encode("utf-8")
        if len(index_bytes) > _MAX_INDEX_HTML_BYTES:
            raise ValueError(
                f"Entry index.html size ({len(index_bytes)} bytes) exceeds 1MB Toy limit"
            )
        (stage_dir / "index.html").write_bytes(index_bytes)

        staged_files = [p for p in stage_dir.rglob("*") if p.is_file()]
        uncompressed_total = sum(p.stat().st_size for p in staged_files)

        if options.output_format == "zip":
            out_path = write_directory_zip(stage_dir, options.output_path)
            total_bytes = out_path.stat().st_size
        elif options.output_format == "directory":
            out_path = Path(options.output_path)
            _publish_directory(stage_dir, out_path)
            total_bytes = uncompressed_total
        else:
            raise ValueError(f"Unsupported output_format: {options.output_format!r}")

        warnings: list[str] = []
        if ffmpeg_missing_flagged:
            warnings.append("ffmpeg_unavailable")
        if skipped_non_static > 0:
            warnings.append("skipped_non_static_sprites")
        if collector.missing_count > 0:
            warnings.append("missing_assets_skipped")

        return VnExportResult(
            output_path=out_path,
            format=options.output_format,
            entry_count=len(serialized_entries),
            asset_count=len(collector.seen),
            voice_count=voice_entry_count,
            transcoded_voice_count=transcoded_voice_count,
            skipped_non_static_sprites=skipped_non_static,
            total_bytes=total_bytes,
            index_html_bytes=len(index_bytes),
            warnings=tuple(warnings),
        )


__all__ = [
    "VnExportOptions",
    "VnExportResult",
    "VnRawEntry",
    "export_playable_vn_package",
]
