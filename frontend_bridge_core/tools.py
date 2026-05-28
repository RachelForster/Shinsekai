from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

from .state import BridgeState
from .tasks import _update_task


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


def _display_path(path: Path) -> str:
    return path.resolve(strict=False).as_posix()


def _filesystem_roots(project_root: Path) -> list[dict[str, str]]:
    roots: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(label: str, path: Path) -> None:
        try:
            resolved = path.resolve(strict=False)
        except Exception:
            return
        if not resolved.exists():
            return
        value = resolved.as_posix()
        key = value.lower() if os.name == "nt" else value
        if key in seen:
            return
        seen.add(key)
        roots.append({"label": label, "path": value})

    add("Shinsekai", project_root)
    add("Data", project_root / "data")
    add("Home", Path.home())

    anchor = project_root.resolve(strict=False).anchor
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
    project_root = Path(root_raw).expanduser().resolve(strict=False)
    target = Path(raw_path).expanduser() if raw_path else project_root
    if not target.is_absolute():
        target = project_root / target

    try:
        target = target.resolve(strict=False)
    except Exception:
        pass

    if target.exists() and target.is_file():
        target = target.parent

    if not target.exists():
        raise FileNotFoundError(f"路径不存在: {target}")
    if not target.is_dir():
        raise NotADirectoryError(f"不是目录: {target}")

    entries: list[dict[str, Any]] = []
    try:
        children = list(target.iterdir())
    except PermissionError:
        raise
    except OSError as exc:
        raise RuntimeError(f"无法读取目录: {target}: {exc}") from exc

    for child in children:
        name = child.name
        if not show_hidden and name.startswith("."):
            continue
        try:
            item_stat = child.stat()
            is_dir = child.is_dir()
        except OSError:
            continue
        entries.append(
            {
                "kind": "directory" if is_dir else "file",
                "modifiedAt": item_stat.st_mtime,
                "name": name,
                "path": _display_path(child),
                "size": None if is_dir else item_stat.st_size,
            }
        )

    entries.sort(key=lambda item: (item["kind"] != "directory", item["name"].casefold()))
    parent = target.parent if target.parent != target else None
    return {
        "cwd": _display_path(target),
        "entries": entries,
        "parent": _display_path(parent) if parent is not None else "",
        "roots": _filesystem_roots(project_root),
    }


def _download_tts_bundle(state: BridgeState, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from ui.settings_ui.tts.tts_bundle_worker import (
        _archive_filename,
        _extract_7za,
        _list_targets,
        _load_py7zr,
        _resolve_extracted_root,
        _rmtree,
        _seven_zip_exe,
    )
    from ui.settings_ui.tts.tts_env_probe import bundle_choice_for_kind, get_default_project_root

    kind = str(payload.get("kind") or "genie").strip()
    choice = bundle_choice_for_kind(kind)
    root = get_default_project_root().resolve()
    base = root / "data" / "tts_bundles"
    dl_dir = base / "downloads"
    out_dir = base / "installed" / choice.bundle_dir_key
    dl_dir.mkdir(parents=True, exist_ok=True)
    archive = dl_dir / _archive_filename(choice.download_url)
    _rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) EasyAI-Desktop/1.0"
        )
    }
    _update_task(state, task_id, message="正在下载 TTS 整合包。", phase="download", progress=0.02)
    try:
        import requests

        with requests.get(choice.download_url, stream=True, timeout=(15, 600), headers=headers) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length", "0") or 0)
            downloaded = 0
            with archive.open("wb") as file:
                for chunk in response.iter_content(512 * 1024):
                    if not chunk:
                        continue
                    file.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        progress = min(0.7, 0.7 * downloaded / total)
                        message = f"正在下载 {downloaded}/{total} bytes。"
                    else:
                        progress = min(0.35, downloaded / (50 * 1024 * 1024))
                        message = f"已下载 {downloaded} bytes。"
                    _update_task(state, task_id, message=message, phase="download", progress=round(progress, 4))
    except Exception as exc:
        raise RuntimeError(f"download: {exc}") from exc

    _update_task(state, task_id, message="正在解压 TTS 整合包。", phase="extract", progress=0.7)
    seven_zip = _seven_zip_exe()
    if getattr(sys, "frozen", False):
        if seven_zip is None:
            raise RuntimeError(f"7za not found; archive saved at {archive.resolve()}")
        error = _extract_7za(seven_zip, archive, out_dir)
        if error is not None:
            raise RuntimeError(f"extract: {error}; archive saved at {archive.resolve()}")
    else:
        py7zr = _load_py7zr()
        if py7zr is not None:
            try:
                with py7zr.SevenZipFile(archive, "r") as zfile:
                    targets = _list_targets(zfile)
                    total_targets = len(targets)
                    if total_targets == 0 or total_targets > 1000:
                        zfile.extractall(path=out_dir)
                    else:
                        for index, name in enumerate(targets, start=1):
                            zfile.extract(path=out_dir, targets=[name])
                            progress = 0.7 + 0.3 * index / total_targets
                            _update_task(
                                state,
                                task_id,
                                message=f"正在解压 {index}/{total_targets}。",
                                phase="extract",
                                progress=round(progress, 4),
                            )
            except Exception as exc:
                raise RuntimeError(f"extract: {exc}; archive saved at {archive.resolve()}") from exc
        elif seven_zip is not None:
            error = _extract_7za(seven_zip, archive, out_dir)
            if error is not None:
                raise RuntimeError(f"extract: {error}; archive saved at {archive.resolve()}")
        else:
            raise RuntimeError(f"py7zr is not installed; archive saved at {archive.resolve()}")

    bundle_root = _resolve_extracted_root(out_dir)
    result = {
        "path": str(bundle_root.resolve()),
        "provider": "genie-tts" if choice.kind == "genie" else "gpt-sovits",
    }
    _update_task(state, task_id, message="TTS 整合包已就绪。", phase="completed", progress=1, result=result)
    return result
