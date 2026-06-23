from __future__ import annotations


def normalize_claude_base_url_for_sdk(base_url: str | None) -> str | None:
    """Return the Anthropic SDK base URL without endpoint/version suffixes."""
    if base_url is None:
        return None

    base = str(base_url).strip().rstrip("/")
    if not base:
        return base

    low = base.lower()
    for suffix in ("/v1/messages", "/messages", "/v1"):
        if low.endswith(suffix):
            normalized = base[: -len(suffix)].rstrip("/")
            return normalized or base
    return base


def claude_messages_endpoint_url(base_url: str) -> str:
    base = normalize_claude_base_url_for_sdk(base_url)
    base = (base or "").strip().rstrip("/")
    if not base:
        raise ValueError("请先填写 LLM 基础地址和 API Key。")
    return f"{base}/v1/messages"


def claude_models_endpoint_url(base_url: str) -> str:
    base = normalize_claude_base_url_for_sdk(base_url)
    base = (base or "").strip().rstrip("/")
    if not base:
        raise ValueError("请先填写 LLM 基础地址和 API Key。")
    return f"{base}/v1/models"
