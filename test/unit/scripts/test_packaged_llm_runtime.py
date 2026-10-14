"""Reject incomplete or stale LLM/SDK copies in actual build output."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
VERIFIER = REPO_ROOT / "frontend" / "scripts" / "verify-packaged-runtime.mjs"


@pytest.fixture
def packaged_app(tmp_path):
    app = tmp_path / "app"
    for relative_path in ("sdk", "ai/llm", "application/chat"):
        shutil.copytree(
            REPO_ROOT / relative_path,
            app / relative_path,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    runtime = app / "runtime"
    runtime.mkdir()
    (runtime / "python.exe").touch()
    (runtime / ".shinsekai-runtime.json").write_text(
        json.dumps(
            {
                "source": "python-build-standalone",
                "target": "windows-x64",
                "python": "3.10.20",
                "triple": "x86_64-pc-windows-msvc",
                "requiredFiles": ["python.exe"],
            }
        ),
        encoding="utf-8",
    )
    (app / "runtime_manifest.json").write_text("{}", encoding="utf-8")
    (app / "requirements-runtime-core.txt").write_text("", encoding="utf-8")
    return app


def _verify(app):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to exercise the packaging verifier")
    env = os.environ.copy()
    env["SHINSEKAI_TAURI_TARGET_DIR"] = str(app.parent)
    return subprocess.run(
        [node, str(VERIFIER)],
        cwd=app.parent,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )


def test_packaged_runtime_accepts_matching_llm_and_sdk_sources(packaged_app):
    result = _verify(packaged_app)

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "missing_module",
    [
        "sdk/llm_response.py",
        "ai/llm/chat_loop.py",
        "application/chat/process_supervisor.py",
        "application/chat/runtime_commands.py",
    ],
)
def test_packaged_runtime_rejects_missing_llm_modules(packaged_app, missing_module):
    (packaged_app / missing_module).unlink()

    result = _verify(packaged_app)

    assert (
        result.returncode != 0
    ), "Incomplete chat runtime passed packaging verification"
    assert missing_module in result.stderr.replace("\\", "/")


def test_packaged_runtime_rejects_old_sdk_adapter_with_new_llm(packaged_app):
    adapter_path = packaged_app / "sdk" / "adapters" / "llm.py"
    adapter_path.write_text("class LLMAdapter:\n    pass\n", encoding="utf-8")

    result = _verify(packaged_app)

    assert (
        result.returncode != 0
    ), "Mixed SDK/LLM revisions passed packaging verification"
    assert "sdk/adapters/llm.py" in result.stderr.replace("\\", "/")
