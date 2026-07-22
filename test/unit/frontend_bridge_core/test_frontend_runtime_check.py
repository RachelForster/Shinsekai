from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (
            (parent / "requirements.txt").is_file()
            and (parent / "frontend/src-tauri/runtime_manifest.json").is_file()
        ):
            return parent
    raise AssertionError("Could not locate repository root")


def test_runtime_context_keeps_app_and_project_roots_separate(tmp_path, monkeypatch):
    from frontend_bridge import _configure_runtime_context

    launch_dir = tmp_path / "launch cwd"
    app_root = tmp_path / "Program Files" / "Shinsekai 应用"
    project_root = tmp_path / "User Data" / "项目 データ"
    launch_dir.mkdir()
    app_root.mkdir(parents=True)
    monkeypatch.chdir(launch_dir)
    monkeypatch.setenv("SHINSEKAI_SOURCE_ROOT", "before-test")
    monkeypatch.setenv("SHINSEKAI_APP_ROOT", "before-test")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", "before-test")
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", "before-test")

    _repo, _dist, resolved_app_root = _configure_runtime_context(
        str(project_root),
        None,
        str(app_root),
    )
    resolved_project_root = os.environ["EASYAI_PROJECT_ROOT"]

    assert Path(resolved_app_root) == app_root.resolve()
    assert Path(resolved_project_root) == project_root.resolve()
    assert Path.cwd() == project_root.resolve()
    assert Path(os.environ["EASYAI_PROJECT_ROOT"]) == project_root.resolve()
    assert Path(os.environ["SHINSEKAI_PROJECT_ROOT"]) == project_root.resolve()
    assert Path(os.environ["SHINSEKAI_APP_ROOT"]) == app_root.resolve()


def test_runtime_context_prefers_public_project_root_override_for_legacy_launches(
    tmp_path, monkeypatch
):
    from frontend_bridge import _configure_runtime_context

    launch_dir = tmp_path / "legacy launch"
    project_root = tmp_path / "D drive data" / "用户数据"
    easyai_root = tmp_path / "stale EASYAI root"
    launch_dir.mkdir()
    project_root.mkdir(parents=True)
    easyai_root.mkdir()
    monkeypatch.chdir(launch_dir)
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(easyai_root))

    _repo, _dist, _app_root = _configure_runtime_context(
        None,
        None,
        None,
    )
    resolved_project_root = os.environ["EASYAI_PROJECT_ROOT"]

    assert Path(resolved_project_root) == project_root.resolve()
    assert Path.cwd() == project_root.resolve()
    assert Path(os.environ["EASYAI_PROJECT_ROOT"]) == project_root.resolve()
    assert Path(os.environ["SHINSEKAI_PROJECT_ROOT"]) == project_root.resolve()


def test_runtime_context_creates_authoritative_environment_project_root(
    tmp_path, monkeypatch
):
    from frontend_bridge import _configure_runtime_context

    launch_dir = tmp_path / "launch"
    project_root = tmp_path / "new parent" / "new project"
    launch_dir.mkdir()
    monkeypatch.chdir(launch_dir)
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(tmp_path / "legacy root"))

    _configure_runtime_context(None, None, None)

    assert project_root.is_dir()
    assert (project_root / "data").is_dir()
    assert Path.cwd() == project_root.resolve()
    assert Path(os.environ["SHINSEKAI_PROJECT_ROOT"]) == project_root.resolve()
    assert Path(os.environ["EASYAI_PROJECT_ROOT"]) == project_root.resolve()


def test_runtime_context_rejects_environment_project_root_that_is_a_file(
    tmp_path, monkeypatch
):
    from frontend_bridge import _configure_runtime_context

    launch_dir = tmp_path / "launch"
    project_root = tmp_path / "project-root-file"
    launch_dir.mkdir()
    project_root.write_text("not a directory", encoding="utf-8")
    monkeypatch.chdir(launch_dir)
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(project_root))

    with pytest.raises(RuntimeError, match="SHINSEKAI_PROJECT_ROOT project root"):
        _configure_runtime_context(None, None, None)

    assert Path.cwd() == launch_dir.resolve()
    assert os.environ["SHINSEKAI_PROJECT_ROOT"] == str(project_root)


def test_runtime_context_rejects_project_root_whose_data_path_is_a_file(
    tmp_path, monkeypatch
):
    from frontend_bridge import _configure_runtime_context

    launch_dir = tmp_path / "launch"
    project_root = tmp_path / "project"
    launch_dir.mkdir()
    project_root.mkdir()
    (project_root / "data").write_text("not a directory", encoding="utf-8")
    monkeypatch.chdir(launch_dir)
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(project_root))

    with pytest.raises(RuntimeError, match="SHINSEKAI_PROJECT_ROOT project root"):
        _configure_runtime_context(None, None, None)

    assert Path.cwd() == launch_dir.resolve()


def test_runtime_context_fails_closed_when_environment_project_root_cannot_be_created(
    tmp_path, monkeypatch
):
    from frontend_bridge import _configure_runtime_context

    launch_dir = tmp_path / "launch"
    blocking_file = tmp_path / "not-a-parent"
    project_root = blocking_file / "project"
    launch_dir.mkdir()
    blocking_file.write_text("not a directory", encoding="utf-8")
    monkeypatch.chdir(launch_dir)
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(project_root))

    with pytest.raises(RuntimeError, match="SHINSEKAI_PROJECT_ROOT project root"):
        _configure_runtime_context(None, None, None)

    assert Path.cwd() == launch_dir.resolve()
    assert os.environ["SHINSEKAI_PROJECT_ROOT"] == str(project_root)


@pytest.mark.skipif(
    os.name == "nt" or getattr(os, "geteuid", lambda: 0)() == 0,
    reason="POSIX permission-bit behavior requires a non-root process",
)
def test_runtime_context_fails_closed_when_project_data_is_not_writable(
    tmp_path, monkeypatch
):
    from frontend_bridge import _configure_runtime_context

    launch_dir = tmp_path / "launch"
    project_root = tmp_path / "project"
    data_root = project_root / "data"
    launch_dir.mkdir()
    data_root.mkdir(parents=True)
    data_root.chmod(0o555)
    monkeypatch.chdir(launch_dir)
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(project_root))

    try:
        with pytest.raises(RuntimeError, match="not safely writable"):
            _configure_runtime_context(None, None, None)
        assert Path.cwd() == launch_dir.resolve()
    finally:
        data_root.chmod(0o755)


def test_runtime_context_does_not_fall_back_from_invalid_public_root(
    tmp_path, monkeypatch
):
    from frontend_bridge import _configure_runtime_context

    launch_dir = tmp_path / "launch"
    invalid_root = tmp_path / "invalid-root"
    legacy_root = tmp_path / "legacy-root"
    launch_dir.mkdir()
    invalid_root.write_text("not a directory", encoding="utf-8")
    legacy_root.mkdir()
    monkeypatch.chdir(launch_dir)
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(invalid_root))
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(legacy_root))

    with pytest.raises(RuntimeError, match="SHINSEKAI_PROJECT_ROOT project root"):
        _configure_runtime_context(None, None, None)

    assert Path.cwd() == launch_dir.resolve()
    assert os.environ["SHINSEKAI_PROJECT_ROOT"] == str(invalid_root)
    assert os.environ["EASYAI_PROJECT_ROOT"] == str(legacy_root)


def test_runtime_context_rejects_relative_environment_project_root(
    tmp_path, monkeypatch
):
    from frontend_bridge import _configure_runtime_context

    launch_dir = tmp_path / "launch"
    launch_dir.mkdir()
    monkeypatch.chdir(launch_dir)
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", "relative-project")

    with pytest.raises(RuntimeError, match="must be absolute"):
        _configure_runtime_context(None, None, None)

    assert Path.cwd() == launch_dir.resolve()
    assert os.environ["SHINSEKAI_PROJECT_ROOT"] == "relative-project"


def test_runtime_context_rejects_invalid_legacy_root_when_public_root_is_unset(
    tmp_path, monkeypatch
):
    from frontend_bridge import _configure_runtime_context

    launch_dir = tmp_path / "launch"
    invalid_root = tmp_path / "legacy-root-file"
    launch_dir.mkdir()
    invalid_root.write_text("not a directory", encoding="utf-8")
    monkeypatch.chdir(launch_dir)
    monkeypatch.delenv("SHINSEKAI_PROJECT_ROOT", raising=False)
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(invalid_root))

    with pytest.raises(RuntimeError, match="EASYAI_PROJECT_ROOT project root"):
        _configure_runtime_context(None, None, None)

    assert Path.cwd() == launch_dir.resolve()
    assert "SHINSEKAI_PROJECT_ROOT" not in os.environ
    assert os.environ["EASYAI_PROJECT_ROOT"] == str(invalid_root)


def test_desktop_core_runtime_check_does_not_import_optional_packages(tmp_path):
    repo_root = _repo_root()
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
        encoding="utf-8",
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

    repo_root = _repo_root()
    monkeypatch.setattr(frontend_bridge.sys, "platform", "win32")
    monkeypatch.setattr(frontend_bridge.platform, "machine", lambda: "ARM64")

    names = list(frontend_bridge._iter_requirement_names(repo_root / "requirements.txt"))

    assert "pygame-ce" in names
    assert "pygame" not in names


def test_runtime_core_asr_markers_skip_platforms_without_native_wheels(monkeypatch):
    import frontend_bridge

    repo_root = _repo_root()
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

    repo_root = _repo_root()
    names = set(_iter_requirement_names(repo_root / "requirements-runtime-core.txt"))

    assert "opencv_python" not in names
    assert "opencv-python" not in names


def test_ui_update_manager_import_does_not_require_cv2():
    repo_root = _repo_root()
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
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_runtime_manifest_defines_optional_requirement_profiles():
    repo_root = _repo_root()
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

    repo_root = _repo_root()
    names = set(_iter_requirement_names(repo_root / "requirements-runtime-core.txt"))

    assert "openai" in names
    assert "google-genai" in names
    assert "anthropic" in names
    assert "tiktoken" in names
    assert "opencc-python-reimplemented" in names
    assert "PySide6" in names
    assert "Pillow" in names


def test_runtime_core_pins_huggingface_hub_to_the_download_progress_version():
    from frontend_bridge_core import runtime_dependencies

    repo_root = _repo_root()
    expected = f"huggingface-hub=={runtime_dependencies.HUGGINGFACE_HUB_VERSION}"
    requirements = repo_root / "requirements-runtime-core.txt"
    lines = {
        line.strip()
        for line in requirements.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert expected in lines


def _fake_runtime_pip_install(calls):
    def fake_run_pip_install(cmd, *, cwd, timeout_sec, detail_max=1600, on_output_line=None):
        calls.append(cmd)
        return ("pip_ok", "")

    return fake_run_pip_install


def test_install_runtime_dependency_requests_long_failure_detail(monkeypatch):
    from frontend_bridge_core import runtime_dependencies

    captured: dict[str, int] = {}

    def fake_run_pip_install(cmd, *, cwd, timeout_sec, detail_max=1600, on_output_line=None):
        captured["detail_max"] = detail_max
        return ("pip_failed", "x" * 3999)

    monkeypatch.setattr(runtime_dependencies, "_run_pip_install", fake_run_pip_install)

    try:
        runtime_dependencies.install_runtime_dependency("openai")
    except RuntimeError as exc:
        error = exc
    else:
        raise AssertionError("install_runtime_dependency should raise on pip failure")

    assert captured["detail_max"] == 4000
    assert len(str(error)) >= 3999


def test_install_runtime_dependency_uses_runtime_pip_index_and_extra_args(monkeypatch):
    from frontend_bridge_core import runtime_dependencies

    calls = []

    monkeypatch.setenv("SHINSEKAI_PIP_INDEX_URL", "https://mirror.example/simple")
    monkeypatch.setenv("SHINSEKAI_PIP_INSTALL_ARGS", "--timeout 60 --trusted-host mirror.example")
    monkeypatch.setattr(runtime_dependencies, "_run_pip_install", _fake_runtime_pip_install(calls))

    result = runtime_dependencies.install_runtime_dependency("openai")

    assert result["packageName"] == "openai"
    assert calls[0] == [
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


def test_install_runtime_dependency_pins_huggingface_hub(monkeypatch):
    from frontend_bridge_core import runtime_dependencies

    calls = []
    monkeypatch.setattr(runtime_dependencies, "_run_pip_install", _fake_runtime_pip_install(calls))

    result = runtime_dependencies.install_runtime_dependency("huggingface_hub")

    expected = f"huggingface-hub=={runtime_dependencies.HUGGINGFACE_HUB_VERSION}"
    assert result["packageName"] == expected
    assert calls[0][:5] == [sys.executable, "-m", "pip", "install", expected]


def test_install_runtime_dependency_invalidates_import_caches_after_success(monkeypatch):
    from frontend_bridge_core import runtime_dependencies

    calls = []
    invalidated = []
    monkeypatch.setattr(runtime_dependencies, "_run_pip_install", _fake_runtime_pip_install(calls))
    monkeypatch.setattr(runtime_dependencies.importlib, "invalidate_caches", lambda: invalidated.append(True))

    runtime_dependencies.install_runtime_dependency("openai")

    assert invalidated == [True]


def test_install_runtime_dependency_uses_manifest_china_index_by_default(monkeypatch):
    from frontend_bridge_core import runtime_dependencies

    calls = []

    monkeypatch.delenv("PIP_INDEX_URL", raising=False)
    monkeypatch.delenv("PIP_EXTRA_INDEX_URL", raising=False)
    monkeypatch.delenv("PIP_NO_INDEX", raising=False)
    monkeypatch.delenv("PIP_CONFIG_FILE", raising=False)
    monkeypatch.delenv("SHINSEKAI_PIP_INDEX_URL", raising=False)
    monkeypatch.delenv("SHINSEKAI_PIP_INDEX_URLS", raising=False)
    monkeypatch.delenv("SHINSEKAI_PIP_INSTALL_ARGS", raising=False)
    monkeypatch.delenv("SHINSEKAI_RUNTIME_SOURCE", raising=False)
    monkeypatch.delenv("SHINSEKAI_MIRROR_REGION", raising=False)
    monkeypatch.setattr(runtime_dependencies, "_run_pip_install", _fake_runtime_pip_install(calls))

    runtime_dependencies.install_runtime_dependency("openai")

    assert "-i" in calls[0]
    assert calls[0][calls[0].index("-i") + 1] == "https://pypi.tuna.tsinghua.edu.cn/simple/"
    assert "https://mirrors.aliyun.com/pypi/simple/" not in calls[0]
    assert "https://mirrors.ustc.edu.cn/pypi/simple/" in calls[0]
    assert "https://pypi.org/simple/" in calls[0]


def test_install_runtime_dependency_uses_official_index_for_global_mirror_region(monkeypatch):
    from frontend_bridge_core import runtime_dependencies

    calls = []

    monkeypatch.delenv("PIP_INDEX_URL", raising=False)
    monkeypatch.delenv("PIP_EXTRA_INDEX_URL", raising=False)
    monkeypatch.delenv("PIP_NO_INDEX", raising=False)
    monkeypatch.delenv("PIP_CONFIG_FILE", raising=False)
    monkeypatch.delenv("SHINSEKAI_PIP_INDEX_URL", raising=False)
    monkeypatch.delenv("SHINSEKAI_PIP_INDEX_URLS", raising=False)
    monkeypatch.delenv("SHINSEKAI_PIP_INSTALL_ARGS", raising=False)
    monkeypatch.delenv("SHINSEKAI_RUNTIME_SOURCE", raising=False)
    monkeypatch.setenv("SHINSEKAI_MIRROR_REGION", "global")
    monkeypatch.setattr(runtime_dependencies, "_run_pip_install", _fake_runtime_pip_install(calls))

    runtime_dependencies.install_runtime_dependency("openai")

    assert "-i" in calls[0]
    assert calls[0][calls[0].index("-i") + 1] == "https://pypi.org/simple/"
    assert "https://pypi.tuna.tsinghua.edu.cn/simple/" not in calls[0]


def test_install_runtime_dependency_does_not_add_index_when_pip_args_pick_one(monkeypatch):
    from frontend_bridge_core import runtime_dependencies

    calls = []

    monkeypatch.setenv("SHINSEKAI_PIP_INDEX_URL", "https://mirror.example/simple")
    monkeypatch.setenv("SHINSEKAI_PIP_INSTALL_ARGS", "--index-url=https://custom.example/simple")
    monkeypatch.setattr(runtime_dependencies, "_run_pip_install", _fake_runtime_pip_install(calls))

    runtime_dependencies.install_runtime_dependency("openai")

    assert "-i" not in calls[0]
    assert "https://mirror.example/simple" not in calls[0]
    assert "--index-url=https://custom.example/simple" in calls[0]


def test_install_runtime_dependency_does_not_add_index_when_pip_args_disable_index(monkeypatch):
    from frontend_bridge_core import runtime_dependencies

    calls = []

    monkeypatch.setenv("SHINSEKAI_PIP_INDEX_URL", "https://mirror.example/simple")
    monkeypatch.setenv("SHINSEKAI_PIP_INSTALL_ARGS", "--no-index --find-links C:\\wheelhouse")
    monkeypatch.setattr(runtime_dependencies, "_run_pip_install", _fake_runtime_pip_install(calls))

    runtime_dependencies.install_runtime_dependency("openai")

    assert "-i" not in calls[0]
    assert "https://mirror.example/simple" not in calls[0]
    assert "--no-index" in calls[0]


def test_install_runtime_dependency_redacts_credential_urls_from_output(monkeypatch):
    import io

    from core.plugins import pip_runner
    from frontend_bridge_core import runtime_dependencies

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            self.stdout = io.StringIO(
                "Looking in indexes: https://user:secret-token@mirror.example/simple\n"
            )
            self.stderr = io.StringIO("")
            self.returncode = 0

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            pass

    monkeypatch.setenv("SHINSEKAI_PIP_INDEX_URL", "https://user:secret-token@mirror.example/simple")
    monkeypatch.delenv("SHINSEKAI_PIP_INSTALL_ARGS", raising=False)
    monkeypatch.setattr(pip_runner.subprocess, "Popen", FakePopen)

    result = runtime_dependencies.install_runtime_dependency("openai")

    assert "secret-token" not in result["pipOutput"]
    assert "https://user:***@mirror.example/simple" in result["pipOutput"]
