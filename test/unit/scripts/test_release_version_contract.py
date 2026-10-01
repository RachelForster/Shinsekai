from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github/workflows/release.yml"


def _step(job: str, name: str) -> dict:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return next(step for step in workflow["jobs"][job]["steps"] if step.get("name") == name)


@pytest.fixture
def bash() -> str:
    executable = shutil.which("bash")
    if os.name == "nt":
        git = shutil.which("git")
        if git:
            git_bash = Path(git).parent.parent / "bin/bash.exe"
            if git_bash.is_file():
                executable = str(git_bash)
    if not executable:
        pytest.skip("Bash is required to execute the release workflow contract")
    return executable


def _run_step(bash: str, tmp_path: Path, step: dict, **variables: str):
    output = tmp_path / "outputs.txt"
    environment = {
        **os.environ,
        "GITHUB_OUTPUT": output.as_posix(),
        **variables,
    }
    result = subprocess.run(
        [bash, "--noprofile", "--norc", "-e", "-o", "pipefail"],
        input=step["run"],
        cwd=tmp_path,
        env=environment,
        encoding="utf-8",
        capture_output=True,
        timeout=20,
    )
    values = (
        dict(
            line.split("=", 1)
            for line in output.read_text(encoding="utf-8").splitlines()
        )
        if output.is_file()
        else {}
    )
    return result, values


@pytest.mark.parametrize(
    "tag,manual,expected_prerelease",
    [
        ("v2.5.0", False, "false"),
        ("v2.5.0-rc.1", False, "true"),
        ("v2.5.0", True, "false"),
        ("v2.5.0-rc.2", True, "true"),
    ],
)
def test_valid_release_tags_use_synced_version_and_preserve_rc_status(
    bash, tmp_path, tag, manual, expected_prerelease
):
    (tmp_path / "VERSION").write_bytes(b"2.5.0\r\n")
    notes = tmp_path / "docs/releases/2.5.0.md"
    notes.parent.mkdir(parents=True)
    notes.write_text("# User-facing release notes\n", encoding="utf-8")
    result, values = _run_step(
        bash,
        tmp_path,
        _step("tag", "Resolve release tag"),
        INPUT_TAG=tag if manual else "",
        INPUT_PRERELEASE=expected_prerelease if manual else "",
        GITHUB_REF="refs/heads/release/2.5" if manual else f"refs/tags/{tag}",
        GITHUB_REF_NAME="release/2.5" if manual else tag,
    )
    assert result.returncode == 0, result.stderr
    assert values == {
        "tag": tag,
        "prerelease": expected_prerelease,
        "make_latest": "false" if expected_prerelease == "true" else "true",
    }


@pytest.mark.parametrize(
    "tag,version,notes,prerelease,message",
    [
        ("v2.4.1", "2.4.0", "notes", "false", "must match VERSION"),
        ("v2.5.0", "2.5.0", None, "false", "Missing release notes"),
        ("v2.5.0", "2.5.0", "", "false", "Missing release notes"),
        ("v2.5.0-rc.1", "2.5.0", "notes", "false", "RC tags must remain prereleases"),
        ("v2.5", "2.5.0", "notes", "false", "Invalid release tag"),
    ],
)
def test_invalid_release_inputs_fail_before_publishing_outputs(
    bash, tmp_path, tag, version, notes, prerelease, message
):
    (tmp_path / "VERSION").write_text(version, encoding="utf-8")
    if notes is not None:
        notes_path = tmp_path / f"docs/releases/{version}.md"
        notes_path.parent.mkdir(parents=True)
        notes_path.write_text(notes, encoding="utf-8")
    result, values = _run_step(
        bash,
        tmp_path,
        _step("tag", "Resolve release tag"),
        INPUT_TAG=tag,
        INPUT_PRERELEASE=prerelease,
        GITHUB_REF="refs/heads/release/2.5",
        GITHUB_REF_NAME="release/2.5",
    )
    assert result.returncode != 0
    assert message in result.stderr
    assert values == {}


@pytest.mark.parametrize("tag", ["v2.5.0", "v2.5.0-rc.1"])
def test_rc_and_stable_releases_share_curated_notes(bash, tmp_path, tag):
    result, values = _run_step(
        bash,
        tmp_path,
        _step("release", "Resolve release notes"),
        RELEASE_TAG=tag,
    )
    assert result.returncode == 0, result.stderr
    assert values == {"path": "docs/releases/2.5.0.md"}
    release = _step("release", "Create or update release")
    assert release["with"]["body_path"] == "${{ steps.notes.outputs.path }}"
    assert release["with"]["generate_release_notes"] is True


def test_repository_release_versions_and_notes_are_synchronized():
    version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    frontend = REPO_ROOT / "frontend"
    package_json = json.loads((frontend / "package.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (frontend / "src-tauri/runtime_manifest.json").read_text(encoding="utf-8")
    )
    assert package_json["version"] == version
    assert manifest["version"] == version
    cargo = (frontend / "src-tauri/Cargo.toml").read_text(encoding="utf-8")
    package = cargo.split("[package]", 1)[1].split("\n[", 1)[0]
    assert (
        re.search(r'^version = "([^"]+)"$', package, re.MULTILINE).group(1)
        == version
    )
    lock = (frontend / "src-tauri/Cargo.lock").read_text(encoding="utf-8")
    assert (
        re.search(r'name = "shinsekai-desktop"\nversion = "([^"]+)"', lock).group(1)
        == version
    )
    assert (
        (REPO_ROOT / f"docs/releases/{version}.md")
        .read_text(encoding="utf-8")
        .strip()
    )
