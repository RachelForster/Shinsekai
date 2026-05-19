from __future__ import annotations

import pytest
import yaml

from core.plugins.plugin_host import append_plugin_manifest_entry_if_missing
from ui.settings_ui.tabs.plugin_tab import (
    _AppSelfUpdateTask,
    _DownloadRepoTask,
    _manifest_entry_matches_dest_name,
    _parse_download_dest_name,
)


pytestmark = pytest.mark.unit


def test_manifest_entry_must_match_downloaded_folder_name() -> None:
    assert _manifest_entry_matches_dest_name("plugins.safe.plugin:SafePlugin", "safe")
    assert not _manifest_entry_matches_dest_name(
        "plugins.other.plugin:OtherPlugin",
        "safe",
    )


def test_download_dest_name_is_parsed_from_worker_payload() -> None:
    assert _parse_download_dest_name('{"dest": "/tmp/plugins/safe"}') == "safe"
    assert _parse_download_dest_name("{}") == ""
    assert _parse_download_dest_name("not json") == ""


def test_append_plugin_manifest_can_write_discovered_entries_disabled(tmp_path) -> None:
    manifest = tmp_path / "plugins.yaml"

    outcome = append_plugin_manifest_entry_if_missing(
        "plugins.safe.plugin:SafePlugin",
        enabled=False,
        path=manifest,
    )

    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert outcome == "added"
    assert data[0] == {
        "entry": "plugins.safe.plugin:SafePlugin",
        "enabled": False,
    }


class _SignalRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def emit(self, *args) -> None:
        self.calls.append(args)


class _DownloadSignalsRecorder:
    def __init__(self) -> None:
        self.finished = _SignalRecorder()
        self.download_progress = _SignalRecorder()
        self.status_message = _SignalRecorder()
        self.pip_log_line = _SignalRecorder()
        self.pip_phase_started = _SignalRecorder()


def test_download_task_does_not_auto_pip_requirements(tmp_path, monkeypatch) -> None:
    plugin_dir = tmp_path / "plugins" / "safe"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "requirements.txt").write_text("dangerous-build==1\n", encoding="utf-8")

    monkeypatch.setattr(
        "ui.settings_ui.tabs.plugin_tab.install_github_plugin_under_plugins",
        lambda *args, **kwargs: plugin_dir,
    )
    sig = _DownloadSignalsRecorder()
    task = _DownloadRepoTask(
        "owner/repo",
        "safe",
        sig,  # type: ignore[arg-type]
        ref_kind="latest",
        tag_name="",
        overwrite=False,
    )

    task.run()

    assert sig.pip_phase_started.calls == []
    assert sig.pip_log_line.calls == []
    repo_norm, ok, _download_err, payload = sig.finished.calls[-1]
    assert repo_norm == "owner/repo"
    assert ok is True
    assert '"pip": "pip_skip_manual_required"' in payload


def test_app_update_task_does_not_auto_pip(monkeypatch) -> None:
    monkeypatch.setattr(
        "ui.settings_ui.tabs.plugin_tab.overwrite_merge_app_tree",
        lambda *args, **kwargs: None,
    )
    sig = _DownloadSignalsRecorder()
    task = _AppSelfUpdateTask(
        "owner/repo",
        "latest",
        "",
        sig,  # type: ignore[arg-type]
    )

    task.run()

    assert sig.pip_phase_started.calls == []
    assert sig.pip_log_line.calls == []
    _repo_norm, ok, _download_err, payload = sig.finished.calls[-1]
    assert ok is True
    assert '"pip": "app_update_skip_pip"' in payload
