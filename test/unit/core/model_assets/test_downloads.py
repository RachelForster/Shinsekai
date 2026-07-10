from __future__ import annotations

import sys
import threading
import time
import types

from core.model_assets import downloads


class _PartialInitTqdm:
    """Model tqdm's disabled/non-TTY lifecycle without terminal rendering."""

    def __init__(
        self,
        iterable=None,
        *args,
        total=None,
        initial=0,
        disable=False,
        **kwargs,
    ):
        self.iterable = iterable
        self.total = total
        self.n = initial
        self.disable = bool(disable)
        self.unit = kwargs.get("unit")
        self.name = kwargs.get("name")
        # Real tqdm skips most of its terminal state when it starts disabled.
        # Enabling that same instance after construction makes refresh/update
        # access attributes that were never initialized.
        self._fully_initialized = not self.disable

    def _raise_if_reenabled_after_partial_init(self):
        if not self.disable and not self._fully_initialized:
            raise AttributeError("nrows")

    def __iter__(self):
        self._raise_if_reenabled_after_partial_init()
        for item in self.iterable or ():
            if not self.disable:
                self.n += 1
            yield item

    def update(self, n=1):
        self._raise_if_reenabled_after_partial_init()
        if self.disable:
            return None
        self.n += n
        return True

    def refresh(self, *args, **kwargs):
        self._raise_if_reenabled_after_partial_init()
        return not self.disable

    def close(self):
        self._raise_if_reenabled_after_partial_init()


def _install_fake_huggingface(monkeypatch, snapshot_download, tqdm_class=_PartialInitTqdm):
    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(snapshot_download=snapshot_download))
    monkeypatch.setitem(sys.modules, "huggingface_hub.utils", types.SimpleNamespace(tqdm=tqdm_class))


def _preload_with_updates(updates, **snapshot_kwargs):
    return downloads.preload_huggingface_snapshot(
        "owner/model",
        cached=False,
        update_task=lambda **changes: updates.append(changes),
        download_message="Downloading test model",
        cached_message="Loading cached test model.",
        load_message="Loading test model.",
        **snapshot_kwargs,
    )


def test_preload_huggingface_snapshot_reports_download_progress(monkeypatch):
    updates: list[dict] = []

    class FakeTqdm:
        def __init__(self, *args, total=None, initial=0, **kwargs):
            self.total = total
            self.n = initial
            self.unit = kwargs.get("unit")
            self.name = kwargs.get("name")

        def update(self, n=1):
            self.n += n
            return True

        def refresh(self, *args, **kwargs):
            return True

    def fake_snapshot_download(repo_id, *, tqdm_class, **kwargs):
        assert repo_id == "owner/model"
        assert kwargs == {"allow_patterns": ["*.json"]}
        bar = tqdm_class(total=0, initial=0, unit="B", unit_scale=True, name="huggingface_hub.snapshot_download")
        bar.total += 4096
        bar.refresh()
        for _ in range(4):
            bar.update(1024)
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
    assert any(update.get("logs") for update in updates)
    assert any("4.0 KB / 4.0 KB" in "\n".join(update.get("logs", [])) for update in updates)
    assert not any("files" in "\n".join(update.get("logs", [])) for update in updates)
    assert updates[-1]["phase"] == "reload"
    assert updates[-1]["message"] == "Loading test model."


def test_preload_huggingface_snapshot_tracks_disabled_partial_init_byte_progress(monkeypatch):
    updates: list[dict] = []

    def fake_snapshot_download(repo_id, *, tqdm_class, **kwargs):
        assert repo_id == "owner/model"
        bar = tqdm_class(
            desc="Downloading (incomplete total...)",
            disable=True,
            total=0,
            initial=0,
            unit="B",
            unit_scale=True,
            name="huggingface_hub.snapshot_download",
        )
        bar.total += 4096
        bar.refresh()
        for _ in range(4):
            bar.update(1024)
        return "cached-model"

    _install_fake_huggingface(monkeypatch, fake_snapshot_download)

    result = _preload_with_updates(updates)

    assert result == "cached-model"
    download_progress = [
        update["progress"]
        for update in updates
        if update.get("phase") == "download" and "progress" in update
    ]
    assert download_progress[0] == downloads.HUGGINGFACE_DOWNLOAD_PROGRESS_START
    assert any(
        downloads.HUGGINGFACE_DOWNLOAD_PROGRESS_START < progress < downloads.HUGGINGFACE_DOWNLOAD_PROGRESS_END
        for progress in download_progress
    )
    assert download_progress[-1] == downloads.HUGGINGFACE_DOWNLOAD_PROGRESS_END
    assert any("4.0 KB / 4.0 KB" in update.get("message", "") for update in updates)


def test_preload_huggingface_snapshot_falls_back_to_legacy_fetching_file_progress(monkeypatch):
    updates: list[dict] = []
    monkeypatch.setattr(downloads.sys, "stderr", None)

    def fake_snapshot_download(repo_id, *, tqdm_class, **kwargs):
        assert repo_id == "owner/model"
        fetched = list(tqdm_class(range(4), desc="Fetching 4 files", total=4))
        assert fetched == [0, 1, 2, 3]
        return "cached-model"

    _install_fake_huggingface(monkeypatch, fake_snapshot_download)

    result = _preload_with_updates(updates)

    assert result == "cached-model"
    download_progress = [
        update["progress"]
        for update in updates
        if update.get("phase") == "download" and "progress" in update
    ]
    assert download_progress[0] == downloads.HUGGINGFACE_DOWNLOAD_PROGRESS_START
    assert any(
        downloads.HUGGINGFACE_DOWNLOAD_PROGRESS_START < progress < downloads.HUGGINGFACE_DOWNLOAD_PROGRESS_END
        for progress in download_progress
    )
    assert download_progress[-1] == downloads.HUGGINGFACE_DOWNLOAD_PROGRESS_END
    assert any("4 / 4 files" in update.get("message", "") for update in updates)


def test_preload_huggingface_snapshot_caches_progress_source_after_init(monkeypatch):
    updates: list[dict] = []

    class DescriptionProbe:
        def __init__(self):
            self.calls = 0

        def __str__(self):
            self.calls += 1
            return "Fetching 2 files"

    def fake_snapshot_download(repo_id, *, tqdm_class, **kwargs):
        assert repo_id == "owner/model"
        description = DescriptionProbe()
        bar = tqdm_class(range(2), desc=description, total=2, disable=True)
        calls_after_init = description.calls

        bar.refresh()
        assert list(bar) == [0, 1]
        assert description.calls == calls_after_init
        return "cached-model"

    _install_fake_huggingface(monkeypatch, fake_snapshot_download)

    assert _preload_with_updates(updates) == "cached-model"
    assert any("2 / 2 files" in update.get("message", "") for update in updates)


def test_preload_huggingface_snapshot_detects_positional_progress_metadata(monkeypatch):
    updates: list[dict] = []

    class PositionalTqdm(_PartialInitTqdm):
        def __init__(self, iterable=None, desc=None, total=None, *args, **kwargs):
            super().__init__(iterable, *args, total=total, **kwargs)
            self.desc = desc

    def fake_snapshot_download(repo_id, *, tqdm_class, **kwargs):
        assert repo_id == "owner/model"
        assert list(tqdm_class(range(2), "Fetching 2 files", 2)) == [0, 1]
        return "cached-model"

    _install_fake_huggingface(monkeypatch, fake_snapshot_download, PositionalTqdm)

    assert _preload_with_updates(updates) == "cached-model"
    assert any("2 / 2 files" in update.get("message", "") for update in updates)


def test_preload_huggingface_snapshot_prefers_byte_progress_over_file_progress(monkeypatch):
    updates: list[dict] = []

    def fake_snapshot_download(repo_id, *, tqdm_class, **kwargs):
        assert repo_id == "owner/model"
        byte_bar = tqdm_class(
            desc="Downloading (incomplete total...)",
            disable=True,
            total=0,
            initial=0,
            unit="B",
            unit_scale=True,
            name="huggingface_hub.snapshot_download",
        )
        byte_bar.total += 4096
        byte_bar.refresh()

        fetched = list(tqdm_class(range(4), desc="Fetching 4 files", total=4, disable=True))
        assert fetched == [0, 1, 2, 3]

        for _ in range(4):
            byte_bar.update(1024)
        return "cached-model"

    _install_fake_huggingface(monkeypatch, fake_snapshot_download)

    result = _preload_with_updates(updates)

    assert result == "cached-model"
    download_messages = [
        update.get("message", "") for update in updates if update.get("phase") == "download"
    ]
    assert any("4.0 KB / 4.0 KB" in message for message in download_messages)
    assert not any("files" in message for message in download_messages)


def test_preload_huggingface_snapshot_serializes_concurrent_disabled_byte_updates(monkeypatch):
    updates: list[dict] = []

    class SlowDisabledTqdm(_PartialInitTqdm):
        def update(self, n=1):
            if self.disable:
                # Let both workers overlap inside the base no-op. Without the
                # wrapper's counter lock they both observe the same previous n.
                time.sleep(0.02)
                return None
            return super().update(n)

    def fake_snapshot_download(repo_id, *, tqdm_class, **kwargs):
        assert repo_id == "owner/model"
        bar = tqdm_class(
            disable=True,
            total=2,
            initial=0,
            unit="B",
            name="huggingface_hub.snapshot_download",
        )
        start = threading.Barrier(3)

        def advance():
            start.wait()
            bar.update(1)

        workers = [threading.Thread(target=advance) for _ in range(2)]
        for worker in workers:
            worker.start()
        start.wait()
        for worker in workers:
            worker.join()
        assert bar.n == 2
        return "cached-model"

    _install_fake_huggingface(monkeypatch, fake_snapshot_download, SlowDisabledTqdm)

    result = _preload_with_updates(updates)

    assert result == "cached-model"
    download_progress = [
        update["progress"]
        for update in updates
        if update.get("phase") == "download" and "progress" in update
    ]
    assert download_progress[-1] == downloads.HUGGINGFACE_DOWNLOAD_PROGRESS_END


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
