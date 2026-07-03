from __future__ import annotations

import sys
import types

from core.model_assets import downloads


def test_preload_huggingface_snapshot_reports_download_progress(monkeypatch):
    updates: list[dict] = []

    class FakeTqdm:
        def __init__(self, *args, total=None, initial=0, **kwargs):
            self.total = total
            self.n = initial

        def update(self, n=1):
            self.n += n
            return True

    def fake_snapshot_download(repo_id, *, tqdm_class, **kwargs):
        assert repo_id == "owner/model"
        assert kwargs == {"allow_patterns": ["*.json"]}
        bar = tqdm_class(total=4)
        for _ in range(4):
            bar.update(1)
        return "cached-model"

    fake_hub = types.SimpleNamespace(snapshot_download=fake_snapshot_download)
    fake_utils = types.SimpleNamespace(tqdm=FakeTqdm)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)
    monkeypatch.setitem(sys.modules, "huggingface_hub.utils", fake_utils)

    result = downloads.preload_huggingface_snapshot(
        "owner/model",
        cached=False,
        update_task=lambda **changes: updates.append(changes),
        download_message="Downloading test model",
        cached_message="Loading cached test model.",
        load_message="Loading test model.",
        allow_patterns=["*.json"],
    )

    assert result == "cached-model"
    progress_values = [update["progress"] for update in updates if "progress" in update]
    assert progress_values[0] == downloads.HUGGINGFACE_DOWNLOAD_PROGRESS_START
    assert downloads.HUGGINGFACE_DOWNLOAD_PROGRESS_END in progress_values
    assert progress_values[-1] == downloads.HUGGINGFACE_LOAD_PROGRESS
    assert updates[-1]["phase"] == "reload"
    assert updates[-1]["message"] == "Loading test model."


def test_preload_huggingface_snapshot_reports_cached_model_without_download():
    updates: list[dict] = []

    result = downloads.preload_huggingface_snapshot(
        "owner/model",
        cached=True,
        update_task=lambda **changes: updates.append(changes),
        download_message="Downloading test model",
        cached_message="Loading cached test model.",
        load_message="Loading test model.",
    )

    assert result is None
    assert updates == [
        {
            "phase": "reload",
            "message": "Loading cached test model.",
            "progress": downloads.HUGGINGFACE_LOAD_PROGRESS,
        }
    ]
