from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
from pathlib import Path
from threading import RLock
from typing import Any

from config.config_manager import character_name_key
from sdk.file_transactions import (
    atomic_write_text,
    capture_directory_identity,
    ensure_portable_name_available,
    read_text_without_links,
    read_text_snapshot_without_links,
    require_directory_identity,
    snapshot_directory_entries_without_links,
)
from sdk.path_contract import (
    _metadata_is_link_or_reparse_point,
    managed_child_path,
    path_is_link_or_reparse_point,
    project_root as runtime_project_root,
    require_directory_without_links,
    resolve_managed_project_path,
    resolve_project_path,
)
from core.sprite.chat_branch_storage import ACTIVE_HISTORY_FILENAME, BRANCH_TREE_FILENAME
from core.sprite.initial_sprite import initial_sprite_path_for_characters
from ai.llm.template_generator import (
    NoValidCharactersError,
    json_format_reminder,
    resolve_chat_template_characters,
)

from .history_paths import history_reference_value, resolve_history_path_for_project
from sdk.path_references import state_project_root
from sdk.path_utils import safe_filename, safe_project_path
from application.runtime.state import BridgeState

MARK_SCENARIO = "<<<EASYAI_USER_SCENARIO>>>"
MARK_SYSTEM = "<<<EASYAI_SYSTEM_TEMPLATE>>>"
TEMP_SPLIT_META = "_temp_split.json"
RUNTIME_TEMPLATE_HASH_FIELD = "runtimeTemplateSha256"
DEFAULT_EMPTY_SCENARIO = "你扮演一个RPG系统。"

_RUNTIME_TEMPLATE_WRITE_LOCK = RLock()


def _template_dir(state: BridgeState) -> Path:
    path = resolve_managed_project_path(
        state.template_dir_path,
        root=state_project_root(state),
    )
    path.mkdir(parents=True, exist_ok=True)
    return require_directory_without_links(
        path,
        field="template directory",
    )


def _template_id(path: Path) -> str:
    return path.name


def _compose_stored_template(scenario: str, system: str) -> str:
    a = (scenario or "").replace("\r\n", "\n").rstrip()
    b = (system or "").replace("\r\n", "\n").rstrip()
    return f"{MARK_SCENARIO}\n{a}\n{MARK_SYSTEM}\n{b}\n"


def _parse_stored_template(raw: str) -> tuple[str, str]:
    text = (raw or "").replace("\r\n", "\n")
    if MARK_SCENARIO in text and MARK_SYSTEM in text:
        try:
            i = text.index(MARK_SCENARIO) + len(MARK_SCENARIO)
            j = text.index(MARK_SYSTEM, i)
            return text[i:j].strip("\n"), text[j + len(MARK_SYSTEM) :].strip("\n")
        except ValueError:
            pass
    text = text.strip()
    return (text, "") if text else ("", "")


def _compose_for_llm(scenario: str, system: str) -> str:
    a = (scenario or "").strip()
    b = (system or "").strip()
    if a and b:
        return f"{a}\n\n{b}"
    return a or b


def _effective_user_scenario(user_scenario: str) -> str:
    return (user_scenario or "").strip() or DEFAULT_EMPTY_SCENARIO


def _compose_runtime_template(system_template: str, user_scenario: str) -> str:
    parts = [
        (system_template or "").rstrip(),
        _effective_user_scenario(user_scenario),
        json_format_reminder(),
    ]
    return "\n".join(part for part in parts if part) + "\n"


def _normalize_hash_character_names(character_names: Any = None) -> list[str]:
    if not isinstance(character_names, list):
        return []
    names = {str(item).strip() for item in character_names if str(item).strip()}
    return sorted(names)


def _scenario_from_template_like(template: dict[str, Any]) -> str:
    raw_scenario = template.get("scenario")
    if raw_scenario is not None:
        return str(raw_scenario)
    return str(template.get("content") or "")


def _history_id_from_scenario(
    user_scenario: str,
    character_names: Any = None,
) -> str:
    stable = {
        "characters": _normalize_hash_character_names(character_names),
        "scenario": _effective_user_scenario(user_scenario),
    }
    return hashlib.md5(
        json.dumps(stable, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _latest_history_json(history_dir: str, *, project_root: Path | None = None) -> Path | None:
    root = (
        resolve_project_path(".", root=project_root)
        if project_root is not None
        else runtime_project_root()
    )
    path = resolve_managed_project_path(history_dir, root=root)
    if path == root:
        raise PermissionError("chat history directory must not be the project root")
    try:
        path, path_identity, items = snapshot_directory_entries_without_links(
            path,
            field="chat history directory",
        )
    except (FileNotFoundError, NotADirectoryError):
        return None
    candidates: list[tuple[Path, float, os.stat_result]] = []
    reserved_root_files = {ACTIVE_HISTORY_FILENAME, BRANCH_TREE_FILENAME}
    for item, item_metadata in items:
        # Session symlinks make the configured root cease to be the deletion
        # boundary.  They are never eligible for automatic resume.
        if _metadata_is_link_or_reparse_point(item_metadata):
            continue
        try:
            if stat.S_ISREG(item_metadata.st_mode):
                if item.name in reserved_root_files:
                    continue
                if item.suffix.lower() == ".json":
                    candidates.append((item, item_metadata.st_mtime, item_metadata))
                # A root-level ``foo.json.tmp`` cannot be mapped safely after
                # directory sessions were introduced: treating ``foo.json``
                # as the latest session would launch an empty ``foo/`` and
                # silently ignore the recovery data.  Only session-local
                # ``active.json.tmp`` files below are eligible for recovery.
                continue
            if not stat.S_ISDIR(item_metadata.st_mode):
                continue
            child_root, child_identity, child_entries = (
                snapshot_directory_entries_without_links(
                    item,
                    field="chat history session directory",
                )
            )
            if not os.path.samestat(item_metadata, child_identity):
                raise PermissionError(
                    f"chat history session identity changed: {item}"
                )
            child_times: list[float] = []
            wanted_names = {
                ACTIVE_HISTORY_FILENAME,
                BRANCH_TREE_FILENAME,
                f"{ACTIVE_HISTORY_FILENAME}.tmp",
            }
            for child, child_metadata in child_entries:
                if child.name not in wanted_names:
                    continue
                if (
                    _metadata_is_link_or_reparse_point(child_metadata)
                    or not stat.S_ISREG(child_metadata.st_mode)
                ):
                    continue
                child_times.append(child_metadata.st_mtime)
            require_directory_identity(
                child_root,
                child_identity,
                field="chat history session directory",
            )
            if child_times:
                candidates.append((item, max(child_times), item_metadata))
        except FileNotFoundError:
            # A clear operation may remove a candidate while resume is
            # scanning. Ignore only that vanished candidate.
            continue
    require_directory_identity(
        path,
        path_identity,
        field="chat history directory",
    )
    if not candidates:
        return None
    selected, _mtime, selected_identity = max(
        candidates,
        key=lambda item: item[1],
    )
    try:
        current_identity = selected.lstat()
    except FileNotFoundError:
        return None
    if (
        _metadata_is_link_or_reparse_point(current_identity)
        or not os.path.samestat(selected_identity, current_identity)
    ):
        raise PermissionError(
            f"latest chat history identity changed: {selected}"
        )
    require_directory_identity(
        path,
        path_identity,
        field="chat history directory",
    )
    return selected


def _runtime_template_hash(runtime_template: str) -> str:
    return hashlib.sha256(runtime_template.encode("utf-8")).hexdigest()


def _write_runtime_template_files(
    template_dir: Path,
    runtime_template: str,
    scenario: str,
    system: str,
) -> None:
    """Publish the runtime template and integrity-bound split metadata."""

    template_dir, template_dir_identity = capture_directory_identity(
        template_dir,
        field="template directory",
    )
    temp_path = template_dir / "_temp.txt"
    meta_path = template_dir / TEMP_SPLIT_META
    if (
        path_is_link_or_reparse_point(temp_path)
        or path_is_link_or_reparse_point(meta_path)
    ):
        raise PermissionError("runtime template files must not be symbolic links")
    metadata = json.dumps(
        {
            "scenario": scenario,
            "system": system,
            RUNTIME_TEMPLATE_HASH_FIELD: _runtime_template_hash(runtime_template),
        },
        ensure_ascii=False,
        indent=2,
    )
    with _RUNTIME_TEMPLATE_WRITE_LOCK:
        atomic_write_text(
            managed_child_path(template_dir, "_temp.txt", field="runtime template filename"),
            runtime_template,
            expected_parent_identity=template_dir_identity,
        )
        atomic_write_text(
            managed_child_path(template_dir, TEMP_SPLIT_META, field="runtime template metadata filename"),
            metadata,
            expected_parent_identity=template_dir_identity,
        )
        require_directory_identity(
            template_dir,
            template_dir_identity,
            field="template directory",
        )


def _read_split_meta(
    template_dir: Path,
    runtime_template: str,
    *,
    expected_parent_identity: os.stat_result | None = None,
) -> tuple[tuple[str, str] | None, bool]:
    """Return split fields and whether integrity metadata rejected the pair."""

    meta_path = template_dir / TEMP_SPLIT_META
    try:
        data = json.loads(
            read_text_without_links(
                meta_path,
                expected_parent_identity=expected_parent_identity,
            )
        )
    except FileNotFoundError:
        return None, False
    except PermissionError:
        if expected_parent_identity is not None:
            raise
        return None, False
    except (OSError, json.JSONDecodeError):
        return None, False
    if not isinstance(data, dict):
        return None, False
    expected_hash = data.get(RUNTIME_TEMPLATE_HASH_FIELD)
    if expected_hash is not None:
        if not isinstance(expected_hash, str) or not hmac.compare_digest(
            expected_hash,
            _runtime_template_hash(runtime_template),
        ):
            return None, True
    scenario = data.get("scenario", "")
    system = data.get("system", "")
    if not isinstance(scenario, str):
        scenario = ""
    if not isinstance(system, str):
        system = ""
    if scenario.strip() or system.strip():
        return (scenario, system), False
    return None, False


def _repair_template_parts_from_session_if_needed(
    state: BridgeState,
    scenario: str,
    system: str,
) -> tuple[str, str]:
    if not _has_untranslated_template_keys(scenario, system):
        return scenario, system
    repaired = _repair_template_session_if_needed(
        state,
        load_template_session(
            _template_dir(state).as_posix(),
            project_root=state_project_root(state),
        ),
    )
    if not repaired:
        return scenario, system
    return str(repaired.get("scenario_text") or ""), str(repaired.get("system_template_text") or "")


def _resume_template_parts_from_directory(
    template_dir: Path,
) -> tuple[str, str, str] | None:
    """Read one resume candidate from a stable template-directory snapshot."""

    template_dir, template_dir_identity, entries = (
        snapshot_directory_entries_without_links(
            template_dir,
            field="template directory",
        )
    )
    regular_templates = [
        (path, metadata)
        for path, metadata in entries
        if (
            not _metadata_is_link_or_reparse_point(metadata)
            and stat.S_ISREG(metadata.st_mode)
            and path.suffix == ".txt"
        )
    ]
    temp_candidate = next(
        (
            (path, metadata)
            for path, metadata in regular_templates
            if path.name == "_temp.txt"
        ),
        None,
    )
    if temp_candidate is not None and temp_candidate[1].st_size > 0:
        temp_path, temp_identity = temp_candidate
        try:
            runtime_template, _runtime_identity = read_text_snapshot_without_links(
                temp_path,
                expected_identity=temp_identity,
                expected_parent_identity=template_dir_identity,
            )
        except FileNotFoundError:
            runtime_template = ""
        split_meta, integrity_mismatch = _read_split_meta(
            template_dir,
            runtime_template,
            expected_parent_identity=template_dir_identity,
        )
        if split_meta is not None:
            require_directory_identity(
                template_dir,
                template_dir_identity,
                field="template directory",
            )
            return split_meta[0], split_meta[1], "_temp.txt"
        if not integrity_mismatch:
            scenario, system = _parse_stored_template(runtime_template)
            if scenario.strip() or system.strip():
                require_directory_identity(
                    template_dir,
                    template_dir_identity,
                    field="template directory",
                )
                return scenario, system, "_temp.txt"

    candidates = [
        (path, metadata)
        for path, metadata in regular_templates
        if path.name != "_temp.txt"
    ]
    if not candidates:
        return None
    path, path_identity = max(
        candidates,
        key=lambda item: item[1].st_mtime_ns,
    )
    try:
        raw, _read_identity = read_text_snapshot_without_links(
            path,
            expected_identity=path_identity,
            expected_parent_identity=template_dir_identity,
        )
        scenario, system = _parse_stored_template(raw)
    except FileNotFoundError:
        return None
    require_directory_identity(
        template_dir,
        template_dir_identity,
        field="template directory",
    )
    if scenario.strip() or system.strip():
        return scenario, system, path.name
    return None


def _resume_template_parts(state: BridgeState) -> tuple[str, str, str] | None:
    resumed = _resume_template_parts_from_directory(_template_dir(state))
    if resumed is None:
        return None
    scenario, system, template_name = resumed
    scenario, system = _repair_template_parts_from_session_if_needed(
        state,
        scenario,
        system,
    )
    return scenario, system, template_name


def _list_templates(state: BridgeState) -> list[dict[str, Any]]:
    template_dir, template_dir_identity, entries = (
        snapshot_directory_entries_without_links(
            _template_dir(state),
            field="template directory",
        )
    )
    rows: list[dict[str, Any]] = []
    for path, path_identity in sorted(
        entries,
        key=lambda item: item[0].name.lower(),
    ):
        if (
            path.suffix != ".txt"
            or _metadata_is_link_or_reparse_point(path_identity)
            or not stat.S_ISREG(path_identity.st_mode)
        ):
            continue
        try:
            raw, read_identity = read_text_snapshot_without_links(
                path,
                expected_identity=path_identity,
                expected_parent_identity=template_dir_identity,
            )
        except FileNotFoundError:
            continue
        scenario, system = _parse_stored_template(raw)
        rows.append(
            {
                "content": _compose_for_llm(scenario, system),
                "id": _template_id(path),
                "name": path.stem,
                "path": path.as_posix(),
                "scenario": scenario,
                "system": system,
                "updatedAt": str(int(read_identity.st_mtime)),
            }
        )
    require_directory_identity(
        template_dir,
        template_dir_identity,
        field="template directory",
    )
    return rows


def _save_template_summary(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    template = payload.get("template", payload)
    if not isinstance(template, dict):
        raise ValueError("template payload must be an object")
    name = str(template.get("name") or template.get("id") or "")
    if not name:
        raise ValueError("template name is required")
    scenario = _scenario_from_template_like(template)
    system = str(template.get("system") or "")
    file_name = safe_filename(name, default_suffix=".txt")
    template_dir = _template_dir(state)
    template_dir, template_dir_identity = capture_directory_identity(
        template_dir,
        field="template directory",
    )
    ensure_portable_name_available(
        template_dir,
        file_name,
        expected_directory_identity=template_dir_identity,
    )
    if path_is_link_or_reparse_point(template_dir / file_name):
        raise PermissionError("template files must not be symbolic links")
    atomic_write_text(
        managed_child_path(template_dir, file_name, field="template filename"),
        _compose_stored_template(scenario, system),
        expected_parent_identity=template_dir_identity,
    )
    require_directory_identity(
        template_dir,
        template_dir_identity,
        field="template directory",
    )
    for row in _list_templates(state):
        if row["id"] == file_name:
            return row
    raise RuntimeError("template was saved but not found")


def _generate_template_summary(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    selected = payload.get("characters") or []
    resolved_names = _resolve_template_character_names(state, selected)
    if not resolved_names:
        raise NoValidCharactersError()
    background = str(payload.get("backgroundName") or "")
    voice_language = str(payload.get("voiceLanguage") or "").strip()
    if voice_language:
        previous_system_config = state.config_manager.config.system_config
        sc = previous_system_config.model_copy(deep=True)
        sc.voice_language = voice_language
        state.config_manager.config.system_config = sc
        try:
            state.config_manager.save_system_config()
        except BaseException:
            state.config_manager.config.system_config = previous_system_config
            raise
    max_speech_chars = max(0, int(payload.get("maxSpeechChars") or 0))
    max_dialog_items = max(0, int(payload.get("maxDialogItems") or 0))
    content, result = state.template_generator.generate_chat_template(
        resolved_names,
        background,
        bool(payload.get("useEffect", True)),
        bool(payload.get("useCg", False)),
        bool(payload.get("useTranslation", True)),
        bool(payload.get("useCot", False)),
        bool(payload.get("useChoice", True)),
        bool(payload.get("useNarration", True)),
        bool(payload.get("useStat", True)),
        max_speech_chars=max_speech_chars,
        max_dialog_items=max_dialog_items,
    )
    output_name = str(result or "").strip()
    name = str(output_name or payload.get("name") or "generated").strip()
    scenario = str(payload.get("scenario") or "")
    row = {
        "content": _compose_for_llm(scenario, content),
        "id": "",
        "name": name,
        "path": "",
        "scenario": scenario,
        "system": content,
        "updatedAt": "",
        "resolvedCharacters": resolved_names,
    }
    row["generationMessage"] = result
    return row


def _resolve_template_character_names(state: BridgeState, selected: Any) -> list[str]:
    """Return the canonical valid character names used by every template-flow boundary."""
    if not isinstance(selected, list):
        raise ValueError("characters must be a list")
    resolved = resolve_chat_template_characters(selected, state.config_manager)
    resolved_names = [name for name, _character in resolved]
    if selected and not resolved_names:
        raise NoValidCharactersError()
    return resolved_names


def _safe_session_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _session_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _template_session_to_frontend(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw:
        return None
    return {
        "background": str(raw.get("background") or ""),
        "effectNames": _session_string_list(raw.get("effect_names")),
        "enableMobileAccess": bool(raw.get("enable_mobile_access", False)),
        "filenameStub": str(raw.get("filename_stub") or ""),
        "historyPath": str(raw.get("history_file") or ""),
        "initSpritePath": str(raw.get("init_sprite_path") or ""),
        "maxDialogItems": _safe_session_int(raw.get("max_dialog_items")),
        "maxSpeechChars": _safe_session_int(raw.get("max_speech_chars")),
        "roomId": str(raw.get("room_id") or ""),
        "scenario": str(raw.get("scenario_text") or ""),
        "selectedCharacters": _session_string_list(raw.get("selected_characters")),
        "system": str(raw.get("system_template_text") or ""),
        "templateFileDropdown": str(raw.get("template_file_dropdown") or ""),
        "workflowPath": str(raw.get("workflow_path") or ""),
        "useCg": bool(raw.get("use_cg_yes", False)),
        "useChoice": bool(raw.get("use_choice_yes", True)),
        "useCot": bool(raw.get("use_cot_yes", False)),
        "useEffect": bool(raw.get("use_effect_yes", True)),
        "useNarration": bool(raw.get("use_narration_yes", True)),
        "useStat": bool(raw.get("use_stat_yes", True)),
        "useTranslation": bool(raw.get("use_tr_yes", True)),
        "voiceLanguage": str(raw.get("voice_lang") or ""),
    }


def _persist_template_session_repair(state: BridgeState, raw: dict[str, Any]) -> None:
    from application.chat.session_store import save_template_session

    save_template_session(
        _template_dir(state).as_posix(),
        raw,
        project_root=state_project_root(state),
    )


def _reconcile_template_session_characters(
    state: BridgeState,
    raw: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Remove stale names and canonicalize restored template selections."""
    if not raw:
        return raw
    selected = _session_string_list(raw.get("selected_characters"))
    resolved = resolve_chat_template_characters(selected, state.config_manager)
    resolved_names = [name for name, _character in resolved]
    if resolved_names == selected:
        return raw
    repaired = dict(raw)
    repaired["selected_characters"] = resolved_names
    repaired["init_sprite_path"] = initial_sprite_path_for_characters(
        state.config_manager,
        str(raw.get("init_sprite_path") or ""),
        resolved_names,
    )
    try:
        _persist_template_session_repair(state, repaired)
    except OSError:
        pass
    return repaired


def _rename_template_session_character(
    state: BridgeState,
    original_name: str,
    saved_name: str,
) -> None:
    """Carry a character rename into the persisted template selection."""
    original_key = character_name_key(original_name)
    if not original_key or original_key == character_name_key(saved_name):
        return
    from application.chat.session_store import load_template_session

    raw = load_template_session(
        _template_dir(state).as_posix(),
        project_root=state_project_root(state),
    )
    if not raw:
        return
    selected = _session_string_list(raw.get("selected_characters"))
    renamed = [
        saved_name if character_name_key(name) == original_key else name
        for name in selected
    ]
    if renamed == selected:
        return
    repaired = dict(raw)
    repaired["selected_characters"] = renamed
    reconciled = _reconcile_template_session_characters(state, repaired)
    if reconciled is repaired:
        _persist_template_session_repair(state, repaired)


def _load_template_session_payload(state: BridgeState) -> dict[str, Any] | None:
    from application.chat.session_store import load_template_session

    raw = load_template_session(
        _template_dir(state).as_posix(),
        project_root=state_project_root(state),
    )
    raw = _reconcile_template_session_characters(state, raw)
    raw = _repair_template_session_if_needed(state, raw)
    return _template_session_to_frontend(raw)


def _save_template_session_payload(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    from application.chat.session_store import save_template_session

    history_value = ""
    history_raw = str(payload.get("historyPath") or "")
    if history_raw:
        history_value = history_reference_value(
            state,
            resolve_history_path_for_project(state, history_raw),
        )

    selected_characters = _resolve_template_character_names(
        state,
        payload.get("selectedCharacters") or [],
    )
    init_sprite_path = initial_sprite_path_for_characters(
        state.config_manager,
        str(payload.get("initSpritePath") or ""),
        selected_characters,
    )
    data = {
        "selected_characters": selected_characters,
        "background": str(payload.get("background") or ""),
        "effect_names": _session_string_list(payload.get("effectNames")),
        "enable_mobile_access": bool(payload.get("enableMobileAccess", False)),
        "voice_lang": str(payload.get("voiceLanguage") or ""),
        "use_effect_yes": bool(payload.get("useEffect", True)),
        "use_tr_yes": bool(payload.get("useTranslation", True)),
        "use_cg_yes": bool(payload.get("useCg", False)),
        "use_cot_yes": bool(payload.get("useCot", False)),
        "use_choice_yes": bool(payload.get("useChoice", True)),
        "use_narration_yes": bool(payload.get("useNarration", True)),
        "use_stat_yes": bool(payload.get("useStat", True)),
        "max_speech_chars": _safe_session_int(payload.get("maxSpeechChars")),
        "max_dialog_items": _safe_session_int(payload.get("maxDialogItems")),
        "scenario_text": str(payload.get("scenario") or ""),
        "system_template_text": str(payload.get("system") or ""),
        "filename_stub": str(payload.get("filenameStub") or ""),
        "template_file_dropdown": str(payload.get("templateFileDropdown") or ""),
        "init_sprite_path": init_sprite_path,
        "history_file": history_value,
        "room_id": str(payload.get("roomId") or ""),
        "workflow_path": str(payload.get("workflowPath") or ""),
    }
    save_template_session(
        _template_dir(state).as_posix(),
        data,
        project_root=state_project_root(state),
    )
    loaded = _load_template_session_payload(state)
    if loaded is None:
        raise RuntimeError("template session was saved but not found")
    return loaded


def _has_untranslated_template_keys(*values: Any) -> bool:
    return any("template_gen." in str(value or "") for value in values)


def _repair_template_session_if_needed(state: BridgeState, raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw or not _has_untranslated_template_keys(raw.get("scenario_text"), raw.get("system_template_text")):
        return raw
    selected = raw.get("selected_characters") or []
    if not isinstance(selected, list) or not selected:
        return raw
    try:
        content, _result = state.template_generator.generate_chat_template(
            [str(item) for item in selected if str(item)],
            str(raw.get("background") or ""),
            bool(raw.get("use_effect_yes", True)),
            bool(raw.get("use_cg_yes", False)),
            bool(raw.get("use_tr_yes", True)),
            bool(raw.get("use_cot_yes", False)),
            bool(raw.get("use_choice_yes", True)),
            bool(raw.get("use_narration_yes", True)),
            bool(raw.get("use_stat_yes", True)),
            max_speech_chars=_safe_session_int(raw.get("max_speech_chars")),
            max_dialog_items=_safe_session_int(raw.get("max_dialog_items")),
        )
    except NoValidCharactersError:
        return raw
    repaired = dict(raw)
    if _has_untranslated_template_keys(repaired.get("scenario_text")):
        repaired["scenario_text"] = ""
    repaired["system_template_text"] = content
    try:
        save_template_session(
            _template_dir(state).as_posix(),
            repaired,
            project_root=state_project_root(state),
        )
    except Exception:
        pass
    return repaired
