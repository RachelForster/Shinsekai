from __future__ import annotations

import pytest

from core.plugins import pip_index_config


@pytest.mark.parametrize(
    "args",
    [
        ["-i", "https://example.invalid/simple"],
        ["-ihttps://example.invalid/simple"],
        ["--index-url", "https://example.invalid/simple"],
        ["--index-url=https://example.invalid/simple"],
        ["--extra-index-url", "https://example.invalid/simple"],
        ["--extra-index-url=https://example.invalid/simple"],
        ["--no-index"],
        ["--retries", "2", "--extra-index-url", "https://example.invalid/simple"],
    ],
)
def test_has_explicit_pip_index_detects_index_intent(args):
    assert pip_index_config.has_explicit_pip_index(args) is True


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["requests>=2"],
        ["--retries", "2", "--trusted-host", "mirror.example"],
        ["--find-links", "./wheels"],
    ],
)
def test_has_explicit_pip_index_ignores_non_index_args(args):
    assert pip_index_config.has_explicit_pip_index(args) is False


def _clear_index_env(monkeypatch):
    for name in (
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "PIP_NO_INDEX",
        "PIP_CONFIG_FILE",
        "SHINSEKAI_PIP_INDEX_URL",
        "SHINSEKAI_PIP_INDEX_URLS",
        "SHINSEKAI_RUNTIME_SOURCE",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    "env_name",
    ["PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_NO_INDEX", "PIP_CONFIG_FILE"],
)
def test_pip_index_urls_respects_user_pip_env_overrides(monkeypatch, env_name):
    _clear_index_env(monkeypatch)
    monkeypatch.setenv(env_name, "https://user.example/simple")

    assert pip_index_config.pip_index_urls() == []


def test_pip_index_urls_prefers_china_mirrors_by_default(monkeypatch):
    _clear_index_env(monkeypatch)

    urls = pip_index_config.pip_index_urls()

    assert urls[0] == "https://pypi.tuna.tsinghua.edu.cn/simple/"
    assert "https://pypi.org/simple/" in urls
