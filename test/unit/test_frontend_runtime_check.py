from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path


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
    assert "PySide6" in names
