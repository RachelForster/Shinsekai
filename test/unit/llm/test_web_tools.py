"""Unit tests for the web_search tool (Brave Search LLM context endpoint)."""

from types import SimpleNamespace

import pytest

import llm.tools.web_tools as web_tools

pytestmark = pytest.mark.unit


def test_web_search_without_key_returns_config_hint(monkeypatch):
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.setattr(web_tools, "_api_key", lambda: "")
    out = web_tools.web_search("anything")
    assert "未配置" in out
    assert "brave_search_api_key" in out


def test_web_search_sends_key_header_and_returns_body(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured.update(url=url, params=params, headers=headers, timeout=timeout)
        return SimpleNamespace(status_code=200, text='{"grounding": "ok"}')

    monkeypatch.setattr(web_tools, "_api_key", lambda: "test-key")
    monkeypatch.setattr(web_tools.requests, "get", fake_get)

    out = web_tools.web_search("tallest mountains")

    assert out == '{"grounding": "ok"}'
    assert captured["url"] == web_tools._ENDPOINT
    assert captured["params"] == {"q": "tallest mountains"}
    assert captured["headers"] == {"X-Subscription-Token": "test-key"}


def test_web_search_http_error_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(web_tools, "_api_key", lambda: "test-key")
    monkeypatch.setattr(
        web_tools.requests, "get",
        lambda *a, **k: SimpleNamespace(status_code=429, text="rate limited"),
    )
    out = web_tools.web_search("q")
    assert "HTTP 429" in out


def test_web_search_env_var_takes_precedence(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "env-key")
    assert web_tools._api_key() == "env-key"


def test_web_search_registered_in_web_group():
    from sdk.tool_registry import iter_registered_tools

    entries = {name: group for _f, name, _d, group, _r in iter_registered_tools()}
    assert entries.get("web_search") == "web"
