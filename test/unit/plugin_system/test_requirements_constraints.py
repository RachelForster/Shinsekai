"""Unit tests ensuring plugin pip installs enforce host core runtime constraints."""

from __future__ import annotations

from pathlib import Path

from core.runtime_env import constraints


def _setup_host_and_capture(monkeypatch, tmp_path: Path):
    from plugin_system.requirements import install as installer

    host_root = tmp_path / "host"
    host_root.mkdir()
    core_req = host_root / "requirements-runtime-core.txt"
    core_req.write_text("huggingface-hub==0.36.2\nfilelock>=3.13,<4\n", encoding="utf-8")
    (host_root / "requirements.txt").write_text("huggingface-hub==0.36.2\n", encoding="utf-8")

    monkeypatch.setattr(constraints, "host_core_requirements_path", lambda _root=None: core_req)
    monkeypatch.setattr(installer, "pip_python_executable", lambda: Path("python"))
    monkeypatch.setattr(installer, "_installed_distribution_versions", lambda: {})
    monkeypatch.setattr(installer.sys, "platform", "linux")

    calls: list[dict[str, object]] = []

    def fake_run_pip_install(cmd, *, cwd, timeout_sec, on_output_line):
        c_texts = [
            Path(cmd[i + 1]).read_text(encoding="utf-8")
            for i, token in enumerate(cmd)
            if token == "-c"
        ]
        calls.append({"cmd": list(cmd), "constraints_texts": c_texts})
        return ("pip_ok", "")

    monkeypatch.setattr(installer, "_run_pip_install", fake_run_pip_install)
    return installer, host_root, calls


def test_plugin_host_site_packages_install_receives_core_constraints(monkeypatch, tmp_path: Path) -> None:
    installer, host_root, calls = _setup_host_and_capture(monkeypatch, tmp_path)
    monkeypatch.setattr(installer, "plugin_pip_target_directory", lambda: None)

    plugin_dir = host_root / "plugins" / "demo"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "requirements.txt").write_text("missing-demo-pkg>=1.0\n", encoding="utf-8")

    assert installer.install_plugin_requirements_txt(plugin_dir) == ("pip_ok", "")
    assert len(calls) == 1
    assert calls[0]["constraints_texts"] == ["huggingface-hub==0.36.2\nfilelock<4,>=3.13\n"]


def test_plugin_isolated_target_and_host_manifests_skip_core_constraints(
    monkeypatch, tmp_path: Path
) -> None:
    installer, host_root, calls = _setup_host_and_capture(monkeypatch, tmp_path)
    target = tmp_path / "plugin_site"
    monkeypatch.setattr(installer, "plugin_pip_target_directory", lambda: target)

    plugin_dir = host_root / "plugins" / "demo"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "requirements.txt").write_text("missing-demo-pkg>=1.0\n", encoding="utf-8")

    assert installer.install_plugin_requirements_txt(plugin_dir) == ("pip_ok", "")
    assert len(calls) == 1
    assert calls[0]["constraints_texts"] == []

    calls.clear()
    monkeypatch.setattr(installer, "plugin_pip_target_directory", lambda: None)
    assert installer.install_plugin_requirements_txt(
        host_root, requirements_file="requirements-runtime-core.txt"
    ) == (
        "pip_ok",
        "",
    )
    assert len(calls) == 1
    assert calls[0]["constraints_texts"] == []
    calls.clear()
    assert installer.install_plugin_requirements_txt(
        host_root, requirements_file="requirements.txt"
    ) == (
        "pip_ok",
        "",
    )
    assert len(calls) == 1
    assert calls[0]["constraints_texts"] == []


def test_plugin_split_torch_appends_core_constraints_after_torch_constraints(
    monkeypatch, tmp_path: Path
) -> None:
    installer, host_root, calls = _setup_host_and_capture(monkeypatch, tmp_path)
    target = tmp_path / "plugin_site"
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
    monkeypatch.setattr(
        installer,
        "_build_pytorch_install_plan",
        lambda lines, installed, *, requirement_is_satisfied: original_plan(
            lines,
            installed,
            requirement_is_satisfied=requirement_is_satisfied,
            index_url="https://download.pytorch.org/whl/cu128",
            index_reason="test_cuda",
        ),
    )

    plugin_dir = host_root / "plugins" / "torch_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "requirements.txt").write_text(
        "accelerate>=1.10.0\ntorch==99.0.0\n",
        encoding="utf-8",
    )

    assert installer.install_plugin_requirements_txt(plugin_dir) == ("pip_ok", "")
    assert len(calls) == 1
    assert calls[0]["constraints_texts"] == [
        "torch==2.7.1\ntorchvision==0.22.1\ntorchaudio==2.7.1\n",
        "huggingface-hub==0.36.2\nfilelock<4,>=3.13\n",
    ]
