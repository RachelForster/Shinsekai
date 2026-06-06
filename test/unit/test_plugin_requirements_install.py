from __future__ import annotations

from pathlib import Path


def _prepare_installer(monkeypatch, tmp_path):
    from core.plugins import plugin_requirements_install as installer

    monkeypatch.setattr(installer, "pip_python_executable", lambda: Path("python"))
    monkeypatch.setattr(installer, "plugin_pip_target_directory", lambda: None)
    monkeypatch.setattr(installer.sys, "platform", "linux")

    plugin_root = tmp_path / "plugin"
    plugin_root.mkdir()
    return installer, plugin_root


def _capture_pip_invocation(monkeypatch, installer, result=("pip_ok", "")):
    calls: list[dict[str, object]] = []

    def fake_run_pip_install(cmd, *, cwd, timeout_sec, on_output_line):
        req_path = Path(cmd[cmd.index("-r") + 1])
        calls.append(
            {
                "cmd": list(cmd),
                "cwd": cwd,
                "timeout_sec": timeout_sec,
                "requirements_path": req_path,
                "requirements_text": req_path.read_text(encoding="utf-8"),
            }
        )
        return result

    monkeypatch.setattr(installer, "_run_pip_install", fake_run_pip_install)
    return calls


def _write_requirements(plugin_root: Path, text: str) -> Path:
    req = plugin_root / "requirements.txt"
    req.write_text(text, encoding="utf-8")
    return req


def test_finish_install_result_refreshes_plugin_target_on_success(monkeypatch):
    from core.plugins import plugin_requirements_install as installer

    calls: list[bool] = []
    monkeypatch.setattr(
        installer,
        "ensure_plugin_site_packages_on_syspath",
        lambda: calls.append(True),
    )

    result = installer._finish_install_result(("pip_ok", ""), Path("plugin_site_packages"))

    assert result == ("pip_ok", "")
    assert calls == [True]


def test_finish_install_result_does_not_refresh_on_failed_install(monkeypatch):
    from core.plugins import plugin_requirements_install as installer

    calls: list[bool] = []
    monkeypatch.setattr(
        installer,
        "ensure_plugin_site_packages_on_syspath",
        lambda: calls.append(True),
    )

    result = installer._finish_install_result(
        ("pip_failed", "boom"),
        Path("plugin_site_packages"),
    )

    assert result == ("pip_failed", "boom")
    assert calls == []


def test_install_plugin_requirements_prunes_installed_plain_packages(
    monkeypatch,
    tmp_path,
):
    installer, plugin_root = _prepare_installer(monkeypatch, tmp_path)
    original_req = _write_requirements(
        plugin_root,
        "already-there==1.0\nmissing-package>=2\n",
    )
    calls = _capture_pip_invocation(monkeypatch, installer)

    monkeypatch.setattr(
        installer,
        "_requirement_line_is_satisfied",
        lambda line: line.startswith("already-there"),
        raising=False,
    )

    result = installer.install_plugin_requirements_txt(plugin_root)

    assert result == ("pip_ok", "")
    assert len(calls) == 1
    assert calls[0]["requirements_path"] != original_req
    assert calls[0]["requirements_text"] == "missing-package>=2\n"


def test_install_plugin_requirements_adds_env_index_url_to_pip_command(
    monkeypatch,
    tmp_path,
):
    installer, plugin_root = _prepare_installer(monkeypatch, tmp_path)
    _write_requirements(plugin_root, "missing-package>=2\n")
    calls = _capture_pip_invocation(monkeypatch, installer)
    monkeypatch.setenv("SHINSEKAI_PIP_INDEX_URL", "https://mirror.example/simple")

    result = installer.install_plugin_requirements_txt(plugin_root)

    assert result == ("pip_ok", "")
    cmd = calls[0]["cmd"]
    assert "--index-url" in cmd
    assert cmd[cmd.index("--index-url") + 1] == "https://mirror.example/simple"


def test_install_plugin_requirements_uses_manifest_china_index_by_default(
    monkeypatch,
    tmp_path,
):
    installer, plugin_root = _prepare_installer(monkeypatch, tmp_path)
    _write_requirements(plugin_root, "missing-package>=2\n")
    calls = _capture_pip_invocation(monkeypatch, installer)
    monkeypatch.delenv("PIP_INDEX_URL", raising=False)
    monkeypatch.delenv("PIP_CONFIG_FILE", raising=False)
    monkeypatch.delenv("SHINSEKAI_PIP_INDEX_URL", raising=False)
    monkeypatch.delenv("SHINSEKAI_PIP_INDEX_URLS", raising=False)
    monkeypatch.delenv("SHINSEKAI_PIP_INSTALL_ARGS", raising=False)
    monkeypatch.delenv("SHINSEKAI_RUNTIME_SOURCE", raising=False)

    result = installer.install_plugin_requirements_txt(plugin_root)

    assert result == ("pip_ok", "")
    cmd = calls[0]["cmd"]
    assert "--index-url" in cmd
    assert cmd[cmd.index("--index-url") + 1] == "https://pypi.tuna.tsinghua.edu.cn/simple/"
    assert "https://mirrors.aliyun.com/pypi/simple/" in cmd
    assert "https://pypi.org/simple/" in cmd


def test_install_plugin_requirements_does_not_add_env_index_when_requirements_has_index(
    monkeypatch,
    tmp_path,
):
    installer, plugin_root = _prepare_installer(monkeypatch, tmp_path)
    _write_requirements(
        plugin_root,
        "--index-url https://requirements.example/simple\nmissing-package>=2\n",
    )
    calls = _capture_pip_invocation(monkeypatch, installer)
    monkeypatch.setenv("SHINSEKAI_PIP_INDEX_URL", "https://mirror.example/simple")

    result = installer.install_plugin_requirements_txt(plugin_root)

    assert result == ("pip_ok", "")
    cmd = calls[0]["cmd"]
    assert "https://mirror.example/simple" not in cmd


def test_install_plugin_requirements_shlex_parses_extra_pip_args(
    monkeypatch,
    tmp_path,
):
    installer, plugin_root = _prepare_installer(monkeypatch, tmp_path)
    _write_requirements(plugin_root, "missing-package>=2\n")
    calls = _capture_pip_invocation(monkeypatch, installer)
    monkeypatch.setenv(
        "SHINSEKAI_PIP_INSTALL_ARGS",
        '--retries 2 --trusted-host "mirror.example"',
    )

    result = installer.install_plugin_requirements_txt(plugin_root)

    assert result == ("pip_ok", "")
    cmd = calls[0]["cmd"]
    assert cmd[cmd.index("--retries") + 1] == "2"
    assert cmd[cmd.index("--trusted-host") + 1] == "mirror.example"


def test_install_plugin_requirements_extra_pip_args_index_suppresses_env_index(
    monkeypatch,
    tmp_path,
):
    installer, plugin_root = _prepare_installer(monkeypatch, tmp_path)
    _write_requirements(plugin_root, "missing-package>=2\n")
    calls = _capture_pip_invocation(monkeypatch, installer)
    monkeypatch.setenv("SHINSEKAI_PIP_INDEX_URL", "https://env.example/simple")
    monkeypatch.setenv(
        "SHINSEKAI_PIP_INSTALL_ARGS",
        "--index-url https://args.example/simple",
    )

    result = installer.install_plugin_requirements_txt(plugin_root)

    assert result == ("pip_ok", "")
    cmd = calls[0]["cmd"]
    assert "https://args.example/simple" in cmd
    assert "https://env.example/simple" not in cmd


def test_install_plugin_requirements_classifies_pip_dependency_conflicts(
    monkeypatch,
    tmp_path,
):
    installer, plugin_root = _prepare_installer(monkeypatch, tmp_path)
    _write_requirements(plugin_root, "a==1\nb==2\n")
    conflict_detail = (
        "ERROR: Cannot install a==1 and b==2 because these package versions "
        "have conflicting dependencies."
    )
    _capture_pip_invocation(monkeypatch, installer, result=("pip_failed", conflict_detail))

    result = installer.install_plugin_requirements_txt(plugin_root)

    assert result == ("pip_conflict", conflict_detail)


def test_install_plugin_requirements_falls_back_to_original_file_for_unsafe_pruning(
    monkeypatch,
    tmp_path,
):
    installer, plugin_root = _prepare_installer(monkeypatch, tmp_path)
    original_req = _write_requirements(
        plugin_root,
        "\n".join(
            [
                "already-there==1.0",
                "editable-project @ git+https://example.invalid/pkg.git",
                "-e ./local-project",
                "--find-links ./wheels",
                "missing-package>=2",
                "",
            ]
        ),
    )
    calls = _capture_pip_invocation(monkeypatch, installer)
    monkeypatch.setattr(
        installer,
        "_requirement_line_is_satisfied",
        lambda line: line.startswith("already-there"),
        raising=False,
    )

    result = installer.install_plugin_requirements_txt(plugin_root)

    assert result == ("pip_ok", "")
    assert calls[0]["requirements_path"] == original_req
    assert calls[0]["requirements_text"] == original_req.read_text(encoding="utf-8")
