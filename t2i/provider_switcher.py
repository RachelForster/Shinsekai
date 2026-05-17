from __future__ import annotations

import copy
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
API_CONFIG = ROOT / "data" / "config" / "api.yaml"
COMFY_ROOT = ROOT / "data" / "t2i_bundles" / "comfyui"
COMFY_WORKFLOW = ROOT / "t2i" / "workflows" / "shinsekai_sd15_api.json"

IMAGE_API_PROFILE_KEYS = (
    "api_url",
    "api_key",
    "model",
    "size",
    "auto_size",
    "square_size",
    "portrait_size",
    "landscape_size",
    "quality",
    "response_format",
    "moderation",
    "fallback_models",
    "fallback_configs",
    "timeout_seconds",
)


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


def _copy_api_profile(config: dict) -> dict:
    return {
        key: copy.deepcopy(config[key])
        for key in IMAGE_API_PROFILE_KEYS
        if key in config
    }


def _profile_label(model: str, api_url: str) -> str:
    model_l = (model or "").strip().lower()
    if model_l == "gpt-image-2":
        return "GPT Image 2"
    if "grok" in model_l:
        return "Grok Imagine"
    if model:
        return str(model).strip()
    if api_url:
        return str(api_url).strip().rstrip("/").replace("https://", "")
    return "Image API"


def _unique_profile_name(profiles: dict, preferred: str) -> str:
    base = (preferred or "Image API").strip() or "Image API"
    if base not in profiles:
        return base
    index = 2
    while f"{base} {index}" in profiles:
        index += 1
    return f"{base} {index}"


def _ensure_api_profiles(data: dict) -> dict:
    profiles = data.get("t2i_api_profiles")
    if not isinstance(profiles, dict):
        profiles = {}
        data["t2i_api_profiles"] = profiles
    if profiles:
        return profiles

    openai = _extras(data, "openai-image")
    primary = _copy_api_profile(openai)
    primary.pop("fallback_models", None)
    fallback_configs = primary.pop("fallback_configs", None)
    if primary.get("api_url") or primary.get("api_key") or primary.get("model"):
        name = _unique_profile_name(
            profiles,
            _profile_label(
                str(primary.get("model") or ""),
                str(primary.get("api_url") or ""),
            ),
        )
        profiles[name] = primary
        data.setdefault("t2i_active_api_profile", name)

    size_defaults = {
        key: copy.deepcopy(openai[key])
        for key in (
            "size",
            "auto_size",
            "square_size",
            "portrait_size",
            "landscape_size",
            "quality",
            "response_format",
            "moderation",
            "timeout_seconds",
        )
        if key in openai
    }
    if isinstance(fallback_configs, list):
        for fallback in fallback_configs:
            if not isinstance(fallback, dict):
                continue
            profile = {**size_defaults, **_copy_api_profile(fallback)}
            profile.pop("fallback_models", None)
            profile.pop("fallback_configs", None)
            if not (profile.get("api_url") or profile.get("api_key") or profile.get("model")):
                continue
            name = _unique_profile_name(
                profiles,
                _profile_label(
                    str(profile.get("model") or ""),
                    str(profile.get("api_url") or ""),
                ),
            )
            profiles[name] = profile

    if profiles and not data.get("t2i_active_api_profile"):
        data["t2i_active_api_profile"] = next(iter(profiles))
    return profiles


def _switch_to_api_defaults(data: dict) -> None:
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


def _apply_api_profile(data: dict, profile_name: str | None = None) -> str:
    profiles = _ensure_api_profiles(data)
    if not profiles:
        _switch_to_api_defaults(data)
        return ""
    name = (profile_name or data.get("t2i_active_api_profile") or "").strip()
    if name not in profiles:
        name = next(iter(profiles))
    profile = _copy_api_profile(profiles[name])

    data["t2i_provider"] = "openai-image"
    data["t2i_work_path"] = ""
    data["t2i_api_url"] = str(profile.get("api_url") or "https://api.mcxhm.cn")
    data["t2i_default_workflow_path"] = ""
    data["t2i_prompt_node_id"] = "6"
    data["t2i_output_node_id"] = "9"
    data["t2i_active_api_profile"] = name

    openai = _extras(data, "openai-image")
    defaults = {
        "api_url": data["t2i_api_url"],
        "model": "gpt-image-2",
        "size": "auto",
        "auto_size": True,
        "square_size": "1024x1024",
        "portrait_size": "1024x1536",
        "landscape_size": "1536x1024",
        "quality": "low",
        "response_format": "b64_json",
        "moderation": "low",
        "timeout_seconds": 240,
    }
    for key, default in defaults.items():
        openai[key] = copy.deepcopy(profile.get(key, default))
    for key in ("api_key", "fallback_models", "fallback_configs"):
        if key in profile:
            openai[key] = copy.deepcopy(profile[key])
        else:
            openai.pop(key, None)
    data["t2i_api_url"] = str(openai.get("api_url") or data["t2i_api_url"])
    return name


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
    _apply_api_profile(data)


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


def list_t2i_api_profiles() -> list[str]:
    """Return saved remote image API profile names, seeding legacy config if needed."""
    data = _load_api()
    before = copy.deepcopy(data.get("t2i_api_profiles"))
    before_active = data.get("t2i_active_api_profile")
    profiles = _ensure_api_profiles(data)
    if (
        before != data.get("t2i_api_profiles")
        or before_active != data.get("t2i_active_api_profile")
    ):
        _save_api(data)
    return list(profiles.keys())


def get_active_t2i_api_profile() -> str:
    data = _load_api()
    _ensure_api_profiles(data)
    return str(data.get("t2i_active_api_profile") or "")


def switch_t2i_api_profile(profile_name: str) -> str:
    """Persist and activate a remote image API profile."""
    data = _load_api()
    active = _apply_api_profile(data, profile_name)
    _save_api(data)
    return active


def save_t2i_api_profile(profile_name: str, profile_config: dict) -> str:
    """Save/update a remote image API profile without logging secrets."""
    name = (profile_name or "").strip()
    if not name:
        raise ValueError("Profile name cannot be empty.")
    data = _load_api()
    profiles = _ensure_api_profiles(data)
    profiles[name] = _copy_api_profile(profile_config or {})
    data["t2i_active_api_profile"] = name
    _apply_api_profile(data, name)
    _save_api(data)
    return name
