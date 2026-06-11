from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

import config.network_proxy as network_proxy
from config.network_proxy import (
    apply_network_proxy_environment,
    apply_network_proxy_environment_from_system_config,
    detect_network_proxy_configuration,
)
from config.schema import SystemConfig


def _clear_proxy_env(monkeypatch):
    for name in (
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "SOCKS_PROXY",
        "socks_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.setitem(network_proxy._ORIGINAL_PROXY_ENV, name, None)


def test_apply_network_proxy_environment_sets_standard_proxy_vars(monkeypatch):
    _clear_proxy_env(monkeypatch)

    values = apply_network_proxy_environment(
        SystemConfig(
            http_proxy_url="http://127.0.0.1:7890",
            https_proxy_url="https://proxy.example:8443",
            network_proxy_enabled=True,
            socks5_proxy_url="socks5://127.0.0.1:7891",
        )
    )

    assert values.http == "http://127.0.0.1:7890"
    assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7890"
    assert os.environ["http_proxy"] == "http://127.0.0.1:7890"
    assert os.environ["HTTPS_PROXY"] == "https://proxy.example:8443"
    assert os.environ["https_proxy"] == "https://proxy.example:8443"
    assert os.environ["ALL_PROXY"] == "socks5://127.0.0.1:7891"
    assert os.environ["all_proxy"] == "socks5://127.0.0.1:7891"


def test_apply_network_proxy_environment_ignores_config_when_disabled(monkeypatch):
    _clear_proxy_env(monkeypatch)

    values = apply_network_proxy_environment(
        SystemConfig(
            http_proxy_url="http://127.0.0.1:7890",
            https_proxy_url="http://127.0.0.1:7890",
            network_proxy_enabled=False,
            socks5_proxy_url="socks5://127.0.0.1:7891",
        )
    )

    assert values.http == ""
    assert "HTTP_PROXY" not in os.environ
    assert "HTTPS_PROXY" not in os.environ
    assert "ALL_PROXY" not in os.environ


def test_apply_network_proxy_environment_restores_original_vars(monkeypatch):
    monkeypatch.setitem(
        network_proxy._ORIGINAL_PROXY_ENV,
        "HTTP_PROXY",
        "http://original:8080",
    )
    monkeypatch.setitem(network_proxy._ORIGINAL_PROXY_ENV, "http_proxy", None)
    monkeypatch.setenv("HTTP_PROXY", "http://configured:7890")
    monkeypatch.setenv("http_proxy", "http://configured:7890")

    apply_network_proxy_environment(SystemConfig())

    assert os.environ["HTTP_PROXY"] == "http://original:8080"
    if os.name == "nt":
        assert os.environ["http_proxy"] == "http://original:8080"
    else:
        assert "http_proxy" not in os.environ


def test_apply_network_proxy_environment_from_system_config_reads_yaml(monkeypatch, tmp_path):
    _clear_proxy_env(monkeypatch)
    config_path = tmp_path / "system_config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "network_proxy_enabled: true",
                "http_proxy_url: http://127.0.0.1:7890",
                "https_proxy_url: http://127.0.0.1:7890",
                "socks5_proxy_url: socks5h://127.0.0.1:7891",
            ]
        ),
        encoding="utf-8",
    )

    values = apply_network_proxy_environment_from_system_config(config_path)

    assert values.socks5 == "socks5h://127.0.0.1:7891"
    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7890"
    assert os.environ["ALL_PROXY"] == "socks5h://127.0.0.1:7891"


def test_detect_network_proxy_configuration_prefers_original_environment(monkeypatch):
    _clear_proxy_env(monkeypatch)
    monkeypatch.setattr(network_proxy.platform_module, "system", lambda: "UnknownOS")
    monkeypatch.setitem(network_proxy._ORIGINAL_PROXY_ENV, "HTTP_PROXY", "127.0.0.1:7890")
    monkeypatch.setitem(network_proxy._ORIGINAL_PROXY_ENV, "HTTPS_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setitem(network_proxy._ORIGINAL_PROXY_ENV, "ALL_PROXY", "socks5h://127.0.0.1:7891")

    detected = detect_network_proxy_configuration()

    assert detected.source == "environment"
    assert detected.http_proxy_url == "http://127.0.0.1:7890"
    assert detected.https_proxy_url == "http://127.0.0.1:7890"
    assert detected.socks5_proxy_url == "socks5h://127.0.0.1:7891"


def test_detect_network_proxy_configuration_maps_http_all_proxy(monkeypatch):
    _clear_proxy_env(monkeypatch)
    monkeypatch.setattr(network_proxy.platform_module, "system", lambda: "UnknownOS")
    monkeypatch.setitem(network_proxy._ORIGINAL_PROXY_ENV, "ALL_PROXY", "http://127.0.0.1:7890")

    detected = detect_network_proxy_configuration()

    assert detected.http_proxy_url == "http://127.0.0.1:7890"
    assert detected.https_proxy_url == "http://127.0.0.1:7890"
    assert detected.socks5_proxy_url == ""


def test_parse_windows_proxy_server():
    detected = network_proxy._parse_windows_proxy_server(
        "http=127.0.0.1:7890;https=https://secure.example:8443;socks=127.0.0.1:7891"
    )

    assert detected.http_proxy_url == "http://127.0.0.1:7890"
    assert detected.https_proxy_url == "https://secure.example:8443"
    assert detected.socks5_proxy_url == "socks5://127.0.0.1:7891"


def test_system_config_rejects_proxy_url_with_wrong_scheme():
    with pytest.raises(ValidationError):
        SystemConfig(http_proxy_url="socks5://127.0.0.1:7891")

    with pytest.raises(ValidationError):
        SystemConfig(socks5_proxy_url="http://127.0.0.1:7890")
