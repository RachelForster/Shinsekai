from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
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

_SD_PROMPT_REQUIRED_PREFIX = (
    "masterpiece",
    "best quality",
    "highres",
    "official art",
    "solo",
    "1 person",
    "single character",
)

_SPRITE_COMPOSITION_TERMS: dict[str, str] = {
    "full_body": "full body",
    "thigh_up": "thigh up",
    "upper_body": "upper body",
}

_DEFAULT_SPRITE_COMPOSITION = "thigh_up"


def _sd_composition_term(composition: str) -> str:
    return _SPRITE_COMPOSITION_TERMS.get(composition.strip().lower(), _SPRITE_COMPOSITION_TERMS[_DEFAULT_SPRITE_COMPOSITION])


def _sd_required_terms(composition: str = _DEFAULT_SPRITE_COMPOSITION) -> tuple[str, ...]:
    return (
        _sd_composition_term(composition),
        "visual novel sprite",
        "transparent background",
        "clean lineart",
        "soft cel shading",
        "single view",
        "one pose",
        "centered character",
    )

_SPRITE_NEGATIVE_PROMPT_REQUIRED_TERMS = (
    "multiple views",
    "multiple angles",
    "turnaround",
    "character sheet",
    "reference sheet",
    "expression sheet",
    "pose sheet",
    "model sheet",
    "split view",
    "multiple panels",
    "collage",
    "duplicated character",
    "clone",
)


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


def _with_required_sd_prompt_prefix(value: Any, composition: str = _DEFAULT_SPRITE_COMPOSITION) -> str:
    prompt = _ascii_prompt_text(value)
    if not prompt:
        return ""

    terms = _sd_required_terms(composition)
    required = {tag.lower() for tag in (*_SD_PROMPT_REQUIRED_PREFIX, *terms)}
    parts = [part.strip() for part in prompt.split(",") if part.strip()]
    remaining = [part for part in parts if part.lower() not in required]
    return ", ".join([*_SD_PROMPT_REQUIRED_PREFIX, *terms, *remaining])


def _with_required_sprite_negative_prompt(value: Any) -> str:
    prompt = _ascii_prompt_text(value)
    parts = [part.strip() for part in prompt.split(",") if part.strip()]
    required = {tag.lower() for tag in _SPRITE_NEGATIVE_PROMPT_REQUIRED_TERMS}
    remaining = [part for part in parts if part.lower() not in required]
    return ", ".join([*remaining, *_SPRITE_NEGATIVE_PROMPT_REQUIRED_TERMS])


def _split_sprite_prompt_line(value: str, composition: str = _DEFAULT_SPRITE_COMPOSITION) -> dict[str, str]:
    text = str(value or "").strip()
    match = re.match(r"^(?:\d+[.)]\s*)?([^:：|]+)[:：|]\s*(.+)$", text)
    if match:
        return {"label": match.group(1).strip(), "prompt": _with_required_sd_prompt_prefix(match.group(2), composition)}
    return {"label": "", "prompt": _with_required_sd_prompt_prefix(text, composition)}


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


def _normalize_sprite_prompt_items(payload: Any, count: int, composition: str = _DEFAULT_SPRITE_COMPOSITION) -> list[dict[str, str]]:
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
            prompt = _with_required_sd_prompt_prefix(raw_item.get("prompt") or raw_item.get("sd_prompt") or "", composition)
        else:
            parsed = _split_sprite_prompt_line(str(raw_item), composition)
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
    positive_prompt_reference: str = "",
    composition: str = _DEFAULT_SPRITE_COMPOSITION,
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
    reference_prompt = str(positive_prompt_reference or "").strip()
    reference_block = (
        f"Positive prompt reference from user:\n{reference_prompt}\n"
        "Prefer including applicable terms from this reference in each English SD prompt, while keeping the required prefix, required terms, character consistency, and composition restriction above.\n"
        if reference_prompt
        else ""
    )
    required_terms = ", ".join(_sd_required_terms(composition))
    system_prompt = (
        "You generate visual novel character sprite generation data. "
        "Return only a valid JSON object with an items array. "
        "Each item must be an object with label and prompt. "
        "The label must be short comma-separated emotion/action tags in the requested UI language. "
        "The prompt must be a pure English Stable Diffusion style prompt, ASCII only, and must include the character name. "
        "Every prompt must start with: masterpiece, best quality, highres, official art, solo, 1 person, single character. "
        f"Every prompt must include these exact terms: {required_terms}. "
        "Each item must describe exactly one standalone sprite image, not a character sheet, not a turnaround, and not multiple views or multiple angles. "
        "Do not include markdown, explanations, or non-English text inside prompt."
    )
    user_prompt = (
        f"Character name: {character_name}\n"
        f"Character settings:\n{character_settings}\n\n"
        f"Generate {count} different sprite candidates.\n"
        f"Label language: {label_language}\n"
        "Prompt prefix: masterpiece, best quality, highres, official art, solo, 1 person, single character.\n"
        f"Required prompt terms: {required_terms}.\n"
        "Composition restriction: one standalone character sprite per image; do not write prompts for multiple views, multiple angles, turnaround sheets, reference sheets, expression sheets, or pose sheets.\n"
        f"{reference_block}"
        "Prompt requirements: consistent character design, expressive emotion and clear action.\n"
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
        "items": _normalize_sprite_prompt_items(payload, count, composition),
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


def _safe_filename_part(value: Any, fallback: str = "sprite") -> str:
    text = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", str(value or "").strip())
    text = text.strip("._-")
    return (text or fallback)[:48]


def _numeric_node_sort_key(node_id: str) -> tuple[int, str]:
    return (int(node_id), node_id) if str(node_id).isdigit() else (10**9, str(node_id))


def _cached_comfyui_api_workflow_path(source_path: Path, prompt: dict[str, dict[str, Any]]) -> Path:
    cache_dir = Path(".cache") / "comfyui-api-workflows"
    cache_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = hashlib.sha256(
        f"{source_path.resolve()}:{source_path.stat().st_mtime_ns}".encode("utf-8", errors="ignore")
    ).hexdigest()[:16]
    output_path = cache_dir / f"{source_path.stem}.{fingerprint}.api.json"
    output_path.write_text(json.dumps(prompt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


def _load_comfyui_api_workflow(workflow_path: str) -> tuple[dict[str, dict[str, Any]], str]:
    from tools.comfyui_workflow2api import convert_workflow

    source_path = Path(workflow_path)
    workflow = json.loads(source_path.read_text(encoding="utf-8"))
    result = convert_workflow(workflow)
    if result.source_format == "native":
        converted_path = _cached_comfyui_api_workflow_path(source_path, result.prompt)
        return result.prompt, converted_path.as_posix()
    return result.prompt, source_path.as_posix()


def _comfyui_api_workflow_nodes(workflow: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(workflow, dict):
        raise ValueError("ComfyUI workflow must be a JSON object")
    nodes = {str(node_id): node for node_id, node in workflow.items() if isinstance(node, dict)}
    if not nodes:
        raise ValueError("ComfyUI workflow does not contain any API-format nodes")
    return nodes


def _linked_node_id(value: Any) -> str:
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, str):
        return value
    return ""


def _infer_comfyui_prompt_node_id(nodes: dict[str, dict[str, Any]]) -> str:
    for node in nodes.values():
        class_type = str(node.get("class_type") or "").lower()
        if "ksampler" not in class_type:
            continue
        linked = _linked_node_id((node.get("inputs") or {}).get("positive"))
        if linked in nodes:
            return linked

    candidates = [
        node_id
        for node_id, node in nodes.items()
        if "cliptextencode" in str(node.get("class_type") or "").lower()
        and isinstance((node.get("inputs") or {}).get("text"), str)
    ]
    return sorted(candidates, key=_numeric_node_sort_key)[0] if candidates else ""


def _infer_comfyui_output_node_id(nodes: dict[str, dict[str, Any]]) -> str:
    candidates = [
        node_id
        for node_id, node in nodes.items()
        if str(node.get("class_type") or "").lower() in {"saveimage", "previewimage"}
    ]
    return sorted(candidates, key=_numeric_node_sort_key)[0] if candidates else ""


def _resolve_comfyui_workflow_node_ids(kwargs: dict[str, Any]) -> dict[str, Any]:
    workflow_path = str(kwargs.get("workflow_path") or "").strip()
    if not workflow_path:
        return kwargs

    workflow, api_workflow_path = _load_comfyui_api_workflow(workflow_path)
    nodes = _comfyui_api_workflow_nodes(workflow)
    resolved = dict(kwargs)
    resolved["workflow_path"] = api_workflow_path

    prompt_node_id = str(resolved.get("prompt_node_id") or "").strip()
    prompt_node = nodes.get(prompt_node_id)
    if not prompt_node or not isinstance((prompt_node.get("inputs") or {}).get("text"), str):
        inferred = _infer_comfyui_prompt_node_id(nodes)
        if not inferred:
            raise ValueError(
                f"Prompt node ID '{prompt_node_id or '(empty)'}' was not found as a text prompt node in the ComfyUI workflow, "
                "and no CLIPTextEncode node connected to a KSampler positive input could be auto-detected."
            )
        resolved["prompt_node_id"] = inferred

    output_node_id = str(resolved.get("output_node_id") or "").strip()
    if output_node_id not in nodes:
        inferred = _infer_comfyui_output_node_id(nodes)
        if not inferred:
            raise ValueError(
                f"Output node ID '{output_node_id or '(empty)'}' was not found in the ComfyUI workflow, "
                "and no SaveImage or PreviewImage node could be auto-detected."
            )
        resolved["output_node_id"] = inferred

    return resolved


def _t2i_factory_kwargs(state: BridgeState) -> tuple[str, dict[str, Any]]:
    from t2i.t2i_manager import T2IAdapterFactory

    api_config = state.config_manager.config.api_config
    provider = str(api_config.t2i_provider or "").strip().lower()
    if not provider:
        raise RuntimeError("T2I provider is not configured")
    if provider not in T2IAdapterFactory._adapters:
        raise RuntimeError(f"Unsupported T2I adapter: {provider}")

    if provider == "comfyui":
        base_kwargs = {
            "api_url": str(api_config.t2i_api_url or "").strip(),
            "work_path": str(api_config.t2i_work_path or "").strip(),
            "workflow_path": str(api_config.t2i_default_workflow_path or "").strip(),
            "prompt_node_id": str(api_config.t2i_prompt_node_id or "6").strip(),
            "output_node_id": str(api_config.t2i_output_node_id or "9").strip(),
        }
    elif provider == "stable diffusion":
        base_kwargs = {
            "api_url": str(api_config.t2i_api_url or "").strip(),
        }
    else:
        base_kwargs = {}

    if hasattr(state.config_manager, "merged_t2i_factory_kwargs"):
        base_kwargs = state.config_manager.merged_t2i_factory_kwargs(provider, base_kwargs)
    if provider == "comfyui":
        base_kwargs = _resolve_comfyui_workflow_node_ids(base_kwargs)
    return provider, base_kwargs


def _generate_sprite_prompts(state: BridgeState, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    character_name = str(payload.get("characterName") or "").strip()
    if not character_name:
        raise ValueError("characterName is required")
    count = int(payload.get("count") or 1)
    if count < 1 or count > 100:
        raise ValueError("count must be between 1 and 100")
    language = str(payload.get("language") or "zh_CN").strip()
    positive_prompt_reference = str(payload.get("positivePromptReference") or "").strip()
    composition = str(payload.get("composition") or _DEFAULT_SPRITE_COMPOSITION).strip()
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
        positive_prompt_reference=positive_prompt_reference,
        composition=composition,
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


def _generate_sprite_image(state: BridgeState, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from t2i.t2i_manager import T2IAdapterFactory

    character_name = str(payload.get("characterName") or "").strip()
    if not character_name:
        raise ValueError("characterName is required")
    prompt = _with_required_sd_prompt_prefix(payload.get("prompt"))
    if not prompt:
        raise ValueError("prompt is required")
    label = str(payload.get("label") or "").strip()
    negative_prompt = _with_required_sprite_negative_prompt(payload.get("negativePrompt"))
    seed = int(payload.get("seed") or secrets.randbelow(2**32))
    character = state.config_manager.get_character_by_name(character_name)
    if character is None:
        raise KeyError(f"character not found: {character_name}")

    provider, kwargs = _t2i_factory_kwargs(state)
    output_dir = _sprite_output_dir(state, character_name, payload.get("outputDir"))
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"ai_{_safe_filename_part(label, 'sprite')}_{int(time.time() * 1000)}.png"
    output_path = output_dir / filename

    if provider == "comfyui":
        _update_task(state, task_id, message="请稍等，生图后端正在启动中。", phase="startup", progress=0.12)
    else:
        _update_task(state, task_id, message="正在生成立绘。", phase="generate", progress=0.18)
    adapter = T2IAdapterFactory.create_adapter(provider, **kwargs)
    _update_task(state, task_id, message="正在提交立绘生成任务。", phase="generate", progress=0.28)
    generated_path = adapter.generate_image(
        prompt,
        output_path.as_posix(),
        negative_prompt=negative_prompt,
        seed=seed,
    )
    if not generated_path:
        raise RuntimeError("T2I did not return a generated image")

    result_path = Path(generated_path).as_posix()
    result = {
        "file": result_path,
        "files": [result_path],
        "label": label,
        "message": f"已生成立绘：{result_path}",
        "outputDir": output_dir.as_posix(),
        "prompt": prompt,
        "seed": seed,
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
    raw_files = payload.get("files")
    files = [str(f) for f in raw_files] if isinstance(raw_files, list) else None
    output_dir = Path(requested_output) if requested_output else input_dir / "removed_backgrounds"

    _update_task(state, task_id, message="正在批量抠出立绘。", phase="remove-background", progress=0.25)
    message = batch_remove_background(input_dir.as_posix(), requested_output or None, files=files)
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
