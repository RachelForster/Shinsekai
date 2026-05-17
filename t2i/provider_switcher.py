from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
API_CONFIG = ROOT / "data" / "config" / "api.yaml"
COMFY_ROOT = ROOT / "data" / "t2i_bundles" / "comfyui"
COMFY_WORKFLOW = ROOT / "t2i" / "workflows" / "shinsekai_sd15_api.json"


def _load_api() -> dict:
    if not API_CONFIG.exists():
        return {}
    data = yaml.safe_load(API_CONFIG.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _save_api(data: dict) -> None:
    API_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    API_CONFIG.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _extras(data: dict, provider: str) -> dict:
    all_extras = data.setdefault("t2i_extra_configs", {})
    if not isinstance(all_extras, dict):
        all_extras = {}
        data["t2i_extra_configs"] = all_extras
    block = all_extras.setdefault(provider, {})
    if not isinstance(block, dict):
        block = {}
        all_extras[provider] = block
    return block


def _switch_to_local(data: dict) -> None:
    data["t2i_provider"] = "comfyui"
    data["t2i_work_path"] = str(COMFY_ROOT)
    data["t2i_api_url"] = "http://127.0.0.1:8188"
    data["t2i_default_workflow_path"] = str(COMFY_WORKFLOW)
    data["t2i_prompt_node_id"] = "6"
    data["t2i_output_node_id"] = "9"

    comfy = _extras(data, "comfyui")
    comfy.setdefault("auto_size", True)
    comfy.setdefault("square_size", "640x640")
    comfy.setdefault("portrait_size", "512x768")
    comfy.setdefault("landscape_size", "768x512")
    comfy.setdefault("size_node_id", "5")
    comfy.setdefault("launch_args", "--lowvram")
    comfy.setdefault("timeout_seconds", 240)


def _switch_to_api(data: dict) -> None:
    data["t2i_provider"] = "openai-image"
    data["t2i_work_path"] = ""
    openai = _extras(data, "openai-image")
    data["t2i_api_url"] = str(openai.get("api_url") or "https://api.mcxhm.cn")
    data["t2i_default_workflow_path"] = ""
    data["t2i_prompt_node_id"] = "6"
    data["t2i_output_node_id"] = "9"

    openai.setdefault("api_url", "https://api.mcxhm.cn")
    openai.setdefault("model", "gpt-image-2")
    openai.setdefault("size", "auto")
    openai.setdefault("auto_size", True)
    openai.setdefault("square_size", "1024x1024")
    openai.setdefault("portrait_size", "1024x1536")
    openai.setdefault("landscape_size", "1536x1024")
    openai.setdefault("quality", "low")
    openai.setdefault("response_format", "b64_json")
    openai.setdefault("moderation", "low")
    openai.setdefault("timeout_seconds", 240)


def switch_t2i_provider(provider: str) -> str:
    """Persist the drawing provider and return its canonical key."""
    key = (provider or "").strip().lower()
    data = _load_api()
    if key in ("local", "comfyui"):
        _switch_to_local(data)
        canonical = "comfyui"
    elif key in ("api", "openai-image", "gpt-image"):
        _switch_to_api(data)
        canonical = "openai-image"
    else:
        raise ValueError(f"Unsupported drawing provider: {provider}")
    _save_api(data)
    return canonical
