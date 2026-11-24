"""Asset, sprite, and voice resolvers for playable Visual Novel export."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from application.chat.history.replay_store import ReplayStore
from application.chat.voice_archive import VoiceArchive
from config.character_assets import get_character_assets, get_character_avatar_type
from config.config_manager import character_name_key
from core.chat_history.identity import CHAT_TURN_ID, DialogIdentities
from core.chat_history.text import parse_assistant_dialog_content
from core.messaging.dialog_tokens import match_scene_name
from core.packaging.vn_export_media import is_static_sprite
from core.paths import app_root, resource_path, source_root
from core.sprite.selection import sprite_entry_path
from sdk.messages import LLMDialogMessage
from sdk.path_utils import reject_control_chars, safe_project_path

_LOCAL_BRIDGE_HOSTS = frozenset({"", "127.0.0.1", "localhost", "::1"})
_SPRITE_ID_RE = re.compile(r"^[0-9]{1,9}$")
_VOICE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PLAYABLE_SPRITE_VOICE_TYPES = frozenset({"preset", "fallback"})


def normalize_sprite_index(raw_id: Any) -> str:
    """Parse 1-based sprite IDs including zero-padded numbers such as ``01``."""
    text = str(raw_id or "").strip()
    if _SPRITE_ID_RE.fullmatch(text):
        num = int(text)
        if num >= 1:
            return str(num)
    return ""


def _collect_roots_from_value(node: Any, roots: set[Path]) -> None:
    if hasattr(node, "model_dump"):
        _collect_roots_from_value(node.model_dump(mode="python"), roots)
    elif isinstance(node, dict):
        for val in node.values():
            _collect_roots_from_value(val, roots)
    elif isinstance(node, (list, tuple, set, frozenset)):
        for val in node:
            _collect_roots_from_value(val, roots)
    elif isinstance(node, (str, os.PathLike)):
        text = os.fspath(node).strip()
        if text and Path(text).is_absolute():
            resolved = Path(text).expanduser().resolve(strict=False)
            roots.add(resolved if resolved.is_dir() else resolved.parent)


def _iter_approved_external_roots(state: Any) -> tuple[Path, ...]:
    roots: set[Path] = set()
    config = getattr(getattr(state, "config_manager", None), "config", None)
    if config is not None:
        _collect_roots_from_value(config, roots)
    chat_stream = getattr(state, "chat_stream", None)
    approved_fn = getattr(chat_stream, "approved_external_media_paths", None)
    if callable(approved_fn):
        try:
            _collect_roots_from_value(list(approved_fn()), roots)
        except Exception:
            pass
    return tuple(roots)


def _relative_media_candidates(clean_str: str) -> list[str]:
    rel_candidates = [clean_str]
    slash_path = clean_str.replace("\\", "/")
    if slash_path != clean_str:
        rel_candidates.append(slash_path)
    parts = [part for part in slash_path.split("/") if part and part != "."]
    if len(parts) >= 5 and parts[0] == "data":
        family, prefix = parts[1], parts[2]
        if parts[3] == family and parts[4] == prefix:
            rel_candidates.append("/".join(parts[:3] + parts[5:]))
        if family in {"backgrounds", "bgm", "speech", "sprite", "sprites"}:
            rel_candidates.append("/".join(parts[:3] + [parts[-1]]))
    return list(dict.fromkeys(rel_candidates))


def make_vn_asset_resolver(state: Any, project_root: Path) -> Callable[[str], Path | None]:
    """Resolve relative paths, approved external files, and local bridge media URLs."""
    proj_resolved = project_root.resolve(strict=False)
    cwd_resolved = Path.cwd().resolve(strict=False)
    allowed_roots = tuple(dict.fromkeys((proj_resolved, cwd_resolved, source_root(), app_root())))
    external_roots = _iter_approved_external_roots(state)

    def resolve_asset(raw_url: str) -> Path | None:
        raw = str(raw_url or "").strip()
        if not raw:
            return None
        parsed = urlsplit(raw)
        is_windows_drive = os.name == "nt" and len(parsed.scheme) == 1
        if not is_windows_drive:
            if parsed.scheme in {"data", "blob"}:
                return None
            if parsed.scheme in {"http", "https"}:
                host = (parsed.hostname or "").lower()
                if host not in _LOCAL_BRIDGE_HOSTS:
                    return None
                if parsed.path != "/api/media" and not parsed.path.startswith(("/assets/", "/data/")):
                    return None
            if parsed.path.startswith("/api/avatar/"):
                return None

        candidate_str = raw
        if not is_windows_drive and parsed.path == "/api/media":
            candidate_str = (parse_qs(parsed.query).get("path") or [""])[0].strip()
            if not candidate_str:
                return None
        elif not is_windows_drive and parsed.path.startswith(("/assets/", "/data/")):
            candidate_str = unquote(parsed.path.lstrip("/"))

        try:
            clean_str = reject_control_chars(candidate_str, field="media asset path")
        except (PermissionError, ValueError):
            return None

        cand = Path(clean_str)
        if not cand.is_absolute():
            roots_to_try = (project_root,) if cwd_resolved == proj_resolved else (project_root, cwd_resolved)
            for rel_item in _relative_media_candidates(clean_str):
                for root in roots_to_try:
                    try:
                        candidate = safe_project_path(rel_item, root=root)
                        if candidate.is_file():
                            return candidate
                    except (PermissionError, ValueError):
                        pass
                res = resource_path(rel_item)
                if res.is_file() and any(res.resolve(strict=False).is_relative_to(r) for r in allowed_roots):
                    return res
            return None

        resolved = cand.expanduser().resolve(strict=False)
        if not resolved.is_file():
            return None
        if any(resolved.is_relative_to(r) for r in (*allowed_roots, *external_roots)):
            return resolved
        return None

    return resolve_asset


def extract_dialog_sprite_hints(
    raw_messages: list[Any],
) -> tuple[dict[str, dict[str, str]], dict[tuple[str, str], dict[str, str]]]:
    """Index per-line sprite/effect hints (supporting zero-padded sprite IDs like ``01``)."""
    by_id: dict[str, dict[str, str]] = {}
    by_text: dict[tuple[str, str], dict[str, str] | None] = {}
    active_sprites: dict[str, str] = {}

    for message in raw_messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        identities = DialogIdentities(message.get(CHAT_TURN_ID))
        for item in parse_assistant_dialog_content(message.get("content", "")):
            try:
                dialog = LLMDialogMessage.model_validate(item)
            except (TypeError, ValueError):
                continue
            identity = identities.next(item)
            speaker = dialog.name.strip()
            text = (dialog.text or "").strip()
            if match_scene_name(speaker):
                active_sprites.clear()
                continue
            speaker_key = character_name_key(speaker) if speaker else ""
            explicit_id = normalize_sprite_index(dialog.asset_id)
            if explicit_id and speaker_key:
                active_sprites[speaker_key] = explicit_id
            effective_id = explicit_id or active_sprites.get(speaker_key, "")
            effect = str(dialog.effect or "").strip()
            if effect.upper() == "LEAVE" and speaker_key:
                active_sprites.pop(speaker_key, None)
            if not effective_id and not effect:
                continue
            payload = {"asset_id": effective_id, "effect": effect}
            if identity:
                by_id[identity] = payload
            if speaker_key and text:
                key = (speaker_key, text)
                if key not in by_text:
                    by_text[key] = payload
                elif by_text[key] != payload:
                    by_text[key] = None

    return by_id, {k: v for k, v in by_text.items() if v is not None}


def resolve_character_fallback_sprite(
    state: Any,
    speaker: str,
    sprite_hint: dict[str, str] | None,
    resolve_asset: Callable[[str], Path | None],
) -> tuple[dict[str, Any] | None, Any]:
    """Resolve a character's static sprite directly from config without HTTP URL round-trips."""
    config_manager = getattr(state, "config_manager", None)
    get_char = getattr(config_manager, "get_character_by_name", None)
    if not callable(get_char) or not speaker.strip():
        return None, None
    character = get_char(speaker)
    if character is None:
        return None, None
    assets = get_character_assets(character)
    if not assets.sprites:
        return None, None
    kind = get_character_avatar_type(character)
    char_name = str(getattr(character, "name", "") or speaker)
    if kind != "static":
        return {"avatarType": kind, "label": char_name, "characterName": char_name}, None

    preferred = 0
    norm_id = normalize_sprite_index((sprite_hint or {}).get("asset_id"))
    if norm_id:
        cand = int(norm_id) - 1
        if 0 <= cand < len(assets.sprites):
            preferred = cand

    indices = [preferred, *(i for i in range(len(assets.sprites)) if i != preferred)]
    for idx in indices:
        raw_path = sprite_entry_path(assets.sprites[idx])
        if not raw_path or resolve_asset(raw_path) is None:
            continue
        scale = float(getattr(character, "sprite_scale", 1.0) or 1.0)
        return (
            {
                "id": f"{char_name}-{idx}",
                "characterName": char_name,
                "label": char_name,
                "path": raw_path,
                "avatarType": "static",
                "modelUrl": "",
                "scale": scale,
            },
            assets.sprites[idx],
        )
    return None, None


def _sprite_speaker_key(sprite: dict[str, Any]) -> str:
    raw = str(sprite.get("characterName") or sprite.get("label") or "").strip()
    return character_name_key(raw) if raw else ""


def _match_character_sprite_entry(
    state: Any,
    speaker: str,
    active_sprite: dict[str, Any] | None,
    sprite_hint: dict[str, str] | None,
    resolve_asset: Callable[[str], Path | None],
) -> Any:
    config_manager = getattr(state, "config_manager", None)
    get_char = getattr(config_manager, "get_character_by_name", None)
    if not callable(get_char) or not speaker.strip():
        return None
    character = get_char(speaker)
    if character is None or get_character_avatar_type(character) != "static":
        return None
    assets = get_character_assets(character)
    if not assets.sprites:
        return None
    if active_sprite is not None:
        raw_ref = str(active_sprite.get("path") or active_sprite.get("url") or "").strip()
        target = resolve_asset(raw_ref) if raw_ref else None
        if target is not None:
            target_resolved = target.resolve(strict=False)
            for item in assets.sprites:
                item_path = sprite_entry_path(item)
                resolved = resolve_asset(item_path) if item_path else None
                if resolved is not None and resolved.resolve(strict=False) == target_resolved:
                    return item
    norm_id = normalize_sprite_index((sprite_hint or {}).get("asset_id"))
    if norm_id:
        cand = int(norm_id) - 1
        if 0 <= cand < len(assets.sprites):
            return assets.sprites[cand]
    return None


def merge_stage_sprites(
    current_sprites: list[dict[str, Any]],
    *,
    state: Any,
    speaker: str,
    role: str,
    cg_path: str,
    frame_present: bool,
    sprite_hint: dict[str, str] | None,
    resolve_asset: Callable[[str], Path | None],
) -> tuple[list[dict[str, Any]], Any]:
    """Filter valid sprites, apply LEAVE or fallback resolution, and preserve stage slots."""
    cleaned: list[dict[str, Any]] = []
    for raw_sp in current_sprites:
        if not isinstance(raw_sp, dict):
            continue
        sp = dict(raw_sp)
        if not is_static_sprite(sp):
            cleaned.append(sp)
            continue
        raw_ref = str(sp.get("path") or sp.get("url") or "").strip()
        if raw_ref and resolve_asset(raw_ref) is not None:
            cleaned.append(sp)

    speaker_key = character_name_key(speaker.strip()) if speaker.strip() else ""
    effect = str((sprite_hint or {}).get("effect") or "").strip()
    if role == "assistant" and speaker_key and effect.upper() == "LEAVE":
        _, leaving_sprite = resolve_character_fallback_sprite(state, speaker, sprite_hint, resolve_asset)
        remaining = [sp for sp in cleaned if _sprite_speaker_key(sp) != speaker_key]
        return remaining, leaving_sprite

    matched_sprite: Any = None
    if role == "assistant" and speaker_key and not cg_path:
        existing_idx = next((i for i, sp in enumerate(cleaned) if _sprite_speaker_key(sp) == speaker_key), None)
        explicit_id = normalize_sprite_index((sprite_hint or {}).get("asset_id"))
        if existing_idx is None or (not frame_present and bool(explicit_id)):
            fb_dict, fb_sprite = resolve_character_fallback_sprite(state, speaker, sprite_hint, resolve_asset)
            if fb_dict is not None:
                matched_sprite = fb_sprite
                if existing_idx is not None:
                    old_slot = cleaned[existing_idx].get("slot")
                    if old_slot is not None and fb_dict.get("slot") is None:
                        fb_dict["slot"] = old_slot
                    cleaned[existing_idx] = fb_dict
                else:
                    occupied = {sp.get("slot") for sp in cleaned if isinstance(sp.get("slot"), int)}
                    slot = next((idx for idx in range(3) if idx not in occupied), min(len(cleaned), 2))
                    fb_dict["slot"] = slot
                    if len(cleaned) >= 3:
                        cleaned.pop(0)
                    cleaned.append(fb_dict)

    if matched_sprite is None and role == "assistant" and speaker_key:
        active_sp = next((sp for sp in cleaned if _sprite_speaker_key(sp) == speaker_key), None)
        matched_sprite = _match_character_sprite_entry(state, speaker, active_sp, sprite_hint, resolve_asset)

    return cleaned, matched_sprite


def _read_archive_index(archive: VoiceArchive) -> dict[str, Any]:
    try:
        loaded = json.loads(archive.index_path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, ValueError):
        return {}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 512), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_archive_segment(
    segment: dict[str, Any],
    *,
    audio_dir: Path,
    cache_dirs: tuple[Path, ...],
) -> Path | None:
    audio_root = audio_dir.resolve()
    for field in ("manual", "saved"):
        rel = str(segment.get(field) or "").strip()
        if not rel:
            continue
        candidate = (audio_dir / rel).resolve()
        if candidate.is_relative_to(audio_root) and candidate.is_file() and candidate.stat().st_size > 0:
            return candidate

    raw_cache = str(segment.get("cache") or "").strip()
    if raw_cache:
        cache_path = Path(raw_cache).resolve()
        if cache_path.is_file() and cache_path.stat().st_size > 0 and any(cache_path.is_relative_to(c) for c in cache_dirs):
            expected = str(segment.get("sha256") or "").strip()
            if not expected or _file_sha256(cache_path) == expected:
                return cache_path
    return None


def resolve_entry_voices(
    archive: VoiceArchive,
    store: ReplayStore,
    *,
    project_root: Path,
    raw_entry: dict[str, Any],
    dialog_id: str,
    chain_key: str,
    role: str,
    matched_sprite: Any,
    resolve_asset: Callable[[str], Path | None],
) -> list[Path]:
    """Resolve recorded, cached-replay, or character preset/fallback voices in priority order."""
    voice_id = str(raw_entry.get("voiceId") or "").strip() or (archive.voice_for_dialog(dialog_id) if dialog_id else "")
    index_data: dict[str, Any] | None = None
    if not voice_id and dialog_id:
        index_data = _read_archive_index(archive)
        voice_id = str((index_data.get("dialogs") or {}).get(dialog_id) or "").strip()

    if _VOICE_ID_RE.fullmatch(voice_id):
        if index_data is None:
            index_data = _read_archive_index(archive)
        raw_voice = (index_data.get("voices") or {}).get(voice_id)
        segments = raw_voice.get("segments") if isinstance(raw_voice, dict) else raw_voice
        cache_dirs = tuple(dict.fromkeys(((project_root / "cache" / "audio").resolve(), (Path.cwd() / "cache" / "audio").resolve())))
        paths: list[Path] = []
        if isinstance(segments, list) and segments:
            for idx, segment in enumerate(segments):
                if not isinstance(segment, dict):
                    continue
                candidate: Path | None = None
                try:
                    candidate = archive.source(voice_id, idx)
                except (ValueError, OSError):
                    candidate = None
                if candidate is None or not candidate.is_file() or candidate.stat().st_size <= 0:
                    candidate = _resolve_archive_segment(segment, audio_dir=archive.audio_dir, cache_dirs=cache_dirs)
                if candidate is not None:
                    paths.append(candidate)
        else:
            try:
                seg_count = archive.count(voice_id)
            except (ValueError, OSError):
                seg_count = 0
            for idx in range(seg_count):
                try:
                    candidate = archive.source(voice_id, idx)
                except (ValueError, OSError):
                    continue
                if candidate.is_file() and candidate.stat().st_size > 0:
                    paths.append(candidate)
        if paths:
            return paths

    for key in dict.fromkeys(k for k in (dialog_id, chain_key) if _SHA256_RE.fullmatch(k)):
        saved_voice = store.read(key, "voice.json")
        if saved_voice and _SHA256_RE.fullmatch(str(saved_voice.get("fileKey") or "")):
            candidate = store.path(str(saved_voice["fileKey"]), "wav")
            if candidate.is_file() and candidate.stat().st_size > 0:
                return [candidate]

    if role == "assistant" and matched_sprite is not None:
        voice_type = (
            matched_sprite.get("voice_type")
            if isinstance(matched_sprite, dict)
            else getattr(matched_sprite, "voice_type", None)
        )
        if str(voice_type or "").strip().lower() in _PLAYABLE_SPRITE_VOICE_TYPES:
            voice_path = (
                matched_sprite.get("voice_path")
                if isinstance(matched_sprite, dict)
                else getattr(matched_sprite, "voice_path", None)
            )
            if str(voice_path or "").strip():
                resolved = resolve_asset(str(voice_path).strip())
                if resolved is not None and resolved.is_file() and resolved.stat().st_size > 0:
                    return [resolved]

    return []


__all__ = [
    "extract_dialog_sprite_hints",
    "make_vn_asset_resolver",
    "merge_stage_sprites",
    "normalize_sprite_index",
    "resolve_character_fallback_sprite",
    "resolve_entry_voices",
]
