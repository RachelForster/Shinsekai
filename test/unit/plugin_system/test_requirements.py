from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_frozen_plugin_paths_keep_app_runtime_and_project_data_separate(tmp_path, monkeypatch):
    from plugin_system.requirements import install as installer

    app_root = tmp_path / "app"
    project_root = tmp_path / "project"
    app_root.mkdir()
    (project_root / "plugins").mkdir(parents=True)
    monkeypatch.setattr(installer.sys, "frozen", True, raising=False)
    monkeypatch.setenv("SHINSEKAI_APP_ROOT", app_root.as_posix())
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project_root.as_posix())
    monkeypatch.setattr(installer.sys, "path", list(installer.sys.path))

    installer.ensure_plugins_namespace_on_syspath()

    assert installer.frozen_release_root() == app_root.resolve()
    assert installer.plugin_pip_target_directory() == (
        project_root / "data" / "plugin_site_packages"
    )
    assert installer.sys.path[0] == project_root.as_posix()


def test_frozen_plugin_target_prefers_explicit_root_over_ambient_root(
    tmp_path,
    monkeypatch,
):
    from plugin_system.requirements import install as installer

    ambient = tmp_path / "ambient"
    selected = tmp_path / "selected"
    ambient.mkdir()
    selected.mkdir()
    monkeypatch.setattr(installer.sys, "frozen", True, raising=False)
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", ambient.as_posix())

    assert installer.plugin_pip_target_directory(root=selected) == (
        selected / "data/plugin_site_packages"
    )


def test_frozen_plugin_pip_uses_the_native_runtime_layout(tmp_path, monkeypatch):
    from plugin_system.requirements import install as installer

    app_root = tmp_path / "app"
    runtime_python = (
        app_root / "runtime/python.exe"
        if os.name == "nt"
        else app_root / "runtime/bin/python3"
    )
    runtime_python.parent.mkdir(parents=True)
    runtime_python.write_bytes(b"python")
    runtime_python.chmod(runtime_python.stat().st_mode | 0o100)
    monkeypatch.setattr(installer.sys, "frozen", True, raising=False)
    monkeypatch.setenv("SHINSEKAI_APP_ROOT", app_root.as_posix())

    assert installer.pip_python_executable() == runtime_python


def test_frozen_plugin_target_rejects_project_directory_alias(tmp_path, monkeypatch):
    from plugin_system.requirements import install as installer

    project_root = tmp_path / "project"
    external_target = tmp_path / "external-plugin-site-packages"
    (project_root / "data").mkdir(parents=True)
    external_target.mkdir()
    try:
        (project_root / "data" / "plugin_site_packages").symlink_to(
            external_target,
            target_is_directory=True,
        )
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    monkeypatch.setattr(installer.sys, "frozen", True, raising=False)
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project_root.as_posix())

    with pytest.raises(PermissionError, match="symbolic links"):
        installer.plugin_pip_target_directory()


def test_plugin_site_packages_rejects_alias_at_syspath_boundary(tmp_path, monkeypatch):
    from plugin_system.requirements import install as installer

    external_target = tmp_path / "external-plugin-site-packages"
    external_target.mkdir()
    alias = tmp_path / "plugin-site-packages"
    try:
        alias.symlink_to(external_target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    original_path = list(installer.sys.path)
    monkeypatch.setattr(installer.sys, "path", original_path.copy())
    monkeypatch.setattr(installer, "plugin_pip_target_directory", lambda: alias)

    with pytest.raises(PermissionError, match="symbolic link"):
        installer.ensure_plugin_site_packages_on_syspath()

    assert installer.sys.path == original_path


def test_plugin_pip_command_rejects_alias_at_subprocess_boundary(tmp_path):
    from plugin_system.requirements import install as installer

    external_target = tmp_path / "external-plugin-site-packages"
    external_target.mkdir()
    alias = tmp_path / "plugin-site-packages"
    try:
        alias.symlink_to(external_target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    with pytest.raises(PermissionError, match="symbolic link"):
        installer._pip_base_install_cmd(Path("python"), alias)


def test_plugins_namespace_rejects_external_directory_alias(tmp_path, monkeypatch):
    from plugin_system.requirements import install as installer

    project_root = tmp_path / "project"
    external_plugins = tmp_path / "external-plugins"
    project_root.mkdir()
    external_plugins.mkdir()
    try:
        (project_root / "plugins").symlink_to(external_plugins, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    original_path = list(installer.sys.path)
    monkeypatch.setattr(installer.sys, "path", original_path.copy())
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project_root.as_posix())

    with pytest.raises(PermissionError, match="symbolic links"):
        installer.ensure_plugins_namespace_on_syspath()

    assert installer.sys.path == original_path


def _prepare_installer(monkeypatch, tmp_path):
    from plugin_system.requirements import install as installer

    python_executable = tmp_path / "python"
    python_executable.write_bytes(b"python")
    python_executable.chmod(python_executable.stat().st_mode | 0o100)
    monkeypatch.setattr(
        installer,
        "pip_python_executable",
        lambda: python_executable,
    )
    monkeypatch.setattr(installer, "plugin_pip_target_directory", lambda: None)
    monkeypatch.setattr(installer.sys, "platform", "linux")

    plugin_root = tmp_path / "plugin"
    plugin_root.mkdir()
    return installer, plugin_root


def _capture_pip_invocation(monkeypatch, installer, result=("pip_ok", "")):
    calls: list[dict[str, object]] = []

    def fake_run_pip_install(cmd, *, cwd, timeout_sec, on_output_line):
        req_path = Path(cmd[cmd.index("-r") + 1])
        constraints_path = Path(cmd[cmd.index("-c") + 1]) if "-c" in cmd else None
        calls.append(
            {
                "cmd": list(cmd),
                "cwd": cwd,
                "timeout_sec": timeout_sec,
                "requirements_path": req_path,
                "requirements_text": req_path.read_text(encoding="utf-8"),
                "constraints_text": (
                    constraints_path.read_text(encoding="utf-8")
                    if constraints_path is not None
                    else None
                ),
            }
        )
        return result

    monkeypatch.setattr(installer, "_run_pip_install", fake_run_pip_install)
    return calls


def _write_requirements(plugin_root: Path, text: str) -> Path:
    req = plugin_root / "requirements.txt"
    req.write_text(text, encoding="utf-8")
    return req


def test_installer_resolves_relative_plugin_root_from_project_not_cwd(
    monkeypatch,
    tmp_path,
):
    installer, _unused = _prepare_installer(monkeypatch, tmp_path)
    project = tmp_path / "project"
    plugin_root = project / "plugins/demo"
    unrelated = tmp_path / "launcher"
    plugin_root.mkdir(parents=True)
    unrelated.mkdir()
    _write_requirements(plugin_root, "missing-package>=2\n")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    monkeypatch.chdir(unrelated)
    calls = _capture_pip_invocation(monkeypatch, installer)

    result = installer.install_plugin_requirements_txt(Path("plugins/demo"))

    assert result == ("pip_ok", "")
    assert calls[0]["cwd"] == plugin_root


def test_installer_rejects_symlinked_plugin_root(monkeypatch, tmp_path):
    from plugin_system.requirements import install as installer

    project = tmp_path / "project"
    external = tmp_path / "external-plugin"
    alias = project / "plugins/demo"
    alias.parent.mkdir(parents=True)
    external.mkdir()
    (external / "requirements.txt").write_text("requests\n", encoding="utf-8")
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())

    with pytest.raises(PermissionError, match="symbolic link"):
        installer.install_plugin_requirements_txt(alias)


def test_installer_rejects_requirements_filename_traversal(monkeypatch, tmp_path):
    installer, plugin_root = _prepare_installer(monkeypatch, tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("must-not-run\n", encoding="utf-8")

    with pytest.raises(ValueError, match="portable path component"):
        installer.install_plugin_requirements_txt(
            plugin_root,
            requirements_file="../outside.txt",
        )


def test_finish_install_result_refreshes_plugin_target_on_success(monkeypatch):
    from plugin_system.requirements import install as installer

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
    from plugin_system.requirements import install as installer

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
        lambda line, installed_versions=None: line.startswith("already-there"),
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
    monkeypatch.delenv("PIP_EXTRA_INDEX_URL", raising=False)
    monkeypatch.delenv("PIP_NO_INDEX", raising=False)
    monkeypatch.delenv("PIP_CONFIG_FILE", raising=False)
    monkeypatch.delenv("SHINSEKAI_PIP_INDEX_URL", raising=False)
    monkeypatch.delenv("SHINSEKAI_PIP_INDEX_URLS", raising=False)
    monkeypatch.delenv("SHINSEKAI_PIP_INSTALL_ARGS", raising=False)
    monkeypatch.delenv("SHINSEKAI_RUNTIME_SOURCE", raising=False)
    monkeypatch.delenv("SHINSEKAI_MIRROR_REGION", raising=False)

    result = installer.install_plugin_requirements_txt(plugin_root)

    assert result == ("pip_ok", "")
    cmd = calls[0]["cmd"]
    assert "--index-url" in cmd
    assert cmd[cmd.index("--index-url") + 1] == "https://pypi.tuna.tsinghua.edu.cn/simple/"
    assert "https://mirrors.aliyun.com/pypi/simple/" not in cmd
    assert "https://mirrors.ustc.edu.cn/pypi/simple/" in cmd
    assert "https://pypi.org/simple/" in cmd


def test_install_plugin_requirements_uses_official_index_for_global_mirror_region(
    monkeypatch,
    tmp_path,
):
    installer, plugin_root = _prepare_installer(monkeypatch, tmp_path)
    _write_requirements(plugin_root, "missing-package>=2\n")
    calls = _capture_pip_invocation(monkeypatch, installer)
    monkeypatch.delenv("PIP_INDEX_URL", raising=False)
    monkeypatch.delenv("PIP_EXTRA_INDEX_URL", raising=False)
    monkeypatch.delenv("PIP_NO_INDEX", raising=False)
    monkeypatch.delenv("PIP_CONFIG_FILE", raising=False)
    monkeypatch.delenv("SHINSEKAI_PIP_INDEX_URL", raising=False)
    monkeypatch.delenv("SHINSEKAI_PIP_INDEX_URLS", raising=False)
    monkeypatch.delenv("SHINSEKAI_PIP_INSTALL_ARGS", raising=False)
    monkeypatch.delenv("SHINSEKAI_RUNTIME_SOURCE", raising=False)
    monkeypatch.setenv("SHINSEKAI_MIRROR_REGION", "global")

    result = installer.install_plugin_requirements_txt(plugin_root)

    assert result == ("pip_ok", "")
    cmd = calls[0]["cmd"]
    assert "--index-url" in cmd
    assert cmd[cmd.index("--index-url") + 1] == "https://pypi.org/simple/"
    assert "https://pypi.tuna.tsinghua.edu.cn/simple/" not in cmd


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


def test_install_plugin_requirements_keeps_default_index_when_requirements_add_extra_index(
    monkeypatch,
    tmp_path,
):
    installer, plugin_root = _prepare_installer(monkeypatch, tmp_path)
    _write_requirements(
        plugin_root,
        "--extra-index-url https://private.example/simple\nmissing-package>=2\n",
    )
    calls = _capture_pip_invocation(monkeypatch, installer)
    monkeypatch.setenv("SHINSEKAI_PIP_INDEX_URL", "https://mirror.example/simple")

    result = installer.install_plugin_requirements_txt(plugin_root)

    assert result == ("pip_ok", "")
    cmd = calls[0]["cmd"]
    assert "https://mirror.example/simple" not in cmd
    assert "--index-url" not in cmd


def test_install_plugin_requirements_extra_pip_args_extra_index_suppresses_env_index(
    monkeypatch,
    tmp_path,
):
    installer, plugin_root = _prepare_installer(monkeypatch, tmp_path)
    _write_requirements(plugin_root, "missing-package>=2\n")
    calls = _capture_pip_invocation(monkeypatch, installer)
    monkeypatch.setenv("SHINSEKAI_PIP_INDEX_URL", "https://env.example/simple")
    monkeypatch.setenv(
        "SHINSEKAI_PIP_INSTALL_ARGS",
        "--extra-index-url=https://private.example/simple",
    )

    result = installer.install_plugin_requirements_txt(plugin_root)

    assert result == ("pip_ok", "")
    cmd = calls[0]["cmd"]
    assert "--extra-index-url=https://private.example/simple" in cmd
    assert "https://env.example/simple" not in cmd


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
    import io

    from core.runtime_env import pip_runner

    installer, plugin_root = _prepare_installer(monkeypatch, tmp_path)
    _write_requirements(plugin_root, "pkg-a==1\npkg-b==2\n")
    conflict_detail = (
        "ERROR: Cannot install pkg-a==1 and pkg-b==2 because these package versions "
        "have conflicting dependencies."
    )

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            self.stdout = io.StringIO(conflict_detail + "\n")
            self.stderr = io.StringIO("")
            self.returncode = 1

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            pass

    monkeypatch.setattr(pip_runner.subprocess, "Popen", FakePopen)

    code, detail = installer.install_plugin_requirements_txt(plugin_root)

    assert code == "pip_conflict"
    assert "conflicting dependencies" in detail


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
        lambda line, installed_versions=None: line.startswith("already-there"),
        raising=False,
    )

    result = installer.install_plugin_requirements_txt(plugin_root)

    assert result == ("pip_ok", "")
    assert calls[0]["requirements_path"] == original_req
    assert calls[0]["requirements_text"] == original_req.read_text(encoding="utf-8")


def test_install_lines_after_precheck_scans_installed_distributions_once(monkeypatch):
    from plugin_system.requirements import install as installer

    calls: list[object] = []

    class Dist:
        metadata = {"Name": "already-there"}
        version = "1.0"

    monkeypatch.setattr(installer, "plugin_pip_target_directory", lambda: None)
    monkeypatch.setattr(
        installer.importlib_metadata,
        "distributions",
        lambda path=None: calls.append(path) or [Dist()],
    )

    can_prune, install_lines = installer._install_lines_after_precheck(
        ["already-there==1.0", "missing-package>=2"],
    )

    assert can_prune is True
    assert install_lines == ["missing-package>=2"]
    assert len(calls) == 1


def test_pytorch_cpu_build_is_force_reinstalled_from_cuda_index_without_plugin_target(
    monkeypatch,
    tmp_path,
):
    installer, plugin_root = _prepare_installer(monkeypatch, tmp_path)
    _write_requirements(
        plugin_root,
        "torch==99.0.0\n",
    )
    monkeypatch.setattr(installer, "plugin_pip_target_directory", lambda: tmp_path / "target")
    monkeypatch.setattr(
        installer,
        "_installed_distribution_versions",
        lambda: {
            "torch": "2.7.1+cpu",
            "torchvision": "0.22.1+cpu",
            "torchaudio": "2.7.1+cpu",
        },
    )

    original_plan = installer._build_pytorch_install_plan

    def cuda_plan(lines, installed_versions, *, requirement_is_satisfied):
        return original_plan(
            lines,
            installed_versions,
            requirement_is_satisfied=requirement_is_satisfied,
            index_url="https://download.pytorch.org/whl/cu128",
            index_reason="test_cuda",
        )

    monkeypatch.setattr(installer, "_build_pytorch_install_plan", cuda_plan)
    calls = _capture_pip_invocation(monkeypatch, installer)

    result = installer.install_plugin_requirements_txt(plugin_root)

    assert result == ("pip_ok", "")
    assert len(calls) == 2
    reinstall_cmd = calls[0]["cmd"]
    assert "--force-reinstall" in reinstall_cmd
    assert "--upgrade" in reinstall_cmd
    assert "--no-deps" in reinstall_cmd
    assert "--target" not in reinstall_cmd
    assert (
        reinstall_cmd[reinstall_cmd.index("--index-url") + 1]
        == "https://download.pytorch.org/whl/cu128"
    )

    dependency_repair_cmd = calls[1]["cmd"]
    assert "--force-reinstall" not in dependency_repair_cmd
    assert "--upgrade" not in dependency_repair_cmd
    assert "--no-deps" not in dependency_repair_cmd
    assert "--target" not in dependency_repair_cmd
    assert calls[0]["requirements_text"] == calls[1]["requirements_text"]
    assert calls[0]["requirements_text"] == (
        "torch==2.7.1\n"
        "torchvision==0.22.1\n"
        "torchaudio==2.7.1\n"
    )


def test_matching_pytorch_stack_skips_pip(monkeypatch, tmp_path):
    installer, plugin_root = _prepare_installer(monkeypatch, tmp_path)
    _write_requirements(
        plugin_root,
        "torch==2.7.1\ntorchvision==0.22.1\ntorchaudio==2.7.1\n",
    )
    monkeypatch.setattr(
        installer,
        "_installed_distribution_versions",
        lambda: {
            "torch": "2.7.1+cu128",
            "torchvision": "0.22.1+cu128",
            "torchaudio": "2.7.1+cu128",
        },
    )

    original_plan = installer._build_pytorch_install_plan

    def cuda_plan(lines, installed_versions, *, requirement_is_satisfied):
        return original_plan(
            lines,
            installed_versions,
            requirement_is_satisfied=requirement_is_satisfied,
            index_url="https://download.pytorch.org/whl/cu128",
            index_reason="test_cuda",
        )

    monkeypatch.setattr(installer, "_build_pytorch_install_plan", cuda_plan)
    calls = _capture_pip_invocation(monkeypatch, installer)

    result = installer.install_plugin_requirements_txt(plugin_root)

    assert result == ("pip_ok", "")
    assert calls == []


def test_plugin_pytorch_versions_are_replaced_and_transitive_torch_is_constrained(
    monkeypatch,
    tmp_path,
):
    installer, plugin_root = _prepare_installer(monkeypatch, tmp_path)
    _write_requirements(
        plugin_root,
        "accelerate>=1.10.0\ntorch==99.0.0\n",
    )
    target = tmp_path / "target"
    monkeypatch.setattr(installer, "plugin_pip_target_directory", lambda: target)
    monkeypatch.setattr(
        installer,
        "_installed_distribution_versions",
        lambda: {
            "torch": "2.7.1+cu128",
            "torchvision": "0.22.1+cu128",
            "torchaudio": "2.7.1+cu128",
        },
    )
    original_plan = installer._build_pytorch_install_plan

    def cuda_plan(lines, installed_versions, *, requirement_is_satisfied):
        return original_plan(
            lines,
            installed_versions,
            requirement_is_satisfied=requirement_is_satisfied,
            index_url="https://download.pytorch.org/whl/cu128",
            index_reason="test_cuda",
        )

    monkeypatch.setattr(installer, "_build_pytorch_install_plan", cuda_plan)
    calls = _capture_pip_invocation(monkeypatch, installer)

    result = installer.install_plugin_requirements_txt(plugin_root)

    assert result == ("pip_ok", "")
    assert len(calls) == 1
    cmd = calls[0]["cmd"]
    assert "--target" not in cmd
    assert "-c" in cmd
    assert calls[0]["constraints_text"] == (
        "torch==2.7.1\n"
        "torchvision==0.22.1\n"
        "torchaudio==2.7.1\n"
    )
    assert calls[0]["requirements_text"] == "accelerate>=1.10.0\n"


def test_write_temp_requirements_removes_file_when_write_fails(monkeypatch, tmp_path):
    from plugin_system.requirements import install as installer

    created = tmp_path / "easyai_missing_req_fail.txt"

    def fake_mkstemp(prefix, suffix):
        fd = os.open(str(created), os.O_CREAT | os.O_TRUNC | os.O_RDWR)
        return fd, str(created)

    real_fdopen = os.fdopen

    class FailingWriter:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.handle.close()

        def write(self, _text):
            raise OSError("disk full")

    def fail_fdopen(fd, *args, **kwargs):
        return FailingWriter(real_fdopen(fd, *args, **kwargs))

    monkeypatch.setattr(installer.tempfile, "mkstemp", fake_mkstemp)
    monkeypatch.setattr(installer.os, "fdopen", fail_fdopen)

    with pytest.raises(OSError, match="disk full"):
        installer._write_temp_requirements("easyai_missing_req_", ["missing-package>=2"])

    assert not created.exists()


def test_write_temp_requirements_pins_a_platform_temp_alias(
    monkeypatch,
    tmp_path,
):
    from plugin_system.requirements import install as installer

    external = tmp_path / "platform-temp"
    alias = tmp_path / "platform-temp-alias"
    external.mkdir()
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")
    created_through_alias = alias / "easyai_missing_req.txt"

    def fake_mkstemp(prefix, suffix):
        fd = os.open(
            str(created_through_alias),
            os.O_CREAT | os.O_EXCL | os.O_RDWR,
        )
        return fd, str(created_through_alias)

    monkeypatch.setattr(installer.tempfile, "mkstemp", fake_mkstemp)

    result, identity = installer._write_temp_requirements(
        "easyai_missing_req_",
        ["missing-package>=2"],
    )

    assert result == external / created_through_alias.name
    installer.remove_file_without_links(result, expected_identity=identity)
