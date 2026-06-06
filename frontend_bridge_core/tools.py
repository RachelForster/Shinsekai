from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .state import BridgeState
from .tasks import _update_task

MAX_FILE_BROWSER_ENTRIES = 2000

_LABEL_LANGUAGE_NAMES = {
    "en": "English",
    "ja": "Japanese",
    "zh_CN": "Simplified Chinese",
}


def _extract_prompt_from_line(line: str) -> str:
    text = line.strip()
    if not text:
        return ""
    match = re.match(r"^[^:]+[:：]\s*(.+)$", text)
    if match:
        return match.group(1).strip()
    return text


def _ascii_prompt_text(value: Any) -> str:
    return (
        str(value or "")
        .encode("ascii", errors="ignore")
        .decode("ascii")
        .replace("\n", " ")
        .strip()
    )


def _split_sprite_prompt_line(value: str) -> dict[str, str]:
    text = str(value or "").strip()
    match = re.match(r"^(?:\d+[.)]\s*)?([^:：|]+)[:：|]\s*(.+)$", text)
    if match:
        return {"label": match.group(1).strip(), "prompt": _ascii_prompt_text(match.group(2))}
    return {"label": "", "prompt": _ascii_prompt_text(text)}


def _response_text(response: Any) -> str:
    if response is None:
        return ""
    if hasattr(response, "text") and isinstance(response.text, str):
        return response.text
    choices = getattr(response, "choices", None)
    if choices:
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(str(getattr(part, "text", part)) for part in content)
    blocks = getattr(response, "content", None)
    if blocks:
        parts: list[str] = []
        for block in blocks:
            text = getattr(block, "text", None)
            if text:
                parts.append(str(text))
        return "\n".join(parts)
    return str(response)


def _load_sprite_prompt_payload(text: str) -> Any:
    raw = text.strip().replace("```json", "").replace("```", "").strip()
    if not raw:
        raise ValueError("LLM returned an empty prompt response")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start : end + 1])
        start = raw.find("[")
        end = raw.rfind("]")
        if start >= 0 and end > start:
            return json.loads(raw[start : end + 1])
        raise


def _normalize_sprite_prompt_items(payload: Any, count: int) -> list[dict[str, str]]:
    if isinstance(payload, dict):
        raw_items = payload.get("items") or payload.get("prompts") or []
    else:
        raw_items = payload
    if not isinstance(raw_items, list):
        raise ValueError("LLM prompt response must contain a JSON list")

    items: list[dict[str, str]] = []
    for raw_item in raw_items[:count]:
        if isinstance(raw_item, dict):
            label = str(raw_item.get("label") or raw_item.get("tag") or "").strip()
            prompt = _ascii_prompt_text(raw_item.get("prompt") or raw_item.get("sd_prompt") or "")
        else:
            parsed = _split_sprite_prompt_line(str(raw_item))
            label = parsed["label"]
            prompt = parsed["prompt"]
        if prompt:
            items.append({"label": label, "prompt": prompt})
    if not items:
        raise ValueError("LLM did not return any usable sprite prompts")
    return items


def _generate_sprite_prompt_items_with_llm(
    state: BridgeState,
    *,
    character_name: str,
    character_settings: str,
    count: int,
    language: str,
) -> dict[str, Any]:
    from llm.llm_manager import LLMAdapterFactory

    llm_provider, llm_model, llm_base_url, api_key = state.config_manager.get_llm_api_config()
    if not llm_provider or not llm_model or not api_key:
        raise RuntimeError("LLM config is incomplete. Configure provider, model, and API key first.")

    base_kwargs = {
        "llm_provider": llm_provider,
        "api_key": api_key,
        "base_url": llm_base_url,
        "model": llm_model,
    }
    if hasattr(state.config_manager, "merged_llm_factory_kwargs"):
        base_kwargs = state.config_manager.merged_llm_factory_kwargs(llm_provider, base_kwargs)
    adapter = LLMAdapterFactory.create_adapter(**base_kwargs)
    label_language = _LABEL_LANGUAGE_NAMES.get(language, "Simplified Chinese")
    system_prompt = (
        "You generate visual novel character sprite generation data. "
        "Return only a valid JSON object with an items array. "
        "Each item must be an object with label and prompt. "
        "The label must be short comma-separated emotion/action tags in the requested UI language. "
        "The prompt must be a pure English Stable Diffusion style prompt, ASCII only, and must include the character name. "
        "Do not include markdown, explanations, or non-English text inside prompt."
    )
    user_prompt = (
        f"Character name: {character_name}\n"
        f"Character settings:\n{character_settings}\n\n"
        f"Generate {count} different sprite candidates.\n"
        f"Label language: {label_language}\n"
        "Prompt requirements: full body, solo, visual novel sprite, transparent background, clean lineart, "
        "soft cel shading, consistent character design, expressive emotion and clear action.\n"
        'JSON shape: {"items":[{"label":"emotion, action","prompt":"English SD prompt with character name"}]}'
    )
    response = adapter.chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        stream=False,
        response_format={"type": "json_object"},
        max_tokens=1800,
    )
    payload = _load_sprite_prompt_payload(_response_text(response))
    return {
        "items": _normalize_sprite_prompt_items(payload, count),
        "model": llm_model,
        "provider": llm_provider,
    }


def _sprite_output_dir(state: BridgeState, character_name: str, requested: Any = "") -> Path:
    raw = str(requested or "").strip()
    if raw:
        return Path(raw)
    character = state.config_manager.get_character_by_name(character_name)
    if character is None:
        raise KeyError(f"character not found: {character_name}")
    return Path("data/sprite") / str(character.sprite_prefix or character.name or "sprites")


def _generate_sprite_prompts(state: BridgeState, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    character_name = str(payload.get("characterName") or "").strip()
    if not character_name:
        raise ValueError("characterName is required")
    count = int(payload.get("count") or 1)
    if count < 1 or count > 100:
        raise ValueError("count must be between 1 and 100")
    language = str(payload.get("language") or "zh_CN").strip()
    character = state.config_manager.get_character_by_name(character_name)
    if character is None:
        raise KeyError(f"character not found: {character_name}")

    _update_task(state, task_id, message="正在生成立绘提示词。", phase="prompt", progress=0.18)
    llm_result = _generate_sprite_prompt_items_with_llm(
        state,
        character_name=str(character.name or character_name),
        character_settings=str(character.character_setting or ""),
        count=count,
        language=language,
    )
    items = llm_result["items"]
    result = {
        "items": items,
        "model": llm_result["model"],
        "prompts": [item["prompt"] for item in items],
        "provider": llm_result["provider"],
    }
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
