from __future__ import annotations

import os
import urllib.error

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui.settings_ui.tabs.api_tab import (
    _extract_llm_model_ids,
    _llm_models_endpoint_url,
    _llm_models_request_headers,
    _summarize_http_error,
)


def test_llm_models_endpoint_url_appends_models_path():
    assert _llm_models_endpoint_url("https://api.example.com/v1/") == (
        "https://api.example.com/v1/models"
    )


def test_llm_models_endpoint_url_uses_deepseek_official_models_path():
    assert _llm_models_endpoint_url(
        "https://api.deepseek.com/v1",
        "Deepseek",
        "sk-test",
    ) == "https://api.deepseek.com/models"


def test_llm_models_endpoint_url_does_not_trust_lookalike_deepseek_host():
    assert _llm_models_endpoint_url(
        "https://api.deepseek.com.evil/v1",
        "Custom",
        "sk-test",
    ) == "https://api.deepseek.com.evil/v1/models"


def test_llm_models_endpoint_url_uses_gemini_native_models_api():
    assert _llm_models_endpoint_url(
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "Gemini",
        "AIza test",
    ) == "https://generativelanguage.googleapis.com/v1beta/models?key=AIza+test"


def test_llm_models_endpoint_url_uses_dashscope_deployment_models_api():
    assert _llm_models_endpoint_url(
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "通义千问",
        "sk-test",
    ) == (
        "https://dashscope.aliyuncs.com/api/v1/deployments/models?"
        "page_no=1&page_size=100&version=v1.0&model_source=base"
    )


def test_llm_models_endpoint_url_uses_anthropic_models_path_once():
    assert _llm_models_endpoint_url(
        "https://api.anthropic.com",
        "Claude",
        "sk-test",
    ) == "https://api.anthropic.com/v1/models"
    assert _llm_models_endpoint_url(
        "https://api.anthropic.com/v1",
        "Claude",
        "sk-test",
    ) == "https://api.anthropic.com/v1/models"
    assert _llm_models_endpoint_url(
        "https://proxy.example.com/anthropic/v1/messages",
        "Claude",
        "sk-test",
    ) == "https://proxy.example.com/anthropic/v1/models"


def test_extract_llm_model_ids_accepts_openai_style_payload():
    assert _extract_llm_model_ids(
        {"data": [{"id": "model-a"}, {"id": "model-b"}, {"id": "model-a"}]}
    ) == ["model-a", "model-b"]


def test_extract_llm_model_ids_accepts_plain_model_list():
    assert _extract_llm_model_ids({"models": ["model-a", {"name": "model-b"}]}) == [
        "model-a",
        "model-b",
    ]


def test_extract_llm_model_ids_accepts_gemini_and_dashscope_payloads():
    assert _extract_llm_model_ids(
        {
            "models": [
                {
                    "name": "models/gemini-2.5-flash",
                    "supportedGenerationMethods": ["generateContent"],
                },
                {
                    "name": "models/gemini-embedding-001",
                    "supportedGenerationMethods": ["embedContent"],
                },
            ]
        }
    ) == ["gemini-2.5-flash"]

    assert _extract_llm_model_ids(
        {"output": {"models": [{"model_name": "qwen-plus"}, {"base_model": "qwen-max"}]}}
    ) == ["qwen-plus", "qwen-max"]


def test_llm_models_request_headers_use_provider_auth_conventions():
    openai_headers = _llm_models_request_headers(
        "ChatGPT", "https://api.openai.com/v1", "sk-test"
    )
    assert openai_headers["Authorization"] == "Bearer sk-test"
    assert "Windows NT 10.0" in openai_headers["User-Agent"]

    claude_headers = _llm_models_request_headers(
        "Claude", "https://api.anthropic.com/v1", "sk-ant"
    )
    assert claude_headers["x-api-key"] == "sk-ant"
    assert "anthropic-version" in claude_headers

    gemini_headers = _llm_models_request_headers(
        "Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "AIza"
    )
    assert "Authorization" not in gemini_headers


def test_summarize_http_error_keeps_cloudflare_detail_compact():
    err = urllib.error.HTTPError(
        "https://api.example.com/models",
        403,
        "Forbidden",
        {},
        None,
    )
    summary = _summarize_http_error(
        err,
        (
            '{"title":"Error 1010: Access denied",'
            '"detail":"The site owner has blocked access based on your browser signature.",'
            '"error_code":1010,'
            '"error_name":"browser_signature_banned"}'
        ),
    )

    assert summary.startswith("HTTP 403: Error 1010: Access denied")
    assert "browser_signature_banned" in summary
    assert len(summary) < 180


def test_summarize_http_error_handles_openai_style_error_object():
    err = urllib.error.HTTPError(
        "https://api.example.com/models",
        401,
        "Unauthorized",
        {},
        None,
    )
    summary = _summarize_http_error(
        err,
        '{"error":{"message":"Incorrect API key provided.","type":"invalid_request_error"}}',
    )

    assert summary == "HTTP 401: invalid_request_error; Incorrect API key provided."
