from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from llm.constants import LLM_BASE_URLS


ROOT = Path(__file__).resolve().parents[1]
API_CONFIG = ROOT / "data" / "config" / "api.yaml"

LLM_PROFILE_KEYS = (
    "provider",
    "base_url",
    "model",
    "api_key",
    "is_streaming",
    "temperature",
    "repetition_penalty",
    "presence_penalty",
    "frequency_penalty",
    "max_context_tokens",
    "extra_config",
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


def _copy_profile(config: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(config[key])
        for key in LLM_PROFILE_KEYS
        if key in config
    }


def _unique_profile_name(profiles: dict, preferred: str) -> str:
    base = (preferred or "LLM API").strip() or "LLM API"
    if base not in profiles:
        return base
    index = 2
    while f"{base} {index}" in profiles:
        index += 1
    return f"{base} {index}"


def _profile_label(provider: str, model: str, base_url: str) -> str:
    provider = (provider or "").strip()
    model = (model or "").strip()
    if provider and model:
        return f"{provider} - {model}"
    if provider:
        return provider
    if model:
        return model
    if base_url:
        return str(base_url).strip().rstrip("/").replace("https://", "")
    return "LLM API"


def _profile_from_provider(data: dict, provider: str, *, active: bool) -> dict[str, Any]:
    models = data.get("llm_model") if isinstance(data.get("llm_model"), dict) else {}
    keys = data.get("llm_api_key") if isinstance(data.get("llm_api_key"), dict) else {}
    extras = (
        data.get("llm_extra_configs")
        if isinstance(data.get("llm_extra_configs"), dict)
        else {}
    )
    base_url = (
        str(data.get("llm_base_url") or "")
        if active
        else str(LLM_BASE_URLS.get(provider, "") or "")
    )
    profile = {
        "provider": provider,
        "base_url": base_url,
        "model": str(models.get(provider, "") or ""),
        "api_key": str(keys.get(provider, "") or ""),
        "is_streaming": bool(data.get("is_streaming", True)),
        "temperature": float(data.get("temperature", 0.7) or 0.7),
        "repetition_penalty": float(data.get("repetition_penalty", 1.0) or 1.0),
        "presence_penalty": float(data.get("presence_penalty", 0.0) or 0.0),
        "frequency_penalty": float(data.get("frequency_penalty", 0.0) or 0.0),
        "max_context_tokens": int(data.get("max_context_tokens", 128000) or 128000),
        "extra_config": copy.deepcopy(extras.get(provider, {}) or {}),
    }
    return profile


def _provider_order(data: dict) -> list[str]:
    active = str(data.get("llm_provider") or "").strip()
    models = data.get("llm_model") if isinstance(data.get("llm_model"), dict) else {}
    keys = data.get("llm_api_key") if isinstance(data.get("llm_api_key"), dict) else {}
    seen: set[str] = set()
    out: list[str] = []
    for provider in [active, *models.keys(), *keys.keys()]:
        provider = str(provider or "").strip()
        if provider and provider not in seen:
            out.append(provider)
            seen.add(provider)
    return out


def _ensure_llm_profiles(data: dict) -> dict:
    profiles = data.get("llm_api_profiles")
    if not isinstance(profiles, dict):
        profiles = {}
        data["llm_api_profiles"] = profiles
    if profiles:
        return profiles

    active_provider = str(data.get("llm_provider") or "").strip()
    for provider in _provider_order(data):
        profile = _profile_from_provider(
            data,
            provider,
            active=(provider == active_provider),
        )
        if not (profile.get("provider") or profile.get("model") or profile.get("api_key")):
            continue
        name = _unique_profile_name(
            profiles,
            _profile_label(
                str(profile.get("provider") or ""),
                str(profile.get("model") or ""),
                str(profile.get("base_url") or ""),
            ),
        )
        profiles[name] = profile
        if provider == active_provider:
            data.setdefault("llm_active_api_profile", name)

    if profiles and not data.get("llm_active_api_profile"):
        data["llm_active_api_profile"] = next(iter(profiles))
    return profiles


def _apply_llm_profile(data: dict, profile_name: str | None = None) -> str:
    profiles = _ensure_llm_profiles(data)
    if not profiles:
        return ""
    name = (profile_name or data.get("llm_active_api_profile") or "").strip()
    if name not in profiles:
        name = next(iter(profiles))
    profile = _copy_profile(profiles[name])
    provider = str(profile.get("provider") or data.get("llm_provider") or "").strip()
    if not provider:
        raise ValueError(f"LLM profile '{name}' has no provider.")

    data["llm_provider"] = provider
    data["llm_base_url"] = str(profile.get("base_url") or "")
    data["llm_active_api_profile"] = name

    models = data.get("llm_model") if isinstance(data.get("llm_model"), dict) else {}
    keys = data.get("llm_api_key") if isinstance(data.get("llm_api_key"), dict) else {}
    extras = (
        data.get("llm_extra_configs")
        if isinstance(data.get("llm_extra_configs"), dict)
        else {}
    )
    models[provider] = str(profile.get("model") or "")
    keys[provider] = str(profile.get("api_key") or "")
    extras[provider] = copy.deepcopy(profile.get("extra_config") or {})
    data["llm_model"] = models
    data["llm_api_key"] = keys
    data["llm_extra_configs"] = extras

    for key, default in (
        ("is_streaming", True),
        ("temperature", 0.7),
        ("repetition_penalty", 1.0),
        ("presence_penalty", 0.0),
        ("frequency_penalty", 0.0),
        ("max_context_tokens", 128000),
    ):
        if key in profile:
            data[key] = copy.deepcopy(profile.get(key, default))
    return name


def list_llm_api_profiles() -> list[str]:
    """Return saved dialog API profile names, seeding legacy config if needed."""
    data = _load_api()
    before = copy.deepcopy(data.get("llm_api_profiles"))
    before_active = data.get("llm_active_api_profile")
    profiles = _ensure_llm_profiles(data)
    if (
        before != data.get("llm_api_profiles")
        or before_active != data.get("llm_active_api_profile")
    ):
        _save_api(data)
    return list(profiles.keys())


def get_active_llm_api_profile() -> str:
    data = _load_api()
    _ensure_llm_profiles(data)
    return str(data.get("llm_active_api_profile") or "")


def switch_llm_api_profile(profile_name: str) -> str:
    """Persist and activate a dialog API profile."""
    data = _load_api()
    active = _apply_llm_profile(data, profile_name)
    _save_api(data)
    return active


def save_llm_api_profile(profile_name: str, profile_config: dict[str, Any]) -> str:
    """Save/update a dialog API profile without logging secrets."""
    name = (profile_name or "").strip()
    if not name:
        raise ValueError("Profile name cannot be empty.")
    data = _load_api()
    profiles = _ensure_llm_profiles(data)
    profiles[name] = _copy_profile(profile_config or {})
    data["llm_active_api_profile"] = name
    _apply_llm_profile(data, name)
    _save_api(data)
    return name
