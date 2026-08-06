from __future__ import annotations

import os
from pathlib import Path

import pytest

from config import tts_provider_config
from config.tts_provider_config import default_tts_work_path, installed_tts_bundles_path


def test_installed_tts_bundle_is_resolved_from_project_root_not_cwd(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    bundle = project / "data/tts_bundles/installed/gpt_sovits_v2pro"
    unrelated = tmp_path / "unrelated"
    bundle.mkdir(parents=True)
    unrelated.mkdir()
    (bundle / "api_v2.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(unrelated)

    assert installed_tts_bundles_path("gpt-sovits", project) == bundle.as_posix()


@pytest.mark.skipif(os.name == "nt", reason="symlink creation differs on Windows")
def test_installed_tts_bundle_ignores_symlinked_managed_storage(tmp_path):
    project = tmp_path / "project"
    external = tmp_path / "external"
    (project / "data").mkdir(parents=True)
    bundle = external / "installed/gpt_sovits_v2pro"
    bundle.mkdir(parents=True)
    (bundle / "api_v2.py").write_text("", encoding="utf-8")
    (project / "data/tts_bundles").symlink_to(external, target_is_directory=True)

    assert installed_tts_bundles_path("gpt-sovits", project) == ""


@pytest.mark.skipif(os.name == "nt", reason="symlink creation differs on Windows")
def test_installed_tts_bundle_ignores_symlinked_inner_bundle_root(tmp_path):
    project = tmp_path / "project"
    external = tmp_path / "external-engine"
    bundle = project / "data/tts_bundles/installed/gpt_sovits_v2pro"
    bundle.mkdir(parents=True)
    external.mkdir()
    (external / "api_v2.py").write_text("", encoding="utf-8")
    (bundle / "engine").symlink_to(external, target_is_directory=True)

    assert installed_tts_bundles_path("gpt-sovits", project) == ""


@pytest.mark.skipif(os.name == "nt", reason="symlink creation differs on Windows")
def test_installed_tts_bundle_ignores_symlinked_required_file(tmp_path):
    project = tmp_path / "project"
    external = tmp_path / "external-api.py"
    bundle = project / "data/tts_bundles/installed/gpt_sovits_v2pro"
    bundle.mkdir(parents=True)
    external.write_text("", encoding="utf-8")
    (bundle / "api_v2.py").symlink_to(external)

    assert installed_tts_bundles_path("gpt-sovits", project) == ""


def test_installed_tts_bundle_rejects_replaced_root_after_inventory(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    bundle = project / "data/tts_bundles/installed/gpt_sovits_v2pro"
    preserved = bundle.with_name("gpt_sovits_v2pro-preserved")
    bundle.mkdir(parents=True)
    (bundle / "api_v2.py").write_text("original", encoding="utf-8")
    real_inventory = (
        tts_provider_config.inspect_portable_directory_tree_with_metadata
    )
    replaced = False

    def inventory_then_replace(path):
        nonlocal replaced
        result = real_inventory(path)
        if Path(path) == bundle and not replaced:
            replaced = True
            bundle.rename(preserved)
            bundle.mkdir()
            (bundle / "api_v2.py").write_text("peer", encoding="utf-8")
        return result

    monkeypatch.setattr(
        tts_provider_config,
        "inspect_portable_directory_tree_with_metadata",
        inventory_then_replace,
    )

    assert installed_tts_bundles_path("gpt-sovits", project) == ""
    assert (bundle / "api_v2.py").read_text(encoding="utf-8") == "peer"
    assert (preserved / "api_v2.py").read_text(encoding="utf-8") == "original"


def test_tts_bundle_lookup_rejects_ambiguous_project_root(tmp_path):
    with pytest.raises(ValueError, match="project root"):
        installed_tts_bundles_path("gpt-sovits", f" {tmp_path}")


def test_default_tts_work_path_does_not_silently_trim_a_different_path():
    with pytest.raises(ValueError, match="non-portable"):
        default_tts_work_path("gpt-sovits", " data/tts_bundles/engine")
