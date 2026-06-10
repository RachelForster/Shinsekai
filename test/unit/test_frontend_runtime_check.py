from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace


def test_desktop_core_runtime_check_does_not_import_optional_packages(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    optional_packages = (
        "PIL",
        "fastembed",
        "mcp",
        "mem0",
        "onnxruntime",
        "pandas",
        "qdrant_client",
        "rembg",
        "sentence_transformers",
    )
    script = textwrap.dedent(
        f"""
        import builtins
        import importlib.metadata
        import json
        import sys

        blocked = {optional_packages!r}
        real_import = builtins.__import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level == 0 and (
                name in blocked or any(name.startswith(prefix + ".") for prefix in blocked)
            ):
                raise ModuleNotFoundError(name)
            return real_import(name, globals, locals, fromlist, level)

        builtins.__import__ = guarded_import
        importlib.metadata.version = lambda _name: "0.0.0"

        from frontend_bridge import runtime_check_report

        report = runtime_check_report(
            project_root={str(tmp_path)!r},
            profile="desktop-core",
            requirements_file="requirements-runtime-core.txt",
        )
        print(json.dumps(report, ensure_ascii=True))
        raise SystemExit(0 if report.get("ok") else 1)
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["ok"] is True
    assert report["profile"] == "desktop-core"
    assert report["missingDistributions"] == []


def test_runtime_requirements_parser_follows_recursive_includes(tmp_path):
    from frontend_bridge import _iter_requirement_names

    core = tmp_path / "requirements-runtime-core.txt"
    local_ai = tmp_path / "requirements-runtime-local-ai.txt"
    core.write_text("pyyaml\npydantic>=2\n", encoding="utf-8")
    local_ai.write_text("--requirement=requirements-runtime-core.txt\nfastembed\n", encoding="utf-8")

    assert list(_iter_requirement_names(local_ai)) == [
        "pyyaml",
        "pydantic",
        "fastembed",
    ]


def test_runtime_requirements_parser_uses_pygame_ce_on_windows_arm64(tmp_path, monkeypatch):
    import frontend_bridge

    requirements = tmp_path / "requirements-runtime-core.txt"
    requirements.write_text(
        "\n".join(
            [
                'pygame-ce>=2.5.7; sys_platform == "win32" and platform_machine == "ARM64"',
                'pygame; sys_platform != "win32" or platform_machine != "ARM64"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(frontend_bridge.sys, "platform", "win32")
    monkeypatch.setattr(frontend_bridge.platform, "machine", lambda: "ARM64")

    assert list(frontend_bridge._iter_requirement_names(requirements)) == ["pygame-ce"]


def test_full_requirements_use_pygame_ce_on_windows_arm64(monkeypatch):
    import frontend_bridge

    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.setattr(frontend_bridge.sys, "platform", "win32")
    monkeypatch.setattr(frontend_bridge.platform, "machine", lambda: "ARM64")

    names = list(frontend_bridge._iter_requirement_names(repo_root / "requirements.txt"))

    assert "pygame-ce" in names
    assert "pygame" not in names


def test_runtime_core_asr_markers_skip_platforms_without_native_wheels(monkeypatch):
    import frontend_bridge

    repo_root = Path(__file__).resolve().parents[2]
    requirements = repo_root / "requirements-runtime-core.txt"

    monkeypatch.setattr(frontend_bridge.sys, "platform", "darwin")
    monkeypatch.setattr(frontend_bridge.platform, "machine", lambda: "arm64")
    names = set(frontend_bridge._iter_requirement_names(requirements))
    assert "pyaudio" not in names
    assert "vosk" in names

    monkeypatch.setattr(frontend_bridge.sys, "platform", "win32")
    monkeypatch.setattr(frontend_bridge.platform, "machine", lambda: "ARM64")
    names = set(frontend_bridge._iter_requirement_names(requirements))
    assert "pyaudio" not in names
    assert "vosk" not in names

    monkeypatch.setattr(frontend_bridge.sys, "platform", "linux")
    monkeypatch.setattr(frontend_bridge.platform, "machine", lambda: "x86_64")
    names = set(frontend_bridge._iter_requirement_names(requirements))
    assert "pyaudio" in names
    assert "vosk" in names


def test_runtime_core_does_not_require_opencv_distribution():
    from frontend_bridge import _iter_requirement_names

    repo_root = Path(__file__).resolve().parents[2]
    names = set(_iter_requirement_names(repo_root / "requirements-runtime-core.txt"))

    assert "opencv_python" not in names
    assert "opencv-python" not in names


def test_ui_update_manager_import_does_not_require_cv2():
    repo_root = Path(__file__).resolve().parents[2]
    script = textwrap.dedent(
        """
        import builtins

        real_import = builtins.__import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level == 0 and (name == "cv2" or name.startswith("cv2.")):
                raise ModuleNotFoundError(name)
            return real_import(name, globals, locals, fromlist, level)

        builtins.__import__ = guarded_import

        from core.runtime.ui_update_manager import HeadlessUIUpdateManager, format_context_token_estimate

        HeadlessUIUpdateManager()
        assert format_context_token_estimate({}) == "tokens sys 0 | hist 0 | tools 0 | total 0"
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_runtime_manifest_defines_optional_requirement_profiles():
    repo_root = Path(__file__).resolve().parents[2]
    manifest = json.loads((repo_root / "frontend/src-tauri/runtime_manifest.json").read_text(encoding="utf-8"))
    profiles = manifest["profiles"]

    assert "targets" not in manifest
    assert profiles["desktop-core"]["requirements"] == "requirements-runtime-core.txt"
    assert "media" not in profiles
    assert profiles["local-ai"]["extends"] == "desktop-core"
    assert profiles["local-ai"]["requirements"] == "requirements-runtime-local-ai.txt"
    assert profiles["full"]["requirements"] == "requirements.txt"


def test_runtime_core_requirements_include_bridge_startup_sdks():
    from frontend_bridge import _iter_requirement_names

    repo_root = Path(__file__).resolve().parents[2]
    names = set(_iter_requirement_names(repo_root / "requirements-runtime-core.txt"))

    assert "openai" in names
    assert "google-genai" in names
    assert "anthropic" in names
    assert "tiktoken" in names
    assert "opencc-python-reimplemented" in names
    assert "PySide6" in names
    assert "Pillow" in names


def test_install_runtime_dependency_uses_runtime_pip_index_and_extra_args(monkeypatch):
    from frontend_bridge_core import runtime_dependencies

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setenv("SHINSEKAI_PIP_INDEX_URL", "https://mirror.example/simple")
    monkeypatch.setenv("SHINSEKAI_PIP_INSTALL_ARGS", "--timeout 60 --trusted-host mirror.example")
    monkeypatch.setattr(runtime_dependencies.subprocess, "run", fake_run)

    result = runtime_dependencies.install_runtime_dependency("openai")

    assert result["packageName"] == "openai"
    assert calls[0][0] == [
        sys.executable,
        "-m",
        "pip",
        "install",
        "openai",
        "-i",
        "https://mirror.example/simple",
        "--timeout",
        "60",
        "--trusted-host",
        "mirror.example",
    ]
    assert calls[0][1]["env"]["PYTHONUTF8"] == "1"


def test_install_runtime_dependency_uses_manifest_china_index_by_default(monkeypatch):
    from frontend_bridge_core import runtime_dependencies

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.delenv("PIP_INDEX_URL", raising=False)
    monkeypatch.delenv("PIP_EXTRA_INDEX_URL", raising=False)
    monkeypatch.delenv("PIP_NO_INDEX", raising=False)
    monkeypatch.delenv("PIP_CONFIG_FILE", raising=False)
    monkeypatch.delenv("SHINSEKAI_PIP_INDEX_URL", raising=False)
    monkeypatch.delenv("SHINSEKAI_PIP_INDEX_URLS", raising=False)
    monkeypatch.delenv("SHINSEKAI_PIP_INSTALL_ARGS", raising=False)
    monkeypatch.delenv("SHINSEKAI_RUNTIME_SOURCE", raising=False)
    monkeypatch.setattr(runtime_dependencies.subprocess, "run", fake_run)

    runtime_dependencies.install_runtime_dependency("openai")

    assert "-i" in calls[0]
    assert calls[0][calls[0].index("-i") + 1] == "https://pypi.tuna.tsinghua.edu.cn/simple/"
    assert "https://mirrors.aliyun.com/pypi/simple/" in calls[0]
    assert "https://pypi.org/simple/" in calls[0]


def test_install_runtime_dependency_does_not_add_index_when_pip_args_pick_one(monkeypatch):
    from frontend_bridge_core import runtime_dependencies

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setenv("SHINSEKAI_PIP_INDEX_URL", "https://mirror.example/simple")
    monkeypatch.setenv("SHINSEKAI_PIP_INSTALL_ARGS", "--index-url=https://custom.example/simple")
    monkeypatch.setattr(runtime_dependencies.subprocess, "run", fake_run)

    runtime_dependencies.install_runtime_dependency("openai")

    assert "-i" not in calls[0]
    assert "https://mirror.example/simple" not in calls[0]
    assert "--index-url=https://custom.example/simple" in calls[0]


def test_install_runtime_dependency_does_not_add_index_when_pip_args_disable_index(monkeypatch):
    from frontend_bridge_core import runtime_dependencies

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setenv("SHINSEKAI_PIP_INDEX_URL", "https://mirror.example/simple")
    monkeypatch.setenv("SHINSEKAI_PIP_INSTALL_ARGS", "--no-index --find-links C:\\wheelhouse")
    monkeypatch.setattr(runtime_dependencies.subprocess, "run", fake_run)

    runtime_dependencies.install_runtime_dependency("openai")

    assert "-i" not in calls[0]
    assert "https://mirror.example/simple" not in calls[0]
    assert "--no-index" in calls[0]


def test_install_runtime_dependency_redacts_credential_urls_from_output(monkeypatch):
    from frontend_bridge_core import runtime_dependencies

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout="Looking in indexes: https://user:secret-token@mirror.example/simple",
            stderr="",
        )

    monkeypatch.setenv("SHINSEKAI_PIP_INDEX_URL", "https://user:secret-token@mirror.example/simple")
    monkeypatch.delenv("SHINSEKAI_PIP_INSTALL_ARGS", raising=False)
    monkeypatch.setattr(runtime_dependencies.subprocess, "run", fake_run)

    result = runtime_dependencies.install_runtime_dependency("openai")

    assert "secret-token" not in result["pipOutput"]
    assert "https://user:***@mirror.example/simple" in result["pipOutput"]
