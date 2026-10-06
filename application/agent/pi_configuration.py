"""Resolve Pi runtime and model references from existing Shinsekai configuration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlsplit

from ai.llm.claude_url import normalize_claude_base_url_for_sdk
from core.agent.ipc import fault
from core.agent.pi_runtime import PiRuntime, PiRuntimeManager, PI_VERSION
from core.paths import project_root, resource_path
from sdk.agent import AgentBackendConfig

_COMPATIBLE_PROVIDERS = {"ChatGPT", "Deepseek", "Gemini", "豆包", "通义千问", "Ollama"}


@dataclass(frozen=True)
class PiModelBinding:
    reference: str
    provider: str
    model: dict
    api_key: str = field(repr=False)


def resolve_pi_model(config_manager, *, provider: str | None = None) -> PiModelBinding:
    if provider is None:
        provider, model_id, base_url, api_key = config_manager.get_llm_api_config()
    else:
        base_url, model_id, api_key = config_manager.update_llm_info(provider)
    provider, model_id, base_url = (
        str(value or "").strip() for value in (provider, model_id, base_url)
    )
    if provider == "Claude":
        api = "anthropic-messages"
        base_url = normalize_claude_base_url_for_sdk(base_url)
    elif provider in _COMPATIBLE_PROVIDERS:
        api = "openai-completions"
    else:
        raise fault(
            "CAPABILITY_UNSUPPORTED", "Configured LLM provider has no Pi API mapping"
        )
    url = urlsplit(base_url)
    if (
        not model_id
        or url.scheme not in ("http", "https")
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise fault(
            "INVALID_REQUEST", "Configure a model and a plain LLM API base URL first"
        )
    api_key = str(api_key or "").strip()
    if not api_key and provider == "Ollama":
        api_key = "ollama"
    if not api_key:
        raise fault("AUTH_REQUIRED", "Configure the LLM provider API key first")
    context_window = max(
        4096, int(config_manager.config.api_config.max_context_tokens or 32768)
    )
    model = {
        "id": model_id,
        "baseUrl": base_url,
        "api": api,
        "contextWindow": context_window,
        "maxTokens": min(4096, context_window // 4),
        "reasoning": False,
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
    }
    fingerprint = hashlib.sha256(
        json.dumps([provider, model], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:24]
    return PiModelBinding("config:llm:" + fingerprint, provider, model, api_key)


@dataclass(frozen=True)
class PiAgentSetup:
    backend: AgentBackendConfig
    model_ref: str
    worker_environment: Callable[[], Mapping[str, str]] = field(repr=False)


def prepare_pi_agent(
    config_manager,
    *,
    root: str | Path | None = None,
    runtime: PiRuntime | None = None,
    update_task: Callable[..., None] = lambda **_: None,
    is_interrupted: Callable[[], bool] = lambda: False,
    policy_paths: Mapping[str, str | Path] | None = None,
    skill_paths: Mapping[str, str | Path] | None = None,
) -> PiAgentSetup:
    binding = resolve_pi_model(config_manager)
    root = Path(root or project_root() / "data" / "agent").resolve()
    runtime = runtime or PiRuntimeManager(root / "runtimes" / "pi").ensure(
        update_task=update_task, is_interrupted=is_interrupted
    )
    if runtime.version != PI_VERSION:
        raise fault(
            "CAPABILITY_UNSUPPORTED",
            "Pi runtime version is not supported by this adapter",
        )

    def environment():
        current = resolve_pi_model(config_manager, provider=binding.provider)
        if current.reference != binding.reference:
            raise fault(
                "SESSION_BACKEND_MISMATCH",
                "LLM model configuration changed; create a new Pi service",
            )
        return {"SHINSEKAI_PI_API_KEY": current.api_key}

    return PiAgentSetup(
        backend=AgentBackendConfig(
            backend_id="pi",
            backend_version="1",
            runtime_ref=str(runtime.executable.resolve()),
            state_ref=str(root / "pi-sessions"),
            credential_ref="config:llm:" + binding.provider,
            options={
                "piVersion": PI_VERSION,
                "models": {binding.reference: binding.model},
                "policies": {
                    key: str(Path(value).resolve())
                    for key, value in (
                        policy_paths
                        or {
                            "agent:default": resource_path(
                                "assets/agent/system-policy.md"
                            )
                        }
                    ).items()
                },
                "skills": {
                    key: str(Path(value).resolve())
                    for key, value in (skill_paths or {}).items()
                },
            },
        ),
        model_ref=binding.reference,
        worker_environment=environment,
    )
