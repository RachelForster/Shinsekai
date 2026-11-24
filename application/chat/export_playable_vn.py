"""Export chat history excerpts or conversations into playable HTML/CSS/JS VN packages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from pathlib import Path
import re
from typing import Any, Literal

from application.chat.composition import _chat_history
from application.chat.conversation_library import _records as list_conversation_records
from application.chat.history.paths import is_unc_history_path, resolve_history_path_for_project
from application.chat.history.replay import digest, replay_user_text, split_text
from application.chat.history.replay_store import ReplayStore
from application.chat.host.history import _serialize_history_entries_from_messages
from application.chat.host.projection import _chat_user_display_name
from application.chat.presentation.user_display import sanitize_user_display_name
from application.chat.vn_export_metadata import extract_vn_theme_vars, player_ui_labels
from application.chat.vn_export_resolvers import (
    extract_dialog_sprite_hints,
    make_vn_asset_resolver,
    merge_stage_sprites,
    resolve_entry_voices,
)
from application.chat.voice_archive import VoiceArchive
from config.config_manager import character_name_key
from core.chat_history.storage import (
    chat_history_session_dir,
    legacy_active_history_branch,
    read_active_chat_history,
)
from core.chat_history.text import DEFAULT_USER_DISPLAY_NAME
from core.messaging.dialog_tokens import is_option_history_name
from core.packaging.vn_export_package import (
    VnExportOptions,
    VnRawEntry,
    export_playable_vn_package,
)
from core.paths import app_root, project_root as runtime_project_root, source_root
from core.sprite.selection import sprite_entry_path
from sdk.exception.types import AppError
from sdk.lang import normalize_lang
from sdk.path_utils import reject_control_chars, safe_project_path

_HIDDEN_SYSTEM_SPEAKERS = frozenset({"scene", "场景", "bgm"})
_TRANSPARENT_BACKGROUNDS = frozenset({"", "透明场景", "透明背景"})


@dataclass(frozen=True, slots=True)
class PlayableVnExportRequest:
    """User-supplied configuration for exporting a playable Visual Novel."""

    conversation_id: str = ""
    start_entry_id: str = ""
    end_entry_id: str = ""
    title: str = ""
    subtitle: str = ""
    output_format: Literal["zip", "directory"] = "zip"
    output_dir: str = ""
    include_voices: bool = True
    transcode_mp3: bool = True
    include_bgm: bool = True
    include_ambient: bool = True
    user_display_name: str = ""


@dataclass(frozen=True, slots=True)
class PlayableVnExportOutcome:
    """Transport-independent result returned by ``export_playable_vn``."""

    path: str
    is_project_relative: bool
    format: Literal["zip", "directory"]
    entry_count: int
    asset_count: int
    voice_count: int
    transcoded_voice_count: int
    skipped_non_static_sprites: int
    total_bytes: int
    index_html_bytes: int
    warnings: tuple[str, ...]


def _project_root(state: Any) -> Path:
    raw = str(getattr(state, "project_root_dir", "") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve(strict=False)
    return runtime_project_root()


def _system_settings_values(state: Any) -> tuple[str, str, str]:
    stores = getattr(state, "stores", None)
    if stores is not None and getattr(stores, "system_settings", None) is not None:
        cfg = stores.system_settings.get()
        return (
            normalize_lang(getattr(cfg, "ui_language", "zh_CN")),
            str(getattr(cfg, "chat_ui_theme_id", "") or ""),
            str(getattr(cfg, "theme_color", "") or ""),
        )
    sys_cfg = getattr(getattr(getattr(state, "config_manager", None), "config", None), "system_config", None)
    return (
        normalize_lang(getattr(sys_cfg, "ui_language", "zh_CN")),
        str(getattr(sys_cfg, "chat_ui_theme_id", "") or ""),
        str(getattr(sys_cfg, "theme_color", "") or ""),
    )


def _resolve_output_path(
    project_root: Path,
    title: str,
    output_format: Literal["zip", "directory"],
    output_dir: str,
) -> Path:
    ascii_slug = re.sub(r"[^A-Za-z0-9_-]+", "-", title).strip("-").lower()[:40]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder_slug = f"{ascii_slug or 'shinsekai-vn'}-{stamp}"

    raw_dir = str(output_dir or "").strip()
    if raw_dir:
        cleaned = reject_control_chars(raw_dir, field="outputDir")
        cand = Path(cleaned)
        base = cand.expanduser().resolve(strict=False) if cand.is_absolute() else safe_project_path(cleaned, root=project_root)
        if output_format == "zip":
            if base.suffix.lower() == ".zip" and not base.is_dir():
                return base
            return base / f"{folder_slug}.zip"
        if base.exists() and base.is_dir():
            return base / folder_slug
        return base

    default_dir = project_root / "output" / "vn_exports"
    return default_dir / (f"{folder_slug}.zip" if output_format == "zip" else folder_slug)


def _slug_story_id(history_path: Path, start_id: str, end_id: str) -> str:
    raw = f"{chat_history_session_dir(history_path)}|{start_id}|{end_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _merge_live_voice_ids(state: Any, history_path: Path, entries: list[dict[str, Any]]) -> None:
    active_raw = str((getattr(state, "chat_session", {}) or {}).get("historyPath") or "").strip()
    if not active_raw or is_unc_history_path(active_raw):
        return
    try:
        active_path = resolve_history_path_for_project(state, active_raw)
    except (PermissionError, ValueError, OSError):
        return
    if (
        chat_history_session_dir(active_path).resolve(strict=False)
        != chat_history_session_dir(history_path).resolve(strict=False)
    ):
        return
    live_voices = {
        str(item.get("dialogId") or ""): str(item.get("voiceId") or "")
        for item in (_chat_history(state) or [])
        if isinstance(item, dict) and item.get("dialogId") and item.get("voiceId")
    }
    if not live_voices:
        return
    for item in entries:
        did = str(item.get("dialogId") or "")
        if did and not item.get("voiceId") and did in live_voices:
            item["voiceId"] = live_voices[did]


def _load_session_entries(
    state: Any,
    request: PlayableVnExportRequest,
) -> tuple[Path, list[dict[str, Any]], list[Any], str, str, dict[str, Any] | None]:
    conv_id = str(request.conversation_id or "").strip()
    raw_override = str(request.user_display_name or "").strip()
    override_user = (
        DEFAULT_USER_DISPLAY_NAME
        if raw_override == DEFAULT_USER_DISPLAY_NAME
        else sanitize_user_display_name(raw_override)
    )
    if conv_id:
        record = list_conversation_records(state).get(conv_id)
        if record is None or not record.get("historyPath"):
            raise AppError("vn_export_conversation_not_found", http_status=404)
        history_path = resolve_history_path_for_project(state, record["historyPath"])
        if is_unc_history_path(history_path):
            raise AppError("vn_export_empty_history", http_status=400)
        messages = read_active_chat_history(history_path)
        user_name = override_user or _chat_user_display_name(state)
        entries = _serialize_history_entries_from_messages(messages, user_name)
        _merge_live_voice_ids(state, history_path, entries)
        launch = record.get("launch") if isinstance(record.get("launch"), dict) else {}
        default_title = str(record.get("title") or launch.get("templateName") or "").strip()
        return history_path, entries, messages, default_title, user_name, record

    history_raw = str((getattr(state, "chat_session", {}) or {}).get("historyPath") or "").strip()
    if not history_raw:
        raise AppError("vn_export_empty_history", http_status=400)
    history_path = resolve_history_path_for_project(state, history_raw)
    if is_unc_history_path(history_path):
        raise AppError("vn_export_empty_history", http_status=400)
    messages = read_active_chat_history(history_path)
    entries = _chat_history(state)
    user_name = override_user or _chat_user_display_name(state)
    default_title = str((getattr(state, "chat_session", {}) or {}).get("conversationTitle") or "").strip()
    return history_path, entries, messages, default_title, user_name, None


def _seed_initial_background(state: Any, record: dict[str, Any] | None, resolve_asset: Any) -> str:
    launch = record.get("launch") if isinstance(record, dict) and isinstance(record.get("launch"), dict) else {}
    bg_name = str(
        launch.get("backgroundName")
        or (getattr(state, "chat_session", {}) or {}).get("backgroundName")
        or ""
    ).strip()
    if bg_name in _TRANSPARENT_BACKGROUNDS:
        return ""
    config_manager = getattr(state, "config_manager", None)
    get_bg = getattr(config_manager, "get_background_by_name", None)
    if not callable(get_bg):
        return ""
    bg_cfg = get_bg(bg_name)
    for sp in getattr(bg_cfg, "sprites", None) or []:
        raw_path = sprite_entry_path(sp)
        if raw_path and resolve_asset(raw_path) is not None:
            return raw_path
    return ""


def _resolve_visible_range(
    parsed_raw: list[tuple[dict[str, Any], str, str, bool]],
    visible_indices: list[int],
    request: PlayableVnExportRequest,
) -> tuple[int, int]:
    visible_start = 0
    visible_end = len(visible_indices) - 1
    if request.start_entry_id.strip():
        target = request.start_entry_id.strip()
        matches = [i for i, raw_idx in enumerate(visible_indices) if parsed_raw[raw_idx][0].get("id") == target]
        if not matches:
            raise AppError("vn_export_invalid_range", http_status=400)
        visible_start = matches[0]
    if request.end_entry_id.strip():
        target = request.end_entry_id.strip()
        matches = [i for i, raw_idx in enumerate(visible_indices) if parsed_raw[raw_idx][0].get("id") == target]
        if not matches:
            raise AppError("vn_export_invalid_range", http_status=400)
        visible_end = matches[0]
    if visible_start > visible_end:
        raise AppError("vn_export_invalid_range", http_status=400)
    return visible_indices[visible_start], visible_indices[visible_end]


def export_playable_vn(state: Any, request: PlayableVnExportRequest) -> PlayableVnExportOutcome:
    """Compile a chat session or selected range into an offline & Toy-ready VN bundle."""
    if request.output_format not in {"zip", "directory"}:
        raise AppError("vn_export_invalid_output", http_status=400)

    history_path, raw_entries, raw_messages, default_title, user_name, record = _load_session_entries(state, request)
    parsed_raw: list[tuple[dict[str, Any], str, str, bool]] = []
    visible_indices: list[int] = []
    for raw in raw_entries:
        speaker, body = split_text(raw)
        hidden = raw.get("role") == "system" and speaker.casefold() in _HIDDEN_SYSTEM_SPEAKERS
        parsed_raw.append((raw, speaker, body, hidden))
        if not hidden:
            visible_indices.append(len(parsed_raw) - 1)

    if not visible_indices:
        raise AppError("vn_export_empty_history", http_status=400)

    raw_start_idx, raw_end_idx = _resolve_visible_range(parsed_raw, visible_indices, request)
    proj_root = _project_root(state)
    resolve_asset = make_vn_asset_resolver(state, proj_root)

    store = ReplayStore(history_path)
    archive = VoiceArchive(history_path)
    branch = legacy_active_history_branch(history_path)
    users = [m for m in raw_messages if isinstance(m, dict) and m.get("role") == "user"]
    hints_by_id, hints_by_text = extract_dialog_sprite_hints(raw_messages)
    config_manager = getattr(state, "config_manager", None)
    get_char = getattr(config_manager, "get_character_by_name", None)

    chain = digest([str(history_path), branch])
    rolling_frame: dict[str, Any] = {
        "backgroundPath": _seed_initial_background(state, record, resolve_asset),
        "bgmPath": "",
        "cgPath": "",
        "ambientEffects": [],
        "sprites": [],
        "stats": [],
        "playerPortrait": None,
    }
    vn_entries: list[VnRawEntry] = []

    for idx in range(raw_end_idx + 1):
        raw, speaker, body, hidden = parsed_raw[idx]
        chain = digest([chain, raw.get("role"), raw.get("text"), raw.get("dialogId")])
        if hidden:
            if speaker.casefold() in {"scene", "场景"}:
                rolling_frame["sprites"] = []
            continue

        role = str(raw.get("role") or "assistant")
        if role == "user":
            body = replay_user_text(raw, body, users)
            speaker = user_name or speaker
        dialog_id = str(raw.get("dialogId") or "")
        frame = store.read(dialog_id, "frame.json") if dialog_id else None
        if frame is not None:
            rolling_frame = {
                "backgroundPath": str(frame.get("backgroundPath") or ""),
                "bgmPath": str(frame.get("bgmPath") or ""),
                "cgPath": str(frame.get("cgPath") or ""),
                "ambientEffects": list(frame.get("ambientEffects") or []),
                "sprites": list(frame.get("sprites") or []),
                "stats": list(frame.get("stats") or []),
                "playerPortrait": frame.get("playerPortrait"),
            }

        speaker_key = character_name_key(speaker.strip()) if speaker.strip() else ""
        sprite_hint = hints_by_id.get(dialog_id) or hints_by_text.get((speaker_key, body))
        merged_sprites, matched_sprite = merge_stage_sprites(
            list(rolling_frame["sprites"]),
            state=state,
            speaker=speaker,
            role=role,
            cg_path=str(rolling_frame["cgPath"] or ""),
            frame_present=(frame is not None),
            sprite_hint=sprite_hint,
            resolve_asset=resolve_asset,
        )
        rolling_frame["sprites"] = list(merged_sprites)
        if idx < raw_start_idx:
            continue

        options: tuple[str, ...] = ()
        selected_index: int | None = None
        if role == "options" or is_option_history_name(speaker):
            choices = [c.strip() for c in body.split("/") if c.strip()]
            options = tuple(choices)
            for f_raw, f_speaker, f_body, f_hidden in parsed_raw[idx + 1 :]:
                if f_hidden:
                    continue
                if f_raw.get("role") == "options" or is_option_history_name(f_speaker):
                    break
                if f_raw.get("role") == "user":
                    picked = replay_user_text(f_raw, f_body, users)
                    selected_index = choices.index(picked) if choices.count(picked) == 1 else None
                    break

        voice_paths = resolve_entry_voices(
            archive,
            store,
            project_root=proj_root,
            raw_entry=raw,
            dialog_id=dialog_id,
            chain_key=chain,
            role=role,
            matched_sprite=matched_sprite,
            resolve_asset=resolve_asset,
        )
        character = get_char(speaker) if (callable(get_char) and role == "assistant") else None
        voice_volume = min(1.0, max(0.0, float(getattr(character, "speech_volume", 1.0) if character else 1.0)))

        vn_entries.append(
            VnRawEntry(
                id=str(raw.get("id") or f"entry-{idx}"),
                role=role,
                speaker=speaker,
                text=body,
                options=options,
                selected_index=selected_index,
                background=str(rolling_frame["backgroundPath"] or ""),
                bgm=str(rolling_frame["bgmPath"] or ""),
                cg=str(rolling_frame["cgPath"] or ""),
                ambient_effects=tuple(dict(item) for item in rolling_frame["ambientEffects"] if isinstance(item, dict)),
                sprites=tuple(dict(sp) for sp in merged_sprites if isinstance(sp, dict)),
                stats=tuple(dict(st) for st in rolling_frame["stats"] if isinstance(st, dict)),
                player_portrait=dict(rolling_frame["playerPortrait"]) if isinstance(rolling_frame["playerPortrait"], dict) else None,
                voice_paths=tuple(voice_paths),
                voice_volume=voice_volume,
                created_at_ms=int(raw["createdAt"]) if isinstance(raw.get("createdAt"), (int, float)) else None,
            )
        )

    locale, theme_id, accent = _system_settings_values(state)
    final_title = request.title.strip() or default_title or "Shinsekai Visual Novel"
    try:
        output_path = _resolve_output_path(proj_root, final_title, request.output_format, request.output_dir)
    except (PermissionError, ValueError) as exc:
        raise AppError("vn_export_invalid_output", fallback_message=str(exc), http_status=400) from exc

    result = export_playable_vn_package(
        vn_entries,
        VnExportOptions(
            title=final_title,
            subtitle=request.subtitle.strip(),
            locale=locale,
            story_id=_slug_story_id(history_path, vn_entries[0].id, vn_entries[-1].id),
            output_format=request.output_format,
            output_path=output_path,
            include_voices=request.include_voices,
            transcode_mp3=request.transcode_mp3,
            include_bgm=request.include_bgm,
            include_ambient=request.include_ambient,
            theme_vars=extract_vn_theme_vars(proj_root, theme_id, accent),
            ui_labels=player_ui_labels(locale),
            ffmpeg_search_roots=(proj_root, app_root(), source_root()),
        ),
        resolve_asset=resolve_asset,
    )

    resolved_out = result.output_path.resolve(strict=False)
    resolved_proj = proj_root.resolve(strict=False)
    is_rel = resolved_out.is_relative_to(resolved_proj)
    display_path = resolved_out.relative_to(resolved_proj).as_posix() if is_rel else resolved_out.as_posix()

    return PlayableVnExportOutcome(
        path=display_path,
        is_project_relative=is_rel,
        format=result.format,
        entry_count=result.entry_count,
        asset_count=result.asset_count,
        voice_count=result.voice_count,
        transcoded_voice_count=result.transcoded_voice_count,
        skipped_non_static_sprites=result.skipped_non_static_sprites,
        total_bytes=result.total_bytes,
        index_html_bytes=result.index_html_bytes,
        warnings=result.warnings,
    )


__all__ = [
    "PlayableVnExportOutcome",
    "PlayableVnExportRequest",
    "export_playable_vn",
]
