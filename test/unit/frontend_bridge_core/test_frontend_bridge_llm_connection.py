from __future__ import annotations

import json
import urllib.error
from io import BytesIO
from unittest import mock

import pytest

from frontend_bridge_core.config import (
    LlmModelDiscoveryHttpError,
    _openai_chat_endpoint,
    _test_llm_connection,
)
from sdk.exception.presenter import format_llm_exception_message


def test_openai_chat_endpoint_appends_chat_completions_without_models_path():
    assert _openai_chat_endpoint("http://127.0.0.1:1234/v1") == (
        "http://127.0.0.1:1234/v1/chat/completions"
    )


def test_llm_connection_test_posts_minimal_chat_request():
    response = mock.Mock()
    response.__enter__ = mock.Mock(return_value=response)
    response.__exit__ = mock.Mock(return_value=False)
    response.read.return_value = b'{"id":"chatcmpl-test"}'

    with mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
        result = _test_llm_connection(
            {
                "apiKey": "sk-test",
                "baseUrl": "http://127.0.0.1:1234/v1",
                "model": "local-model",
                "provider": "Local",
            }
        )

    assert result == {"message": "LLM 连通检测通过。"}
    request = urlopen.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:1234/v1/chat/completions"
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["model"] == "local-model"
    assert payload["messages"] == [{"role": "user", "content": "ping"}]


def test_gemini_connection_test_uses_openai_compatible_chat_api():
    response = mock.Mock()
    response.__enter__ = mock.Mock(return_value=response)
    response.__exit__ = mock.Mock(return_value=False)
    response.read.return_value = b'{"id":"chatcmpl-gemini"}'

    with mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
        _test_llm_connection(
            {
                "apiKey": "gemini-key",
                "baseUrl": "https://generativelanguage.googleapis.com/v1beta/openai",
                "model": "gemini-2.5-flash",
                "provider": "Gemini",
            }
        )

    request = urlopen.call_args.args[0]
    assert request.full_url == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert request.headers["Authorization"] == "Bearer gemini-key"
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["model"] == "gemini-2.5-flash"


def test_llm_connection_error_uses_presenter_balance_message():
    http_error = urllib.error.HTTPError(
        "https://api.example.test/v1/chat/completions",
        402,
        "Payment Required",
        {},
        BytesIO(b'{"error":{"message":"insufficient balance"}}'),
    )

    with mock.patch("urllib.request.urlopen", side_effect=http_error):
        with pytest.raises(LlmModelDiscoveryHttpError) as exc_info:
            _test_llm_connection(
                {
                    "apiKey": "sk-test",
                    "baseUrl": "https://api.example.test/v1",
                    "model": "model-a",
                    "provider": "OpenAI",
                }
            )

    message = format_llm_exception_message(exc_info.value, fallback_message="LLM 连通检测失败。")
    assert "余额" in message or "额度" in message
    assert "HTTP status: 402" in message
