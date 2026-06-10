from __future__ import annotations

import io
import logging

import pytest

from core.plugins import pip_runner


def _clear_index_env(monkeypatch):
    for name in (
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "PIP_NO_INDEX",
        "PIP_CONFIG_FILE",
        "SHINSEKAI_PIP_INDEX_URL",
        "SHINSEKAI_PIP_INDEX_URLS",
        "SHINSEKAI_PIP_INSTALL_ARGS",
        "SHINSEKAI_RUNTIME_SOURCE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_apply_pip_index_and_extra_args_injects_configured_index(monkeypatch):
    _clear_index_env(monkeypatch)
    monkeypatch.setenv("SHINSEKAI_PIP_INDEX_URL", "https://mirror.example/simple")
    monkeypatch.setenv("SHINSEKAI_PIP_INSTALL_ARGS", "--retries 2")

    cmd = pip_runner.apply_pip_index_and_extra_args(["python", "-m", "pip", "install", "demo"])

    assert cmd == [
        "python",
        "-m",
        "pip",
        "install",
        "demo",
        "--index-url",
        "https://mirror.example/simple",
        "--retries",
        "2",
    ]


def test_apply_pip_index_and_extra_args_uses_primary_flag(monkeypatch):
    _clear_index_env(monkeypatch)
    monkeypatch.setenv("SHINSEKAI_PIP_INDEX_URL", "https://mirror.example/simple")

    cmd = pip_runner.apply_pip_index_and_extra_args(
        ["python", "-m", "pip", "install", "demo"],
        primary_flag="-i",
    )

    assert cmd[-2:] == ["-i", "https://mirror.example/simple"]


@pytest.mark.parametrize(
    ("cmd_args", "lines", "extra_args"),
    [
        (["--extra-index-url", "https://private.example/simple"], [], ""),
        ([], ["--extra-index-url https://private.example/simple"], ""),
        ([], ["-r sub-requirements.txt"], ""),
        ([], ["--constraint constraints.txt"], ""),
        ([], [], "--extra-index-url=https://private.example/simple"),
        ([], [], "--no-index"),
    ],
)
def test_apply_pip_index_and_extra_args_respects_existing_intent(
    monkeypatch,
    cmd_args,
    lines,
    extra_args,
):
    _clear_index_env(monkeypatch)
    monkeypatch.setenv("SHINSEKAI_PIP_INDEX_URL", "https://mirror.example/simple")
    if extra_args:
        monkeypatch.setenv("SHINSEKAI_PIP_INSTALL_ARGS", extra_args)

    cmd = pip_runner.apply_pip_index_and_extra_args(
        ["python", "-m", "pip", "install", "demo", *cmd_args],
        lines,
    )

    assert "https://mirror.example/simple" not in cmd


def test_extra_pip_install_args_ignores_invalid_env_and_logs(monkeypatch, caplog):
    _clear_index_env(monkeypatch)
    monkeypatch.setenv("SHINSEKAI_PIP_INSTALL_ARGS", '--trusted-host "mirror.example')
    caplog.set_level(logging.WARNING, logger=pip_runner.logger.name)

    assert pip_runner.extra_pip_install_args() == []
    assert "Ignoring invalid SHINSEKAI_PIP_INSTALL_ARGS" in caplog.text


def test_redact_url_credentials_masks_password_and_bare_tokens():
    assert (
        pip_runner.redact_url_credentials("https://user:secret@host/simple")
        == "https://user:***@host/simple"
    )
    assert (
        pip_runner.redact_url_credentials("https://only-token@host/simple")
        == "https://***@host/simple"
    )
    assert pip_runner.redact_url_credentials("https://host/simple") == "https://host/simple"


def test_pip_subprocess_env_sets_defaults(monkeypatch):
    monkeypatch.delenv("PIP_DISABLE_PIP_VERSION_CHECK", raising=False)
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("PYTHONUNBUFFERED", raising=False)

    env = pip_runner.pip_subprocess_env()

    assert env["PIP_DISABLE_PIP_VERSION_CHECK"] == "1"
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONUNBUFFERED"] == "1"


def test_pip_subprocess_env_keeps_user_values(monkeypatch):
    monkeypatch.setenv("PYTHONUTF8", "0")

    assert pip_runner.pip_subprocess_env()["PYTHONUTF8"] == "0"


class _FakePopen:
    def __init__(self, stdout_text: str, returncode: int):
        self.stdout = io.StringIO(stdout_text)
        self.stderr = io.StringIO("")
        self.returncode = returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        pass


def _patch_popen(monkeypatch, stdout_text: str, returncode: int):
    monkeypatch.setattr(
        pip_runner.subprocess,
        "Popen",
        lambda cmd, **kwargs: _FakePopen(stdout_text, returncode),
    )


def test_run_pip_install_redacts_relayed_lines(monkeypatch, tmp_path):
    _patch_popen(
        monkeypatch,
        "Looking in indexes: https://user:secret@mirror.example/simple\n",
        0,
    )
    lines: list[str] = []

    code, detail = pip_runner.run_pip_install(
        ["python", "-m", "pip", "install", "demo"],
        cwd=tmp_path,
        timeout_sec=30,
        on_output_line=lines.append,
    )

    assert (code, detail) == ("pip_ok", "")
    assert lines == ["Looking in indexes: https://user:***@mirror.example/simple"]


def test_run_pip_install_classifies_conflicts(monkeypatch, tmp_path):
    _patch_popen(monkeypatch, "ERROR: ResolutionImpossible: for help visit pip docs\n", 1)

    code, detail = pip_runner.run_pip_install(
        ["python", "-m", "pip", "install", "demo"],
        cwd=tmp_path,
        timeout_sec=30,
    )

    assert code == "pip_conflict"
    assert "ResolutionImpossible" in detail


def test_run_pip_install_reports_redacted_failure_tail(monkeypatch, tmp_path):
    _patch_popen(
        monkeypatch,
        "ERROR: HTTP error 403 from https://user:secret@private.example/simple\n",
        1,
    )

    code, detail = pip_runner.run_pip_install(
        ["python", "-m", "pip", "install", "demo"],
        cwd=tmp_path,
        timeout_sec=30,
    )

    assert code == "pip_failed"
    assert "secret" not in detail
    assert "https://user:***@private.example/simple" in detail


def test_run_pip_install_allows_longer_failure_detail(monkeypatch, tmp_path):
    output = "A" * 2000 + "KEEP-ME"
    _patch_popen(monkeypatch, output, 1)

    code, detail = pip_runner.run_pip_install(
        ["python", "-m", "pip", "install", "demo"],
        cwd=tmp_path,
        timeout_sec=30,
        detail_max=4000,
    )

    assert code == "pip_failed"
    assert "KEEP-ME" in detail
    assert len(detail) > 1600
