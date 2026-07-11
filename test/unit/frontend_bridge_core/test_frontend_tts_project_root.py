from __future__ import annotations

from pathlib import Path

from frontend_bridge_core.state import BridgeState
from frontend_bridge_core.tts import _download_tts_bundle
from ui.settings_ui.tts import tts_bundle_manifest, tts_bundle_worker


def test_tts_bundle_download_uses_bridge_project_root(tmp_path, monkeypatch):
    app_root = tmp_path / "Program Files" / "Shinsekai App"
    project_root = tmp_path / "D drive" / "项目 データ"
    wrong_environment_root = tmp_path / "wrong environment root"
    app_root.mkdir(parents=True)
    project_root.mkdir(parents=True)
    wrong_environment_root.mkdir(parents=True)
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(wrong_environment_root))
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(wrong_environment_root))
    monkeypatch.setattr(tts_bundle_manifest, "bundle_manifest_for_key", lambda _key: None)

    observed: dict[str, Path] = {}

    def fake_download(_url, archive, _headers, **_kwargs):
        observed["archive"] = Path(archive)
        Path(archive).write_bytes(b"test archive")

    def fake_extract(_archive, out_dir, **_kwargs):
        observed["output"] = Path(out_dir)
        bundle = Path(out_dir) / "bundle root"
        bundle.mkdir(parents=True)
        (bundle / "server.py").write_text("# test\n", encoding="utf-8")
        return None

    monkeypatch.setattr(tts_bundle_worker, "_download_archive", fake_download)
    monkeypatch.setattr(tts_bundle_worker, "_extract_archive", fake_extract)

    state = BridgeState(
        None,
        None,
        None,
        None,
        app_root_dir=str(app_root),
        project_root_dir=str(project_root),
    )
    state.tasks["tts-test"] = {"cancelRequested": False}

    result = _download_tts_bundle(state, "tts-test", {"kind": "genie"})

    expected_base = project_root / "data" / "tts_bundles"
    assert observed["archive"].is_relative_to(expected_base / "downloads")
    assert observed["output"] == expected_base / "installed" / "genie_tts_server"
    assert Path(result["path"]).is_relative_to(expected_base)
    assert not (app_root / "data" / "tts_bundles").exists()
    assert not (wrong_environment_root / "data" / "tts_bundles").exists()


def test_legacy_tts_project_root_helper_prefers_runtime_environment(tmp_path, monkeypatch):
    from ui.settings_ui.tts.tts_env_probe import get_default_project_root

    shinsekai_root = tmp_path / "SHINSEKAI root 空格"
    easyai_root = tmp_path / "EASYAI root"
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(shinsekai_root))
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(easyai_root))

    assert get_default_project_root() == shinsekai_root.resolve()
