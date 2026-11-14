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
        compatible_versions = {{
            "filelock": "3.13.0",
            "huggingface-hub": "0.36.2",
            "mcp": "1.2.0",
            "packaging": "24.2",
            "pygame": "2.5.7",
            "pygame-ce": "2.5.7",
            "pyqt-toast-notification": "1.3.3",
            "py7zz": "1.1.4",
            "qrcode": "8.2",
            "qtpy": "2.4.1",
        }}
        importlib.metadata.version = lambda name: compatible_versions.get(name.lower(), "1.0.0")

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
        errors="replace",
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


def test_runtime_check_rejects_installed_distributions_with_incompatible_versions(
    tmp_path, monkeypatch
):
    import frontend_bridge
    from core.runtime_env import requirements as runtime_requirements

    requirements = tmp_path / "requirements-runtime-core.txt"
    requirements.write_text("huggingface-hub==0.36.2\n", encoding="utf-8")
    monkeypatch.setattr(
        runtime_requirements.importlib_metadata,
        "version",
        lambda _name: "1.24.0",
    )

    report = frontend_bridge.runtime_check_report(
        requirements_file=str(requirements),
        requirements_only=True,
    )

    assert report["ok"] is False
    assert report["missingDistributions"] == ["huggingface-hub"]
    assert "1.24.0 does not satisfy" in str(report["message"])


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

        from application.chat.presentation.updates import HeadlessUIUpdateManager, format_context_token_estimate

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
    assert "packaging" in names
    assert "filelock" in names
    assert "opencc-python-reimplemented" in names
    assert "PySide6" not in names
    assert "Pillow" in names


def test_video_decode_dependency_is_available_to_desktop_and_test_installs():
    from frontend_bridge import _iter_requirement_names

    repo_root = _repo_root()
    for requirements_name in (
        "requirements.txt",
        "requirements-dev.txt",
        "requirements-runtime-core.txt",
    ):
        names = set(_iter_requirement_names(repo_root / requirements_name))
        assert "av" in names, f"{requirements_name} must install the video decoder"


def test_runtime_core_pins_huggingface_hub_to_the_shared_compatible_version():
    from application.runtime import dependencies as runtime_dependencies

    repo_root = _repo_root()
    expected = f"huggingface-hub=={runtime_dependencies.HUGGINGFACE_HUB_VERSION}"
    requirements = repo_root / "requirements-runtime-core.txt"
    lines = {
        line.strip()
        for line in requirements.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert expected in lines


def test_runtime_requirements_keep_memory_and_moondream_dependencies_compatible():
    from application.runtime import dependencies as runtime_dependencies

    repo_root = _repo_root()
    for requirements_name in ("requirements-runtime-local-ai.txt", "requirements.txt"):
        requirements = repo_root / requirements_name
        lines = {
            line.strip()
            for line in requirements.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        assert runtime_dependencies.SENTENCE_TRANSFORMERS_SPEC in lines
        assert runtime_dependencies.TRANSFORMERS_SPEC in lines
        assert runtime_dependencies.CLICK_SPEC in lines
        assert runtime_dependencies.SPACY_SPEC in lines
        assert "mem0ai[extras]" not in lines


def _fake_runtime_pip_install(calls):
    def fake_run_pip_install(cmd, *, cwd, timeout_sec, detail_max=1600, on_output_line=None):
        calls.append(cmd)
        return ("pip_ok", "")

    return fake_run_pip_install


def test_install_runtime_dependency_requests_long_failure_detail(monkeypatch):
    from application.runtime import dependencies as runtime_dependencies

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
    from application.runtime import dependencies as runtime_dependencies

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
    from application.runtime import dependencies as runtime_dependencies

    calls = []
    monkeypatch.setattr(runtime_dependencies, "_run_pip_install", _fake_runtime_pip_install(calls))

    result = runtime_dependencies.install_runtime_dependency("huggingface_hub")

    expected = f"huggingface-hub=={runtime_dependencies.HUGGINGFACE_HUB_VERSION}"
    assert result["packageName"] == expected
    assert calls[0][:5] == [sys.executable, "-m", "pip", "install", expected]


def test_install_runtime_dependency_installs_mem0_without_broad_extras(monkeypatch):
    from application.runtime import dependencies as runtime_dependencies

    calls = []
    monkeypatch.setattr(runtime_dependencies, "_run_pip_install", _fake_runtime_pip_install(calls))

    result = runtime_dependencies.install_runtime_dependency("mem0")

    assert result["packageName"] == "mem0ai"
    assert calls[0][:11] == [
        sys.executable,
        "-m",
        "pip",
        "install",
        runtime_dependencies.MEM0_SPEC,
        runtime_dependencies.CLICK_SPEC,
        runtime_dependencies.SPACY_SPEC,
        runtime_dependencies.SENTENCE_TRANSFORMERS_SPEC,
        runtime_dependencies.FASTEMBED_SPEC,
        runtime_dependencies.TRANSFORMERS_SPEC,
        runtime_dependencies.HUGGINGFACE_HUB_SPEC,
    ]
    assert "mem0ai[extras]" not in calls[0]


def test_memory_runtime_dependency_check_detects_an_old_huggingface_version():
    from application.runtime import dependencies as runtime_dependencies

    versions = {
        "click": "8.1.8",
        "fastembed": "0.7.3",
        "huggingface-hub": "1.24.0",
        "mem0ai": "2.0.12",
        "sentence-transformers": "5.2.2",
        "spacy": "3.8.11",
        "transformers": "4.57.1",
    }

    issues = runtime_dependencies.runtime_dependency_issues(
        "mem0",
        installed_versions=versions,
    )

    assert [issue.name for issue in issues] == ["huggingface-hub"]
    assert issues[0].installed_version == "1.24.0"


def test_memory_runtime_dependency_check_checks_the_complete_group():
    from application.runtime import dependencies as runtime_dependencies

    issues = runtime_dependencies.runtime_dependency_issues(
        "mem0",
        installed_versions={"mem0ai": "2.0.12"},
    )

    assert [issue.requirement for issue in issues] == list(
        runtime_dependencies.MEMORY_RUNTIME_PACKAGE_SPECS[1:]
    )


def test_memory_runtime_dependency_check_accepts_the_compatible_group():
    from application.runtime import dependencies as runtime_dependencies

    versions = {
        "click": "8.1.8",
        "fastembed": "0.7.3",
        "huggingface-hub": "0.36.2",
        "mem0ai": "2.0.12",
        "sentence-transformers": "5.2.2",
        "spacy": "3.8.11",
        "transformers": "4.57.1",
    }

    assert (
        runtime_dependencies.runtime_dependency_issues(
            "mem0",
            installed_versions=versions,
        )
        == ()
    )


def test_install_runtime_dependency_keeps_sentence_transformers_compatible(monkeypatch):
    from application.runtime import dependencies as runtime_dependencies

    calls = []
    monkeypatch.setattr(runtime_dependencies, "_run_pip_install", _fake_runtime_pip_install(calls))

    result = runtime_dependencies.install_runtime_dependency("sentence_transformers")

    assert result["packageName"] == "sentence-transformers"
    assert calls[0][:7] == [
        sys.executable,
        "-m",
        "pip",
        "install",
        runtime_dependencies.SENTENCE_TRANSFORMERS_SPEC,
        runtime_dependencies.TRANSFORMERS_SPEC,
        runtime_dependencies.HUGGINGFACE_HUB_SPEC,
    ]


def test_install_runtime_dependency_invalidates_import_caches_after_success(monkeypatch):
    from application.runtime import dependencies as runtime_dependencies

    calls = []
    invalidated = []
    monkeypatch.setattr(runtime_dependencies, "_run_pip_install", _fake_runtime_pip_install(calls))
    monkeypatch.setattr(runtime_dependencies.importlib, "invalidate_caches", lambda: invalidated.append(True))

    runtime_dependencies.install_runtime_dependency("openai")

    assert invalidated == [True]


def test_install_runtime_dependency_uses_manifest_china_index_by_default(monkeypatch):
    from application.runtime import dependencies as runtime_dependencies

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
    from application.runtime import dependencies as runtime_dependencies

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
    from application.runtime import dependencies as runtime_dependencies

    calls = []

    monkeypatch.setenv("SHINSEKAI_PIP_INDEX_URL", "https://mirror.example/simple")
    monkeypatch.setenv("SHINSEKAI_PIP_INSTALL_ARGS", "--index-url=https://custom.example/simple")
    monkeypatch.setattr(runtime_dependencies, "_run_pip_install", _fake_runtime_pip_install(calls))

    runtime_dependencies.install_runtime_dependency("openai")

    assert "-i" not in calls[0]
    assert "https://mirror.example/simple" not in calls[0]
    assert "--index-url=https://custom.example/simple" in calls[0]


def test_install_runtime_dependency_does_not_add_index_when_pip_args_disable_index(monkeypatch):
    from application.runtime import dependencies as runtime_dependencies

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

    from core.runtime_env import pip_runner
    from application.runtime import dependencies as runtime_dependencies

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


def test_install_perception_runtime_dependency_installs_pytorch_and_pins_torch_constraints(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from application.runtime import dependencies as runtime_dependencies

    rel = Path("runtime/python.exe") if os.name == "nt" else Path("runtime/bin/python3")
    fake_py = tmp_path / rel
    fake_py.parent.mkdir(parents=True, exist_ok=True)
    fake_py.write_bytes(b"fake-python")

    calls: list[list[str]] = []
    seen_constraints: list[str] = []
    version_snapshots = [
        {"pillow": "12.3.0"},
        {
            "pillow": "12.3.0",
            "torch": "2.7.1+cu128",
            "torchvision": "0.22.1+cu128",
            "torchaudio": "2.7.1+cu128",
        },
        {
            "pillow": "12.3.0",
            "torch": "2.7.1+cu128",
            "torchvision": "0.22.1+cu128",
            "torchaudio": "2.7.1+cu128",
            "transformers": "4.57.1",
            "accelerate": "1.2.1",
            "huggingface-hub": runtime_dependencies.HUGGINGFACE_HUB_VERSION,
            "rapidocr-onnxruntime": "1.4.4",
        },
    ]

    def fake_installed_versions(_py):
        return version_snapshots.pop(0) if len(version_snapshots) > 1 else version_snapshots[0]

    def fake_pip_install(cmd, **kwargs):
        calls.append(list(cmd))
        if "-c" in cmd:
            c_path = Path(cmd[cmd.index("-c") + 1])
            seen_constraints.extend(c_path.read_text(encoding="utf-8").splitlines())
        on_line = kwargs.get("on_output_line")
        if on_line:
            on_line("Successfully installed packages")
        return ("pip_ok", "")

    monkeypatch.setattr(runtime_dependencies, "installed_versions_for_python", fake_installed_versions)
    monkeypatch.setattr(runtime_dependencies, "_machine_expected_pytorch_build", lambda: "cu128")
    monkeypatch.setattr(
        runtime_dependencies,
        "build_pytorch_install_plan",
        lambda reqs, _versions, **_kw: SimpleNamespace(
            requirement_lines=tuple(reqs),
            index_url="https://download.pytorch.org/whl/cu128",
            expected_build="cu128",
            install_required=True,
            force_reinstall=False,
        ),
    )
    monkeypatch.setattr(runtime_dependencies, "_run_pip_install", fake_pip_install)

    result = runtime_dependencies.install_runtime_dependency(
        "perception",
        python_path=str(fake_py),
    )

    assert result["moduleName"] == "perception"
    assert Path(result["pythonPath"]) == fake_py.resolve()
    assert len(calls) == 2
    assert calls[0][0] == str(fake_py.resolve())
    assert "https://download.pytorch.org/whl/cu128" in calls[0]
    assert calls[1][0] == str(fake_py.resolve())
    assert runtime_dependencies.PERCEPTION_TRANSFORMERS_SPEC in calls[1]
    assert runtime_dependencies.PERCEPTION_ACCELERATE_SPEC in calls[1]
    assert runtime_dependencies.HUGGINGFACE_HUB_SPEC in calls[1]
    assert runtime_dependencies.PERCEPTION_RAPIDOCR_SPEC in calls[1]
    assert runtime_dependencies.PERCEPTION_PILLOW_SPEC not in calls[1]
    assert "torch==2.7.1" in seen_constraints
    assert "torchvision==0.22.1" in seen_constraints


def test_declarative_runtime_dependency_registry_supports_custom_bundles_and_protects_builtins(
    monkeypatch,
):
    from application.runtime import dependencies as runtime_dependencies
    from application.runtime.dependency_registry import (
        RUNTIME_DEPENDENCY_REGISTRY,
        RuntimeDependencySpec,
        register_runtime_dependency,
    )

    with pytest.raises(ValueError, match="reserved built-in runtime dependency key"):
        register_runtime_dependency(
            RuntimeDependencySpec(
                key="perception",
                package_specs=("pillow>=10.0",),
            )
        )

    custom_spec = RuntimeDependencySpec(
        key="plugin_ocr_bundle",
        package_specs=("rapidocr-onnxruntime>=1.3,<2.0", "pillow>=10.0"),
        install_only_unsatisfied=True,
        default_label="Plugin OCR runtime",
        success_message="Installed Plugin OCR runtime bundle",
    )
    register_runtime_dependency(custom_spec)
    try:
        issues = runtime_dependencies.runtime_dependency_issues(
            "plugin_ocr_bundle",
            installed_versions={"pillow": "11.0.0"},
        )
        assert [issue.name for issue in issues] == ["rapidocr-onnxruntime"]

        calls: list[list[str]] = []
        installed_state = {"pillow": "11.0.0"}

        def fake_pip_and_record(cmd, *, cwd, timeout_sec, detail_max=1600, on_output_line=None):
            calls.append(cmd)
            installed_state["rapidocr-onnxruntime"] = "1.4.4"
            return ("pip_ok", "")

        monkeypatch.setattr(
            runtime_dependencies,
            "installed_versions_for_python",
            lambda _py=None: dict(installed_state),
        )
        monkeypatch.setattr(
            runtime_dependencies,
            "_run_pip_install",
            fake_pip_and_record,
        )
        result = runtime_dependencies.install_runtime_dependency("plugin_ocr_bundle")
        assert result["packageName"] == "Plugin OCR runtime"
        assert result["message"] == "Installed Plugin OCR runtime bundle"
        assert Path(result["pythonPath"]) == Path(sys.executable)
        assert len(calls) == 1
        assert calls[0][0] == sys.executable
        assert "rapidocr-onnxruntime>=1.3,<2.0" in calls[0]
        assert "pillow>=10.0" not in calls[0]
    finally:
        assert RUNTIME_DEPENDENCY_REGISTRY.unregister("plugin_ocr_bundle") is True


def test_install_runtime_dependency_reports_host_pytorch_pin_conflict_and_verifies_bundle(
    tmp_path, monkeypatch
):
    from application.runtime import dependencies as runtime_dependencies
    from application.runtime.dependency_registry import (
        RuntimeDependencyRegistry,
        RuntimeDependencySpec,
    )

    if sys.platform == "darwin":
        pytest.skip("Host-pinned CUDA/CPU PyTorch plan applies to non-macOS platforms")

    rel = Path("runtime/python.exe") if os.name == "nt" else Path("runtime/bin/python3")
    fake_py = tmp_path / rel
    fake_py.parent.mkdir(parents=True, exist_ok=True)
    fake_py.write_bytes(b"fake-python")

    registry = RuntimeDependencyRegistry()
    runtime_dependencies._register_builtin_runtime_dependencies(registry)
    registry.register(
        RuntimeDependencySpec(
            key="future_torch_bundle",
            package_specs=("torch>=2.10", "pillow>=10.0"),
            pytorch_specs=("torch>=2.10",),
            install_only_unsatisfied=True,
        )
    )

    pip_calls: list[list[str]] = []
    monkeypatch.setattr(
        runtime_dependencies,
        "installed_versions_for_python",
        lambda _py: {"torch": "2.7.1+cu128", "pillow": "11.0.0"},
    )
    monkeypatch.setattr(runtime_dependencies, "_machine_expected_pytorch_build", lambda: "cu128")
    monkeypatch.setattr(
        runtime_dependencies,
        "_run_pip_install",
        _fake_runtime_pip_install(pip_calls),
    )

    with pytest.raises(RuntimeError) as exc_info:
        runtime_dependencies.install_runtime_dependency(
            "future_torch_bundle",
            python_path=str(fake_py),
            registry=registry,
        )

    err_text = str(exc_info.value)
    assert pip_calls == []
    assert "torch>=2.10" in err_text
    assert "torch==2.7.1" in err_text

    # Post-install verification must also fail if pip returns ok without satisfying the bundle.
    registry.register(
        RuntimeDependencySpec(
            key="unmet_after_pip_bundle",
            package_specs=("torch>=2.10", "rapidocr-onnxruntime>=1.3"),
            pin_installed_torch=True,
            install_only_unsatisfied=True,
        )
    )
    monkeypatch.setattr(
        runtime_dependencies,
        "installed_versions_for_python",
        lambda _py: {"torch": "2.7.1+cu128", "rapidocr-onnxruntime": "1.4.4"},
    )
    with pytest.raises(RuntimeError) as post_exc:
        runtime_dependencies.install_runtime_dependency(
            "unmet_after_pip_bundle",
            python_path=str(fake_py),
            registry=registry,
        )
    post_text = str(post_exc.value)
    assert "does not satisfy torch>=2.10" in post_text
    assert "conflicts with host-pinned torch==2.7.1" in post_text


def test_custom_bundle_defaults_to_chat_interpreter_instead_of_perception_python(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from application.runtime import dependencies as runtime_dependencies
    from application.runtime.dependency_registry import (
        RuntimeDependencyRegistry,
        RuntimeDependencySpec,
    )

    exe_name = "python.exe" if os.name == "nt" else "python3"
    perception_py = tmp_path / "perception_env" / exe_name
    perception_py.parent.mkdir(parents=True, exist_ok=True)
    perception_py.write_bytes(b"fake-perception-python")

    bundle_py = tmp_path / "bundle_env" / exe_name
    bundle_py.parent.mkdir(parents=True, exist_ok=True)
    bundle_py.write_bytes(b"fake-bundle-python")

    caller_py = tmp_path / "caller_env" / exe_name
    caller_py.parent.mkdir(parents=True, exist_ok=True)
    caller_py.write_bytes(b"fake-caller-python")

    monkeypatch.setenv("SHINSEKAI_PERCEPTION_PYTHON", str(perception_py))
    state = SimpleNamespace(
        project_root_dir=str(tmp_path),
        app_root_dir=str(tmp_path),
        config_manager=SimpleNamespace(
            config=SimpleNamespace(
                api_config=SimpleNamespace(perception_python_path=str(perception_py))
            )
        ),
    )

    registry = RuntimeDependencyRegistry()
    runtime_dependencies._register_builtin_runtime_dependencies(registry)
    registry.register(
        RuntimeDependencySpec(
            key="chat_plugin_bundle",
            package_specs=("rapidocr-onnxruntime>=1.3",),
            install_only_unsatisfied=True,
        )
    )
    registry.register(
        RuntimeDependencySpec(
            key="dedicated_worker_bundle",
            package_specs=("rapidocr-onnxruntime>=1.3",),
            install_only_unsatisfied=True,
            target_python=str(bundle_py),
        )
    )

    versions_by_exe: dict[str, dict[str, str]] = {}
    seen_executables: list[str] = []

    def fake_versions(py_exe):
        return dict(versions_by_exe.get(str(Path(py_exe).resolve()), {}))

    def fake_pip(cmd, *, cwd, timeout_sec, detail_max=1600, on_output_line=None):
        exe_key = str(Path(cmd[0]).resolve())
        seen_executables.append(cmd[0])
        versions_by_exe[exe_key] = {
            "pillow": "12.3.0",
            "torch": "2.7.1+cu128",
            "torchvision": "0.22.1+cu128",
            "torchaudio": "2.7.1+cu128",
            "transformers": "4.57.1",
            "accelerate": "1.2.1",
            "huggingface-hub": runtime_dependencies.HUGGINGFACE_HUB_VERSION,
            "rapidocr-onnxruntime": "1.4.4",
        }
        return ("pip_ok", "")

    monkeypatch.setattr(runtime_dependencies, "installed_versions_for_python", fake_versions)
    monkeypatch.setattr(runtime_dependencies, "_machine_expected_pytorch_build", lambda: "cpu")
    monkeypatch.setattr(runtime_dependencies, "_run_pip_install", fake_pip)

    # 1. Custom bundle without pythonPath installs into sys.executable, NOT perception_python_path.
    chat_result = runtime_dependencies.install_runtime_dependency(
        "chat_plugin_bundle",
        _state=state,
        registry=registry,
    )
    assert Path(chat_result["pythonPath"]) == Path(sys.executable)
    assert Path(chat_result["pythonPath"]).resolve() != perception_py.resolve()

    # 2. Custom bundle with explicit caller python_path installs into caller_py.
    caller_result = runtime_dependencies.install_runtime_dependency(
        "chat_plugin_bundle",
        python_path=str(caller_py),
        _state=state,
        registry=registry,
    )
    assert Path(caller_result["pythonPath"]) == caller_py.resolve()

    # 3. Custom bundle declaring target_python installs into bundle_py when python_path is omitted.
    worker_result = runtime_dependencies.install_runtime_dependency(
        "dedicated_worker_bundle",
        _state=state,
        registry=registry,
    )
    assert Path(worker_result["pythonPath"]) == bundle_py.resolve()

    # 4. Built-in perception bundle still resolves perception_python_path when python_path is omitted.
    perception_result = runtime_dependencies.install_runtime_dependency(
        "perception",
        _state=state,
        registry=registry,
    )
    assert Path(perception_result["pythonPath"]) == perception_py.resolve()


