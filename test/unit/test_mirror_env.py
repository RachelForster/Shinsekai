from __future__ import annotations

import os
import logging

from config.mirror_env import (
    DEFAULT_GITHUB_MIRROR_URL,
    DEFAULT_HUGGINGFACE_CACHE_DIR,
    DEFAULT_HUGGINGFACE_MIRROR_URL,
    DEFAULT_PYPI_MIRROR_URL,
    apply_mirror_environment,
    apply_mirror_environment_from_system_config,
    detect_china_network,
    mirror_github_url,
    system_config_payload_with_resolved_mirrors,
)
from config.schema import SystemConfig


def _clear_mirror_env(monkeypatch):
    for name in (
        "HF_ENDPOINT",
        "HF_HOME",
        "HF_HUB_CACHE",
        "HUGGINGFACE_HUB_ENDPOINT",
        "HUGGINGFACE_HUB_CACHE",
        "TRANSFORMERS_CACHE",
        "SHINSEKAI_HUGGINGFACE_MIRROR_URL",
        "SHINSEKAI_HUGGINGFACE_CACHE_DIR",
        "GITHUB_MIRROR_URL",
        "SHINSEKAI_GITHUB_MIRROR_URL",
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "SHINSEKAI_PIP_INDEX_URL",
        "SHINSEKAI_NETWORK_REGION",
        "SHINSEKAI_SKIP_NETWORK_REGION_PROBE",
        "SHINSEKAI_IP_REGION_URLS",
        "SHINSEKAI_MIRROR_REGION",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("config.mirror_env._DETECT_CACHE", None)


def test_apply_mirror_environment_uses_china_defaults(monkeypatch):
    _clear_mirror_env(monkeypatch)
    monkeypatch.setenv("SHINSEKAI_NETWORK_REGION", "china")

    values = apply_mirror_environment(SystemConfig())

    assert values.huggingface == DEFAULT_HUGGINGFACE_MIRROR_URL
    assert values.github == DEFAULT_GITHUB_MIRROR_URL
    assert values.huggingface_cache_dir == DEFAULT_HUGGINGFACE_CACHE_DIR
    assert values.pypi == DEFAULT_PYPI_MIRROR_URL
    assert os.environ["HF_ENDPOINT"] == DEFAULT_HUGGINGFACE_MIRROR_URL
    assert os.environ["HF_HOME"].endswith("/data/cache/huggingface")
    assert os.environ["HF_HUB_CACHE"].endswith("/data/cache/huggingface/hub")
    assert os.environ["HUGGINGFACE_HUB_CACHE"] == os.environ["HF_HUB_CACHE"]
    assert os.environ["TRANSFORMERS_CACHE"].endswith("/data/cache/huggingface/transformers")
    assert os.environ["SHINSEKAI_HUGGINGFACE_CACHE_DIR"] == os.environ["HF_HOME"]
    assert os.environ["SHINSEKAI_GITHUB_MIRROR_URL"] == DEFAULT_GITHUB_MIRROR_URL
    assert "PIP_INDEX_URL" not in os.environ
    assert "PIP_EXTRA_INDEX_URL" not in os.environ
    assert os.environ["SHINSEKAI_PIP_INDEX_URL"] == DEFAULT_PYPI_MIRROR_URL
    assert os.environ["SHINSEKAI_MIRROR_REGION"] == "china"


def test_apply_mirror_environment_marks_global_pip_strategy(monkeypatch):
    _clear_mirror_env(monkeypatch)
    monkeypatch.setenv("SHINSEKAI_NETWORK_REGION", "global")

    values = apply_mirror_environment(SystemConfig())

    assert values.region == "global"
    assert "SHINSEKAI_PIP_INDEX_URL" not in os.environ
    assert os.environ["SHINSEKAI_MIRROR_REGION"] == "global"


def test_apply_mirror_environment_manual_values_override_region(monkeypatch, tmp_path):
    _clear_mirror_env(monkeypatch)
    monkeypatch.setenv("SHINSEKAI_NETWORK_REGION", "global")
    cache_dir = tmp_path / "hf-cache"
    config = SystemConfig(
        github_mirror_url="https://mirror.example/{path}",
        huggingface_cache_dir=str(cache_dir),
        huggingface_mirror_url="https://hf.example",
        mirror_auto_detect_china=False,
        pypi_mirror_url="https://pypi.example/simple",
    )

    values = apply_mirror_environment(config)

    assert values.region == "global"
    assert os.environ["HF_ENDPOINT"] == "https://hf.example"
    assert os.environ["HF_HOME"] == cache_dir.as_posix()
    assert os.environ["HF_HUB_CACHE"] == (cache_dir / "hub").as_posix()
    assert (cache_dir / "hub").is_dir()
    assert (cache_dir / "transformers").is_dir()
    assert "PIP_INDEX_URL" not in os.environ
    assert os.environ["SHINSEKAI_PIP_INDEX_URL"] == "https://pypi.example/simple"
    assert mirror_github_url("https://github.com/owner/repo/archive/refs/heads/main.zip") == (
        "https://mirror.example/owner/repo/archive/refs/heads/main.zip"
    )


def test_apply_mirror_environment_from_system_config_reads_yaml(monkeypatch, tmp_path):
    _clear_mirror_env(monkeypatch)
    config_path = tmp_path / "system_config.yaml"
    cache_dir = tmp_path / "hf-home"
    config_path.write_text(
        "\n".join(
            [
                "mirror_auto_detect_china: false",
                "huggingface_mirror_url: https://hf.example",
                f"huggingface_cache_dir: {cache_dir.as_posix()}",
                "github_mirror_url: https://mirror.example/{url}",
                "pypi_mirror_url: https://pypi.example/simple",
            ]
        ),
        encoding="utf-8",
    )

    values = apply_mirror_environment_from_system_config(config_path)

    assert values.huggingface == "https://hf.example"
    assert os.environ["HF_ENDPOINT"] == "https://hf.example"
    assert os.environ["HF_HOME"] == cache_dir.as_posix()
    assert os.environ["SHINSEKAI_GITHUB_MIRROR_URL"] == "https://mirror.example/{url}"
    assert os.environ["SHINSEKAI_PIP_INDEX_URL"] == "https://pypi.example/simple"


def test_apply_mirror_environment_does_not_override_standard_pip_env(monkeypatch):
    _clear_mirror_env(monkeypatch)
    monkeypatch.setenv("PIP_INDEX_URL", "https://user.example/simple")

    apply_mirror_environment(SystemConfig(mirror_auto_detect_china=False, pypi_mirror_url="https://pypi.example/simple"))

    assert os.environ["PIP_INDEX_URL"] == "https://user.example/simple"
    assert os.environ["SHINSEKAI_PIP_INDEX_URL"] == "https://pypi.example/simple"


def test_resolved_payload_keeps_user_mirror_fields_blank(monkeypatch):
    _clear_mirror_env(monkeypatch)
    monkeypatch.setenv("SHINSEKAI_NETWORK_REGION", "china")

    payload = system_config_payload_with_resolved_mirrors(SystemConfig())

    assert payload["mirror_region"] == "china"
    assert payload["huggingface_mirror_url"] == ""
    assert payload["github_mirror_url"] == ""
    assert payload["pypi_mirror_url"] == ""
    assert "effective_huggingface_mirror_url" not in payload
    assert "effective_huggingface_cache_dir" not in payload
    assert "effective_github_mirror_url" not in payload
    assert "effective_pypi_mirror_url" not in payload


def test_detect_china_network_prefers_ip_geo_over_locale(monkeypatch):
    _clear_mirror_env(monkeypatch)
    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    monkeypatch.setattr("config.mirror_env._fetch_ip_country", lambda *args, **kwargs: "US")

    assert detect_china_network() is False


def test_detect_china_network_uses_locale_only_as_fallback(monkeypatch):
    _clear_mirror_env(monkeypatch)
    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    monkeypatch.setattr("config.mirror_env._detect_china_by_ip", lambda *args, **kwargs: None)
    monkeypatch.setattr("config.mirror_env._probe_china_network", lambda *args, **kwargs: None)

    assert detect_china_network() is True


def test_apply_mirror_environment_logs_applied_values(monkeypatch, caplog):
    _clear_mirror_env(monkeypatch)
    caplog.set_level(logging.INFO, logger="config.mirror_env")

    apply_mirror_environment(
        SystemConfig(
            mirror_auto_detect_china=False,
            huggingface_mirror_url="https://token:secret@hf.example",
            pypi_mirror_url="https://pypi.example/simple",
        )
    )

    applied = [record for record in caplog.records if getattr(record, "event", "") == "mirror.env.applied"]
    assert applied
    assert applied[-1].huggingface_mirror == "https://***@hf.example"
    assert applied[-1].pypi_index == "https://pypi.example/simple"
    assert applied[-1].sets_standard_pip_env is False
