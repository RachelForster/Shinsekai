"""Unit tests ensuring runtime dependency host constraints stay scoped to host Python."""

from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

from application.runtime import dependencies as runtime_dependencies
from application.runtime.dependency_registry import RuntimeDependencyRegistry, RuntimeDependencySpec
from core.runtime_env import constraints


def _fake_python_binary(env_root: Path) -> Path:
    rel = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    exe = env_root / rel
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"fake-python")
    return exe


def _patch_core_constraints(monkeypatch, tmp_path: Path) -> None:
    core_req = tmp_path / "requirements-runtime-core.txt"
    core_req.write_text("huggingface-hub==0.36.2\nfilelock>=3.13,<4\n", encoding="utf-8")
    monkeypatch.setattr(constraints, "host_core_requirements_path", lambda _root=None: core_req)


def _capture_pip_calls(monkeypatch) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def fake_run(cmd, *, cwd, detail_max=4000, timeout_sec=900, on_output_line=None):
        c_texts = [
            Path(cmd[i + 1]).read_text(encoding="utf-8")
            for i, token in enumerate(cmd)
            if token == "-c"
        ]
        calls.append({"cmd": list(cmd), "constraints_texts": c_texts})
        return ("pip_ok", "")

    monkeypatch.setattr(runtime_dependencies, "_run_pip_install", fake_run)
    return calls


def test_targets_host_python_environment_scopes_host_vs_external_and_venv(tmp_path: Path) -> None:
    assert runtime_dependencies.targets_host_python_environment(None) is True
    assert runtime_dependencies.targets_host_python_environment(sys.executable) is True

    sibling = Path(sys.executable).with_name("pythonw.exe" if os.name == "nt" else "python3")
    assert runtime_dependencies.targets_host_python_environment(sibling) is True

    external_py = _fake_python_binary(tmp_path / "external_env")
    assert runtime_dependencies.targets_host_python_environment(external_py) is False

    venv_root = tmp_path / "custom_venv"
    venv_bin = venv_root / ("Scripts" if os.name == "nt" else "bin")
    venv_bin.mkdir(parents=True)
    (venv_root / "pyvenv.cfg").write_text("include-system-site-packages = false\n", encoding="utf-8")
    venv_py = venv_bin / Path(sys.executable).name
    try:
        venv_py.symlink_to(Path(sys.executable))
    except OSError:
        venv_py.write_bytes(b"venv-python")
    assert runtime_dependencies.targets_host_python_environment(venv_py) is False


def test_generic_install_applies_core_constraints_only_for_host_python(
    monkeypatch, tmp_path: Path
) -> None:
    _patch_core_constraints(monkeypatch, tmp_path)
    calls = _capture_pip_calls(monkeypatch)

    runtime_dependencies.install_runtime_dependency("openai")
    assert len(calls) == 1
    assert calls[0]["constraints_texts"] == ["huggingface-hub==0.36.2\nfilelock<4,>=3.13\n"]

    calls.clear()
    external_py = _fake_python_binary(tmp_path / "isolated_env")
    result = runtime_dependencies.install_runtime_dependency(
        "openai",
        python_path=str(external_py),
    )
    assert Path(result["pythonPath"]) == external_py.resolve()
    assert len(calls) == 1
    assert calls[0]["constraints_texts"] == []


def test_staged_install_applies_core_constraints_only_for_host_python(
    monkeypatch, tmp_path: Path
) -> None:
    _patch_core_constraints(monkeypatch, tmp_path)
    calls = _capture_pip_calls(monkeypatch)
    external_py = _fake_python_binary(tmp_path / "perception_external")

    registry = RuntimeDependencyRegistry()
    registry.register(
        RuntimeDependencySpec(
            key="host_bundle",
            package_specs=("filelock>=3.13",),
            install_only_unsatisfied=True,
        )
    )
    registry.register(
        RuntimeDependencySpec(
            key="external_filelock4_bundle",
            package_specs=("filelock>=4",),
            install_only_unsatisfied=True,
            target_python=str(external_py),
        )
    )

    installed_state: dict[str, dict[str, str]] = {}

    def fake_installed(py_exe):
        return dict(installed_state.get(str(Path(py_exe).resolve()), {}))

    def fake_staged_pip(cmd, *, cwd, detail_max=4000, timeout_sec=900, on_output_line=None):
        c_texts = [
            Path(cmd[i + 1]).read_text(encoding="utf-8")
            for i, token in enumerate(cmd)
            if token == "-c"
        ]
        calls.append({"cmd": list(cmd), "constraints_texts": c_texts})
        target_key = str(Path(cmd[0]).resolve())
        installed_state[target_key] = {"filelock": "4.1.0"}
        return ("pip_ok", "")

    monkeypatch.setattr(runtime_dependencies, "installed_versions_for_python", fake_installed)
    monkeypatch.setattr(runtime_dependencies, "_run_pip_install", fake_staged_pip)

    runtime_dependencies.install_runtime_dependency(
        "host_bundle",
        python_path=sys.executable,
        registry=registry,
    )
    assert len(calls) == 1
    assert calls[0]["constraints_texts"] == ["huggingface-hub==0.36.2\nfilelock<4,>=3.13\n"]

    calls.clear()
    ext_result = runtime_dependencies.install_runtime_dependency(
        "external_filelock4_bundle",
        registry=registry,
    )
    assert Path(ext_result["pythonPath"]) == external_py.resolve()
    assert len(calls) == 1
    assert calls[0]["constraints_texts"] == []
