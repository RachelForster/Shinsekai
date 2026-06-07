from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .state import BridgeState
from .tasks import _update_task

MAX_FILE_BROWSER_ENTRIES = 2000


def _extract_prompt_from_line(line: str) -> str:
    text = line.strip()
    if not text:
        return ""
    match = re.match(r"^[^:]+[:：]\s*(.+)$", text)
    if match:
        return match.group(1).strip()
    return text


def _sprite_output_dir(state: BridgeState, character_name: str, requested: Any = "") -> Path:
    raw = str(requested or "").strip()
    if raw:
        return Path(raw)
    character = state.config_manager.get_character_by_name(character_name)
    if character is None:
        raise KeyError(f"character not found: {character_name}")
    return Path("data/sprite") / str(character.sprite_prefix or character.name or "sprites")


def _generate_sprite_prompts(state: BridgeState, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from tools.generate_sprites import ImageGenerator

    character_name = str(payload.get("characterName") or "").strip()
    if not character_name:
        raise ValueError("characterName is required")
    count = int(payload.get("count") or 1)
    if count < 1 or count > 100:
        raise ValueError("count must be between 1 and 100")
    character = state.config_manager.get_character_by_name(character_name)
    if character is None:
        raise KeyError(f"character not found: {character_name}")

    _update_task(state, task_id, message="正在生成立绘提示词。", phase="prompt", progress=0.18)
    prompts = ImageGenerator().generate_prompts(count, str(character.character_setting or ""))
    result = {"prompts": [str(item) for item in prompts]}
    _update_task(state, task_id, message="提示词已生成。", phase="completed", progress=1, result=result)
    return result


def _generate_sprites(state: BridgeState, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from tools.generate_sprites import ImageGenerator

    character_name = str(payload.get("characterName") or "").strip()
    if not character_name:
        raise ValueError("characterName is required")
    reference = Path(str(payload.get("referenceImage") or "").strip())
    if not reference.is_file():
        raise ValueError("referenceImage must point to an existing file")
    raw_prompts = payload.get("prompts") or []
    if isinstance(raw_prompts, str):
        prompts = [_extract_prompt_from_line(line) for line in raw_prompts.splitlines()]
    elif isinstance(raw_prompts, list):
        prompts = [_extract_prompt_from_line(str(item)) for item in raw_prompts]
    else:
        raise ValueError("prompts must be a list or string")
    prompts = [item for item in prompts if item]
    if not prompts:
        raise ValueError("at least one prompt is required")

    output_dir = _sprite_output_dir(state, character_name, payload.get("outputDir"))
    _update_task(state, task_id, message="正在批量生成立绘。", phase="generate", progress=0.12)
    files = ImageGenerator().batch_generate_sprites(reference, prompts, output_dir)
    paths = [Path(item).as_posix() for item in files if item and Path(item).is_file()]
    result = {
        "files": paths,
        "message": f"已生成 {len(paths)} 张（输出目录: {output_dir.as_posix()}）",
        "outputDir": output_dir.as_posix(),
    }
    _update_task(state, task_id, message=result["message"], phase="completed", progress=1, result=result)
    return result


def _crop_sprites(state: BridgeState, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from tools.crop_sprite import batch_crop_upper_half

    input_dir = Path(str(payload.get("inputDir") or "").strip())
    ratio = float(payload.get("ratio") or 1.0)
    requested_output = str(payload.get("outputDir") or "").strip()
    output_dir = Path(requested_output) if requested_output else input_dir / f"cropped_upper_{ratio}"

    _update_task(state, task_id, message="正在批量裁剪立绘。", phase="crop", progress=0.25)
    message = batch_crop_upper_half(ratio, input_dir.as_posix(), requested_output or None)
    result = {"message": str(message), "outputDir": output_dir.as_posix()}
    _update_task(state, task_id, message=result["message"], phase="completed", progress=1, result=result)
    return result


def _remove_sprite_background(state: BridgeState, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from tools.remove_bg import batch_remove_background

    input_dir = Path(str(payload.get("inputDir") or "").strip())
    requested_output = str(payload.get("outputDir") or "").strip()
    output_dir = Path(requested_output) if requested_output else input_dir / "removed_backgrounds"

    _update_task(state, task_id, message="正在批量抠出立绘。", phase="remove-background", progress=0.25)
    message = batch_remove_background(input_dir.as_posix(), requested_output or None)
    result = {"message": str(message), "outputDir": output_dir.as_posix()}
    _update_task(state, task_id, message=result["message"], phase="completed", progress=1, result=result)
    return result


def _strip_windows_verbatim_prefix(value: str) -> str:
    if value.startswith("\\\\?\\UNC\\"):
        return "\\\\" + value[len("\\\\?\\UNC\\") :]
    if value.startswith("\\\\?\\"):
        return value[len("\\\\?\\") :]
    if value.startswith("//?/UNC/"):
        return "//" + value[len("//?/UNC/") :]
    if value.startswith("//?/"):
        return value[len("//?/") :]
    return value


def _display_path(path: Path) -> str:
    try:
        value = str(path.resolve(strict=False))
    except Exception:
        value = str(path)
    if os.name == "nt":
        value = _strip_windows_verbatim_prefix(value)
        return value.replace("\\", "/")
    return Path(value).as_posix()


def _file_browser_root_key(value: str) -> str:
    normalized = _strip_windows_verbatim_prefix(value).replace("\\", "/")
    if match := re.match(r"^([A-Za-z]:)/*$", normalized):
        return match.group(1).lower()
    if normalized.startswith("//"):
        return normalized.rstrip("/").lower()
    return normalized.lower() if os.name == "nt" else normalized


def _file_browser_root_label(label: str, value: str) -> str:
    normalized_label = _strip_windows_verbatim_prefix(label).replace("\\", "/").rstrip("/")
    normalized_value = _strip_windows_verbatim_prefix(value).replace("\\", "/").rstrip("/")
    for candidate in (normalized_label, normalized_value):
        if match := re.match(r"^([A-Za-z]:)$", candidate):
            return match.group(1)
    return normalized_label or normalized_value


def _resolve_path(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except Exception:
        return path


def _state_app_root(state: BridgeState, project_root: Path) -> Path:
    raw = str(getattr(state, "app_root_dir", "") or os.environ.get("SHINSEKAI_APP_ROOT") or "").strip()
    if raw:
        app_root = _resolve_path(Path(raw).expanduser())
        if app_root.exists() and app_root.is_dir():
            return app_root
    return project_root


def _project_data_root(project_root: Path) -> Path:
    data_root = _resolve_path(project_root / "data")
    try:
        data_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return data_root


def _xdg_downloads_dir(home: Path) -> Path | None:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config").expanduser()
    user_dirs = config_home / "user-dirs.dirs"
    try:
        lines = user_dirs.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    for line in lines:
        raw = line.strip()
        if not raw.startswith("XDG_DOWNLOAD_DIR="):
            continue
        value = raw.split("=", 1)[1].strip().strip('"').strip("'")
        if not value:
            return None
        if value == "$HOME":
            return home
        if value.startswith("$HOME/"):
            return home / value[len("$HOME/") :]
        if value.startswith("${HOME}/"):
            return home / value[len("${HOME}/") :]
        path = Path(value).expanduser()
        return path if path.is_absolute() else home / path
    return None


def _user_downloads_dir() -> Path | None:
    try:
        home = Path.home()
    except RuntimeError:
        raw_home = os.environ.get("USERPROFILE") if os.name == "nt" else os.environ.get("HOME")
        if not raw_home:
            return None
        home = Path(raw_home).expanduser()

    if os.name != "nt":
        return _xdg_downloads_dir(home) or home / "Downloads"

    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        return Path(user_profile).expanduser() / "Downloads"
    return home / "Downloads"


def _filesystem_roots(project_root: Path, app_root: Path) -> list[dict[str, str]]:
    roots: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(label: str, path: Path) -> None:
        resolved = _resolve_path(path)
        if not resolved.exists():
            return
        value = _display_path(resolved)
        key = _file_browser_root_key(value)
        if key in seen:
            return
        seen.add(key)
        roots.append({"label": _file_browser_root_label(label, value), "path": value})

    add("Shinsekai", app_root)
    add("Data", _project_data_root(project_root))
    downloads_dir = _user_downloads_dir()
    if downloads_dir is not None:
        add("Downloads", downloads_dir)
    add("Home", Path.home())

    for root in (app_root, project_root):
        anchor = _resolve_path(root).anchor
        if anchor:
            add(anchor, Path(anchor))

    if os.name == "nt":
        for code in range(ord("A"), ord("Z") + 1):
            drive = Path(f"{chr(code)}:/")
            if drive.exists():
                add(f"{chr(code)}:", drive)

    return roots


def _browse_local_files(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(payload.get("path") or "").strip()
    show_hidden = bool(payload.get("showHidden"))
    root_raw = os.environ.get("EASYAI_PROJECT_ROOT") or str(Path.cwd())
    project_root = _resolve_path(Path(root_raw).expanduser())
    app_root = _state_app_root(state, project_root)
    target = Path(raw_path).expanduser() if raw_path else app_root
    if not target.is_absolute():
        target = project_root / target

    target = _resolve_path(target)

    if target.exists() and target.is_file():
        target = target.parent

    if not target.exists():
        raise FileNotFoundError(f"路径不存在: {_display_path(target)}")
    if not target.is_dir():
        raise NotADirectoryError(f"不是目录: {_display_path(target)}")

    entries: list[dict[str, Any]] = []
    try:
        with os.scandir(target) as children:
            for child in children:
                name = child.name
                if not show_hidden and name.startswith("."):
                    continue
                if len(entries) >= MAX_FILE_BROWSER_ENTRIES:
                    break
                try:
                    is_dir = child.is_dir(follow_symlinks=False)
                    item_stat = child.stat(follow_symlinks=False)
                except OSError:
                    continue
                entries.append(
                    {
                        "kind": "directory" if is_dir else "file",
                        "modifiedAt": item_stat.st_mtime,
                        "name": name,
                        "path": _display_path(Path(child.path)),
                        "size": None if is_dir else item_stat.st_size,
                    }
                )
    except PermissionError:
        raise
    except OSError as exc:
        raise RuntimeError(f"无法读取目录: {_display_path(target)}: {exc}") from exc

    entries.sort(key=lambda item: (item["kind"] != "directory", item["name"].casefold()))
    parent = target.parent if target.parent != target else None
    return {
        "cwd": _display_path(target),
        "entries": entries,
        "parent": _display_path(parent) if parent is not None else "",
        "roots": _filesystem_roots(project_root, app_root),
    }
