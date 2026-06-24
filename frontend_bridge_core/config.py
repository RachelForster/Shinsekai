from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from config.tts_provider_config import (
    default_tts_work_path,
    installed_tts_bundle_paths,
    is_http_url,
    normalize_tts_provider,
    requires_tts_work_path,
    tts_server_url_or_default,
    uses_shared_tts_server_config,
)
from llm.claude_url import claude_messages_endpoint_url, claude_models_endpoint_url
from .security import host_matches, validated_http_url
from .state import BridgeState, _jsonify

_MODEL_REQUEST_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 Shinsekai/1.0"
)
_IMAGE_ONLY_MODEL_MARKERS = (
    "dall-e",
    "dalle",
    "flux",
    "gpt-image",
    "imagen",
    "midjourney",
    "qwen-image",
    "sdxl",
    "stable-diffusion",
)
_TTS_LABEL_PREFS: tuple[tuple[str, str], ...] = (
    ("genie-tts", "Genie TTS"),
    ("kaggle-gpt-sovits", "Kaggle GPT-SoVITS"),
    ("gpt-sovits", "GPT SoVITS"),
    ("index-tts", "IndexTTS"),
    ("cosyvoice", "CosyVoice"),
)
_PREFERRED_T2I_KEYS_LOWER: tuple[str, ...] = ("comfyui", "stable diffusion")


class LlmModelDiscoveryHttpError(RuntimeError):
    def __init__(self, status_code: int, url: str, detail: str) -> None:
        self.status_code = status_code
        self.url = url
        message = detail.strip() or f"HTTP {status_code}"
        super().__init__(message)


class LlmModelDiscoveryConnectionError(RuntimeError):
    def __init__(self, url: str, detail: str) -> None:
        self.url = url
        super().__init__(detail.strip() or "connection failed")


def _adapter_schema(adapter_class: Any | None) -> dict[str, Any]:
    if adapter_class is None:
        return {}
    getter = getattr(adapter_class, "get_config_schema", None)
    if not callable(getter):
        return {}
    try:
        schema = getter()
    except Exception:
        return {}
    return _jsonify(schema) if isinstance(schema, dict) else {}


def _adapter_option(value: str, label: str, adapter_class: Any | None = None) -> dict[str, Any]:
    return {
        "label": str(label or value),
        "schema": _adapter_schema(adapter_class),
        "value": str(value),
    }


def _adapter_catalog() -> dict[str, list[dict[str, Any]]]:
    """Expose the same registered adapter choices the PyQt settings tab uses."""
    try:
        from asr.asr_manager import ASRAdapterFactory
        from llm.constants import LLM_BASE_URLS
        from llm.llm_manager import LLMAdapterFactory
        from t2i.t2i_manager import T2IAdapterFactory
        from tts.tts_manager import TTSAdapterFactory
    except Exception:
        return {"asr": [], "llm": [], "t2i": [], "tts": []}

    llm_adapters = dict(LLMAdapterFactory._adapters)
    llm: list[dict[str, Any]] = []
    for key in LLM_BASE_URLS.keys():
        if key in llm_adapters:
            llm.append(_adapter_option(key, key, llm_adapters[key]))
    for key in sorted(llm_adapters.keys(), key=str.lower):
        if key not in {item["value"] for item in llm}:
            llm.append(_adapter_option(key, key, llm_adapters[key]))

    tts_adapters = dict(TTSAdapterFactory._adapters)
    tts: list[dict[str, Any]] = [_adapter_option("none", "不使用", None)]
    by_lower = {key.lower(): key for key in tts_adapters}
    seen: set[str] = set()
    for slug, label in _TTS_LABEL_PREFS:
        canonical = by_lower.get(slug)
        if canonical:
            tts.append(_adapter_option(canonical, label, tts_adapters[canonical]))
            seen.add(canonical)
    for key in sorted(tts_adapters.keys(), key=str.lower):
        if key not in seen:
            tts.append(_adapter_option(key, key.replace("-", " ").title(), tts_adapters[key]))

    t2i_adapters = dict(T2IAdapterFactory._adapters)
    t2i_by_lower = {key.lower(): key for key in t2i_adapters}
    t2i: list[dict[str, Any]] = []
    fixed_t2i_labels = {"comfyui": "ComfyUI", "stable diffusion": "Stable Diffusion"}
    for preferred in _PREFERRED_T2I_KEYS_LOWER:
        canonical = t2i_by_lower.get(preferred)
        if canonical:
            t2i.append(
                _adapter_option(
                    canonical,
                    fixed_t2i_labels.get(canonical.lower(), canonical.replace("-", " ").title()),
                    t2i_adapters[canonical],
                )
            )
    for key in sorted(t2i_adapters.keys(), key=str.lower):
        if key not in {item["value"] for item in t2i}:
            t2i.append(
                _adapter_option(
                    key,
                    fixed_t2i_labels.get(key.lower(), key.replace("-", " ").title()),
                    t2i_adapters[key],
                )
            )

    asr_adapters = dict(ASRAdapterFactory._adapters)
    asr_labels = {"faster_whisper": "faster-whisper", "realtime_stt": "RealtimeSTT", "vosk": "Vosk"}
    asr: list[dict[str, Any]] = []
    if "vosk" in asr_adapters:
        asr.append(_adapter_option("vosk", asr_labels["vosk"], asr_adapters["vosk"]))
    for key in sorted(k for k in asr_adapters.keys() if k != "vosk"):
        asr.append(_adapter_option(key, asr_labels.get(key, key), asr_adapters[key]))

    return {"asr": asr, "llm": llm, "t2i": t2i, "tts": tts}


def _app_config_response(state: BridgeState) -> dict[str, Any]:
    payload = _jsonify(state.config_manager.config)
    if not isinstance(payload, dict):
        return {}
    project_root = state.app_root_dir or None
    try:
        from config.mirror_env import system_config_payload_with_resolved_mirrors

        payload["system_config"] = system_config_payload_with_resolved_mirrors(state.config_manager.config.system_config)
    except Exception:
        pass
    api_config = payload.get("api_config")
    tts_bundle_paths = installed_tts_bundle_paths(project_root)
    if isinstance(api_config, dict):
        provider = str(api_config.get("llm_provider") or "Deepseek").strip() or "Deepseek"
        if not str(api_config.get("llm_base_url") or "").strip():
            try:
                from llm.constants import LLM_BASE_URLS

                api_config["llm_base_url"] = str(LLM_BASE_URLS.get(provider) or "")
            except Exception:
                pass
        llm_model = api_config.get("llm_model")
        if not isinstance(llm_model, dict):
            llm_model = {}
            api_config["llm_model"] = llm_model
        tts_provider = normalize_tts_provider(str(api_config.get("tts_provider") or ""))
        api_config["tts_provider"] = tts_provider
        api_config["gpt_sovits_url"] = tts_server_url_or_default(
            tts_provider,
            str(api_config.get("gpt_sovits_url") or ""),
        )
        api_config["gpt_sovits_api_path"] = default_tts_work_path(
            tts_provider,
            str(api_config.get("gpt_sovits_api_path") or ""),
            project_root,
        )
    if tts_bundle_paths:
        payload["tts_bundle_installed_paths"] = tts_bundle_paths
    payload["adapter_catalog"] = _adapter_catalog()
    return payload


def _contains_quotes(value: str) -> bool:
    return '"' in value or "'" in value


def _provider_map_value(mapping: dict[str, str], provider: str) -> str:
    return str((mapping or {}).get(provider, "") or "").strip()


def _normalize_t2i_provider(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "comfyui"
    try:
        from t2i.t2i_manager import T2IAdapterFactory

        low = raw.lower()
        for key in T2IAdapterFactory._adapters:
            if key.lower() == low:
                return key
    except Exception:
        pass
    return raw


def _validate_api_config_for_save(config: Any) -> None:
    provider = str(config.llm_provider or "").strip()
    base_url = str(config.llm_base_url or "").strip()
    api_key = _provider_map_value(config.llm_api_key, provider)
    model = _provider_map_value(config.llm_model, provider)
    if not provider or not base_url or not api_key or not model:
        raise ValueError("服务商、基础地址、API Key 和模型 ID 都需要填写。")
    if _contains_quotes(base_url):
        raise ValueError("LLM API 基础网址不能包含引号。")

    tts_provider = normalize_tts_provider(config.tts_provider)
    if not uses_shared_tts_server_config(tts_provider):
        return

    tts_url = str(config.gpt_sovits_url or "").strip()
    tts_path = str(config.gpt_sovits_api_path or "").strip()
    if not tts_url:
        raise ValueError("当前 TTS 引擎需要填写 URL。")
    if _contains_quotes(tts_url) or _contains_quotes(tts_path):
        raise ValueError("TTS URL 和服务启动路径不能包含引号。")
    if not is_http_url(tts_url):
        raise ValueError("TTS URL 必须是有效的 http(s) URL。")
    if requires_tts_work_path(tts_provider) and not tts_path:
        raise ValueError("本地 TTS 引擎需要填写服务启动路径。")
    if tts_path and tts_provider != "kaggle-gpt-sovits" and not Path(tts_path).expanduser().is_dir():
        raise ValueError("TTS 服务启动路径必须是已存在的目录。")


def _save_api_config(state: BridgeState, payload: dict[str, Any]) -> Any:
    from config.schema import ApiConfig

    config = ApiConfig.model_validate(payload).model_copy(deep=True)
    config.tts_provider = normalize_tts_provider(config.tts_provider)
    config.t2i_provider = _normalize_t2i_provider(config.t2i_provider)
    config.gpt_sovits_url = tts_server_url_or_default(config.tts_provider, config.gpt_sovits_url)
    if config.tts_provider == "kaggle-gpt-sovits":
        config.gpt_sovits_api_path = ""
    else:
        config.gpt_sovits_api_path = default_tts_work_path(
            config.tts_provider,
            config.gpt_sovits_api_path,
            state.app_root_dir or None,
        )
    _validate_api_config_for_save(config)
    state.config_manager.config.api_config = config
    state.config_manager.save_api_config()
    return config


def _llm_model_provider_kind(provider: str, base_url: str) -> str:
    low_provider = provider.strip().lower()
    if "gemini" in low_provider or _base_url_host_matches(base_url, {"generativelanguage.googleapis.com"}):
        return "gemini"
    if "deepseek" in low_provider or _base_url_host_matches(base_url, {"api.deepseek.com"}):
        return "deepseek"
    if low_provider == "claude" or "claude" in low_provider or _base_url_host_matches(base_url, {"anthropic.com"}):
        return "anthropic"
    if (
        _base_url_host_matches(base_url, {"dashscope.aliyuncs.com"})
        or "通义" in low_provider
        or "qwen" in low_provider
        or "dashscope" in low_provider
    ):
        return "dashscope"
    return "openai_compatible"


def _base_url_host_matches(base_url: str, allowed_hosts: set[str]) -> bool:
    try:
        parsed = urllib.parse.urlsplit(str(base_url or "").strip())
    except ValueError:
        return False
    return parsed.hostname is not None and host_matches(parsed.hostname, allowed_hosts)


def _openai_models_endpoint(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if not base:
        raise ValueError("请先填写 LLM 基础地址和 API Key。")
    if base.lower().endswith("/models"):
        return _validated_llm_endpoint(base)
    return _validated_llm_endpoint(f"{base}/models")


def _validated_llm_endpoint(endpoint: str) -> str:
    return validated_http_url(
        endpoint,
        allow_localhost=True,
        allow_private_hosts=True,
        field="LLM endpoint",
    )


def _llm_models_endpoint(provider: str, base_url: str, api_key: str) -> str:
    kind = _llm_model_provider_kind(provider, base_url)
    base = base_url.strip().rstrip("/")
    if kind == "anthropic":
        return _validated_llm_endpoint(claude_models_endpoint_url(base))
    if kind == "gemini" and _base_url_host_matches(base, {"generativelanguage.googleapis.com"}):
        marker_ix = base.lower().rfind("/openai")
        if marker_ix >= 0:
            base = base[:marker_ix]
        if not base.lower().endswith("/v1beta"):
            base = "https://generativelanguage.googleapis.com/v1beta"
        return _validated_llm_endpoint(f"{base}/models?{urllib.parse.urlencode({'key': api_key.strip()})}")
    if kind == "deepseek" and _base_url_host_matches(base, {"api.deepseek.com"}) and base.lower().endswith("/v1"):
        base = base[:-3]
    if kind == "dashscope":
        low_base = base.lower()
        query = urllib.parse.urlencode(
            {"page_no": 1, "page_size": 100, "version": "v1.0", "model_source": "base"}
        )
        if low_base.endswith("/compatible-mode/v1"):
            base = base[: -len("/compatible-mode/v1")] + "/api/v1"
        if base.lower().endswith("/api/v1"):
            return _validated_llm_endpoint(f"{base}/deployments/models?{query}")
    return _openai_models_endpoint(base)


def _openai_chat_endpoint(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if not base:
        raise ValueError("请先填写 LLM 基础地址和 API Key。")
    if base.lower().endswith("/chat/completions"):
        return _validated_llm_endpoint(base)
    return _validated_llm_endpoint(f"{base}/chat/completions")


def _anthropic_messages_endpoint(base_url: str) -> str:
    return _validated_llm_endpoint(claude_messages_endpoint_url(base_url))


def _llm_model_request_headers(provider: str, base_url: str, api_key: str) -> dict[str, str]:
    key = api_key.strip()
    if not key:
        raise ValueError("请先填写 LLM 基础地址和 API Key。")
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": _MODEL_REQUEST_USER_AGENT,
    }
    kind = _llm_model_provider_kind(provider, base_url)
    if kind == "gemini" and _base_url_host_matches(base_url, {"generativelanguage.googleapis.com"}):
        return headers
    if kind == "anthropic":
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
        headers["Content-Type"] = "application/json"
        return headers
    headers["Authorization"] = f"Bearer {key}"
    if kind == "dashscope":
        headers["Content-Type"] = "application/json"
    return headers


def _llm_chat_request_headers(provider: str, base_url: str, api_key: str) -> dict[str, str]:
    headers = _llm_model_request_headers(provider, base_url, api_key)
    kind = _llm_model_provider_kind(provider, base_url)
    if kind == "gemini":
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    return headers


def _request_json(endpoint: str, headers: dict[str, str], payload: dict[str, Any], *, timeout: int = 20) -> Any:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise LlmModelDiscoveryHttpError(exc.code, endpoint, detail or str(exc.reason or exc)) from exc
    except urllib.error.URLError as exc:
        raise LlmModelDiscoveryConnectionError(endpoint, str(exc.reason or exc)) from exc
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON response: {exc}") from exc


def _test_llm_connection(payload: dict[str, Any]) -> dict[str, str]:
    provider = str(payload.get("provider") or "").strip()
    base_url = str(payload.get("baseUrl") or "").strip()
    api_key = str(payload.get("apiKey") or "").strip()
    model = str(payload.get("model") or "").strip()
    if not base_url or not api_key:
        raise ValueError("请先填写 LLM 基础地址和 API Key。")
    if not model:
        raise ValueError("请先填写 LLM 模型 ID。")

    kind = _llm_model_provider_kind(provider, base_url)
    if kind == "anthropic":
        endpoint = _anthropic_messages_endpoint(base_url)
        headers = _llm_model_request_headers(provider, base_url, api_key)
        _request_json(
            endpoint,
            headers,
            {
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "ping"}],
                "model": model,
            },
        )
        return {"message": "LLM 连通检测通过。"}

    endpoint = _openai_chat_endpoint(base_url)
    headers = _llm_chat_request_headers(provider, base_url, api_key)
    _request_json(
        endpoint,
        headers,
        {
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "ping"}],
            "model": model,
            "stream": False,
        },
    )
    return {"message": "LLM 连通检测通过。"}


def _iter_llm_model_items(payload: Any):
    if isinstance(payload, list):
        yield from payload
        return
    if not isinstance(payload, dict):
        return
    for key in ("data", "models", "items", "deployments"):
        raw = payload.get(key)
        if isinstance(raw, list):
            yield from raw
        elif isinstance(raw, dict):
            yield from _iter_llm_model_items(raw)
    for key in ("output", "result"):
        raw = payload.get(key)
        if isinstance(raw, (dict, list)):
            yield from _iter_llm_model_items(raw)


def _llm_model_id_is_image_only(model_id: str) -> bool:
    low = model_id.strip().removeprefix("models/").lower()
    if any(marker in low for marker in _IMAGE_ONLY_MODEL_MARKERS):
        return True
    parts = [part for part in low.replace("_", "-").replace(".", "-").split("-") if part]
    return "image" in parts and (
        "generation" in parts or "preview" in parts or low.startswith("gemini-")
    )


def _llm_model_item_supports_chat(item: dict[str, Any]) -> bool:
    actions = item.get("supportedGenerationMethods") or item.get("supportedActions")
    if isinstance(actions, list):
        normalized = {str(action).strip().lower() for action in actions}
        return bool({"generatecontent", "chat.completions", "chat"} & normalized)
    endpoints = item.get("supported_endpoint_types") or item.get("supportedEndpointTypes")
    if isinstance(endpoints, list):
        normalized = {str(endpoint).strip().lower() for endpoint in endpoints}
        if any("chat" in endpoint or endpoint == "responses" for endpoint in normalized):
            return True
        if any("image" in endpoint for endpoint in normalized):
            return False
    return True


def _modalities_to_tags(input_modalities: Any, output_modalities: Any) -> list[str]:
    def _as_set(raw: Any) -> set[str]:
        if isinstance(raw, list):
            return {str(item).strip().lower() for item in raw if str(item).strip()}
        if isinstance(raw, str) and raw.strip():
            return {
                part.strip().lower()
                for part in raw.replace("+", ",").replace("->", ",").split(",")
                if part.strip()
            }
        return set()

    inputs = _as_set(input_modalities)
    outputs = _as_set(output_modalities)
    tags: list[str] = []
    if "text" in outputs or "text" in inputs or not outputs:
        tags.append("text")
    if "image" in inputs:
        tags.append("vision")
    if "file" in inputs:
        tags.append("file")
    if "audio" in inputs:
        tags.append("audio")
    if "video" in inputs:
        tags.append("video")
    if "image" in outputs:
        tags.append("image_out")
    out: list[str] = []
    for tag in tags or ["unknown"]:
        if tag not in out:
            out.append(tag)
    return out


def _llm_model_option_from_item(item: Any) -> dict[str, Any] | None:
    if isinstance(item, str):
        model_id = item.strip()
        if not model_id or _llm_model_id_is_image_only(model_id):
            return None
        return {"id": model_id, "tags": ["text"]}
    if not isinstance(item, dict) or not _llm_model_item_supports_chat(item):
        return None
    model_id = ""
    for key in ("id", "model", "model_id", "modelId", "model_name", "modelName", "name", "deployed_model", "base_model"):
        model_id = str(item.get(key) or "").strip()
        if model_id:
            break
    if model_id.startswith("models/"):
        model_id = model_id.split("/", 1)[1].strip()
    if not model_id or _llm_model_id_is_image_only(model_id):
        return None
    arch = item.get("architecture")
    arch = arch if isinstance(arch, dict) else {}
    tags = _modalities_to_tags(arch.get("input_modalities"), arch.get("output_modalities"))
    return {"id": model_id, "tags": tags}


def _fetch_llm_models(payload: dict[str, Any]) -> list[dict[str, Any]]:
    provider = str(payload.get("provider") or "").strip()
    base_url = str(payload.get("baseUrl") or "").strip()
    api_key = str(payload.get("apiKey") or "").strip()
    if not base_url or not api_key:
        raise ValueError("请先填写 LLM 基础地址和 API Key。")
    endpoint = _llm_models_endpoint(provider, base_url, api_key)
    headers = _llm_model_request_headers(provider, base_url, api_key)
    request = urllib.request.Request(endpoint, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise LlmModelDiscoveryHttpError(exc.code, endpoint, detail or str(exc.reason or exc)) from exc
    except urllib.error.URLError as exc:
        raise LlmModelDiscoveryConnectionError(endpoint, str(exc.reason or exc)) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON response: {exc}") from exc
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _iter_llm_model_items(data):
        option = _llm_model_option_from_item(item)
        if option is None or option["id"] in seen:
            continue
        seen.add(option["id"])
        out.append(option)
    return out
