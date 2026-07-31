from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from core.model_assets import service


def _spec(**changes) -> service.ModelAssetSpec:
    values = {
        "asset_id": "test.model",
        "title": "Test model",
        "variant": "small",
        "repo_id": "owner/model",
        "allow_patterns": ("config.json", "model.bin", "tokenizer.json"),
        "required_file_groups": (("config.json",), ("model.bin",), ("tokenizer.json",)),
    }
    values.update(changes)
    return service.ModelAssetSpec(**values)


def _write_complete_snapshot(snapshot: Path) -> None:
    snapshot.mkdir(parents=True, exist_ok=True)
    for name in ("config.json", "model.bin", "tokenizer.json"):
        (snapshot / name).write_text(name, encoding="utf-8")


def test_inspect_model_asset_only_accepts_complete_huggingface_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "unused-home"))
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)
    model_dir = tmp_path / "models--owner--model"
    snapshots = model_dir / "snapshots"
    incomplete = snapshots / "incomplete"
    incomplete.mkdir(parents=True)
    (incomplete / "config.json").write_text("{}", encoding="utf-8")
    refs = model_dir / "refs"
    refs.mkdir()
    (refs / "main").write_text("incomplete", encoding="utf-8")

    missing = service.inspect_model_asset(_spec())

    assert missing["cached"] is False
    assert missing["downloadable"] is True

    complete = snapshots / "complete"
    _write_complete_snapshot(complete)

    still_missing = service.inspect_model_asset(_spec())
    assert still_missing["cached"] is False

    (refs / "main").write_text("complete", encoding="utf-8")

    cached = service.inspect_model_asset(_spec())

    assert cached["cached"] is True
    assert Path(str(cached["path"])) == complete.resolve()

    (complete / "model.bin").write_bytes(b"")
    assert service.inspect_model_asset(_spec())["cached"] is False


def test_explicit_hub_cache_does_not_reuse_a_stale_snapshot_from_hf_home(tmp_path, monkeypatch):
    active_hub = tmp_path / "active-hub"
    old_home = tmp_path / "old-home"
    old_model = old_home / "hub" / "models--owner--model"
    old_snapshot = old_model / "snapshots" / "old-revision"
    _write_complete_snapshot(old_snapshot)
    (old_model / "refs").mkdir()
    (old_model / "refs" / "main").write_text("old-revision", encoding="utf-8")
    monkeypatch.setenv("HF_HUB_CACHE", str(active_hub))
    monkeypatch.setenv("HF_HOME", str(old_home))
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)

    status = service.inspect_model_asset(_spec())

    assert status["cached"] is False
    assert "path" not in status


def test_main_ref_cannot_select_snapshot_outside_cache_root(tmp_path, monkeypatch):
    cache_root = tmp_path / "hub"
    model_dir = cache_root / "models--owner--model"
    (model_dir / "refs").mkdir(parents=True)
    (model_dir / "refs" / "main").write_text("../../outside-snapshot", encoding="utf-8")
    outside_snapshot = tmp_path / "outside-snapshot"
    _write_complete_snapshot(outside_snapshot)
    monkeypatch.setenv("HF_HUB_CACHE", str(cache_root))

    assert service.find_cached_huggingface_snapshot(_spec()) is None


def test_inspect_local_model_reports_existing_and_missing_directories(tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "asset.bin").write_bytes(b"model")

    present = service.inspect_model_asset(
        _spec(source="local", repo_id="", local_path=existing, required_file_groups=())
    )
    missing = service.inspect_model_asset(
        _spec(source="local", repo_id="", local_path=tmp_path / "missing", required_file_groups=())
    )

    assert present["source"] == "local"
    assert present["cached"] is True
    assert present["downloadable"] is False
    assert missing["cached"] is False
    assert missing["downloadable"] is False


def test_snapshot_readiness_allows_only_bounded_huggingface_file_links(tmp_path):
    cache_root = tmp_path / "hub"
    snapshot = cache_root / "models--owner--model" / "snapshots" / "revision"
    blobs = cache_root / "blobs"
    snapshot.mkdir(parents=True)
    blobs.mkdir(parents=True)
    for name in ("config.json", "model.bin", "tokenizer.json"):
        target = blobs / name
        target.write_text(name, encoding="utf-8")
        try:
            (snapshot / name).symlink_to(target)
        except (OSError, NotImplementedError):
            pytest.skip("symbolic links are unavailable")

    assert service._snapshot_is_complete(
        snapshot,
        _spec().required_file_groups,
        allowed_link_root=cache_root,
    )

    outside = tmp_path / "outside-model.bin"
    outside.write_bytes(b"outside")
    (snapshot / "model.bin").unlink()
    (snapshot / "model.bin").symlink_to(outside)

    assert not service._snapshot_is_complete(
        snapshot,
        _spec().required_file_groups,
        allowed_link_root=cache_root,
    )


def test_snapshot_readiness_rejects_replaced_directory(
    tmp_path,
    monkeypatch,
):
    snapshot = tmp_path / "snapshot"
    preserved = tmp_path / "snapshot-preserved"
    _write_complete_snapshot(snapshot)
    real_snapshot = service.snapshot_directory_entries_without_links
    replaced = False

    def replace_after_inventory(path, **kwargs):
        nonlocal replaced
        result = real_snapshot(path, **kwargs)
        if Path(path) == snapshot and not replaced:
            replaced = True
            snapshot.rename(preserved)
            _write_complete_snapshot(snapshot)
        return result

    monkeypatch.setattr(
        service,
        "snapshot_directory_entries_without_links",
        replace_after_inventory,
    )

    assert not service._snapshot_is_complete(
        snapshot,
        _spec().required_file_groups,
        allowed_link_root=tmp_path,
    )
    assert (snapshot / "model.bin").is_file()
    assert (preserved / "model.bin").is_file()


def test_snapshot_validator_can_reject_structurally_invalid_assets(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    model_dir = tmp_path / "models--owner--model"
    snapshot = model_dir / "snapshots" / "current"
    _write_complete_snapshot(snapshot)
    (model_dir / "refs").mkdir()
    (model_dir / "refs" / "main").write_text("current", encoding="utf-8")

    rejected = service.inspect_model_asset(
        _spec(snapshot_validator=lambda candidate: (candidate / "config.json").read_text() == "{}")
    )

    assert rejected["cached"] is False


def test_download_model_asset_uses_shared_progress_downloader_and_token(tmp_path, monkeypatch):
    cache_root = tmp_path / "active-cache"
    monkeypatch.setenv("HF_HUB_CACHE", str(cache_root))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "unused-home"))
    snapshot = cache_root / "models--owner--model" / "snapshots" / "downloaded"
    calls = []

    def fake_preload(repo_id, **kwargs):
        calls.append((repo_id, kwargs))
        _write_complete_snapshot(snapshot)
        kwargs["update_task"](phase="download", progress=0.5, message="halfway")
        return str(snapshot)

    monkeypatch.setattr(service, "preload_huggingface_snapshot", fake_preload)
    updates = []

    result = service.download_model_asset(
        _spec(),
        update_task=lambda **changes: updates.append(changes),
        token="hf-secret",
    )

    assert result["cached"] is True
    assert result["downloaded"] is True
    assert calls[0][0] == "owner/model"
    assert calls[0][1]["token"] == "hf-secret"
    assert calls[0][1]["post_download_phase"] == "verify"
    assert calls[0][1]["allow_patterns"] == ["config.json", "model.bin", "tokenizer.json"]
    assert calls[0][1]["cache_dir"] == str(cache_root)
    assert updates[-1]["progress"] == 0.5


def test_download_model_asset_rejects_downloader_snapshot_outside_active_cache(
    tmp_path,
    monkeypatch,
):
    cache_root = tmp_path / "active-cache"
    outside = tmp_path / "outside-snapshot"
    monkeypatch.setenv("HF_HUB_CACHE", str(cache_root))
    monkeypatch.setattr(
        service,
        "preload_huggingface_snapshot",
        lambda *_args, **_kwargs: (
            _write_complete_snapshot(outside) or outside.as_posix()
        ),
    )

    with pytest.raises(RuntimeError, match="outside the active cache root"):
        service.download_model_asset(
            _spec(),
            update_task=lambda **_changes: None,
        )


def test_download_model_asset_forces_refresh_of_incomplete_main_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    model_dir = tmp_path / "models--owner--model"
    snapshot = model_dir / "snapshots" / "current"
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (snapshot / "partial").mkdir()
    (snapshot / "partial" / "model.bin").write_bytes(b"partial")
    old_snapshot = model_dir / "snapshots" / "old"
    _write_complete_snapshot(old_snapshot)
    (model_dir / "refs").mkdir()
    (model_dir / "refs" / "main").write_text("current", encoding="utf-8")
    calls = []

    def fake_preload(repo_id, **kwargs):
        calls.append((repo_id, kwargs))
        assert not snapshot.exists()
        assert old_snapshot.is_dir()
        _write_complete_snapshot(snapshot)
        return str(snapshot)

    monkeypatch.setattr(service, "preload_huggingface_snapshot", fake_preload)

    result = service.download_model_asset(_spec(), update_task=lambda **_changes: None)

    assert result["cached"] is True
    assert result["downloaded"] is True
    assert calls[0][1]["force_download"] is True


def test_concurrent_downloads_for_same_asset_share_work(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    model_dir = tmp_path / "models--owner--model"
    snapshot = model_dir / "snapshots" / "current"
    refs = model_dir / "refs"
    first_download_started = threading.Event()
    release_first_download = threading.Event()
    duplicate_download_started = threading.Event()
    calls = []
    calls_lock = threading.Lock()

    def fake_preload(repo_id, **_kwargs):
        with calls_lock:
            calls.append(repo_id)
            if len(calls) > 1:
                duplicate_download_started.set()
        first_download_started.set()
        assert release_first_download.wait(timeout=2)
        _write_complete_snapshot(snapshot)
        refs.mkdir(parents=True, exist_ok=True)
        (refs / "main").write_text("current", encoding="utf-8")
        return str(snapshot)

    monkeypatch.setattr(service, "preload_huggingface_snapshot", fake_preload)
    results = []
    errors = []

    def download() -> None:
        try:
            results.append(
                service.download_model_asset(_spec(), update_task=lambda **_changes: None)
            )
        except BaseException as exc:  # pragma: no cover - reported by the assertion below
            errors.append(exc)

    first = threading.Thread(target=download)
    second = threading.Thread(target=download)
    first.start()
    assert first_download_started.wait(timeout=2)
    second.start()

    duplicate_started = duplicate_download_started.wait(timeout=0.2)
    release_first_download.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not duplicate_started
    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert calls == ["owner/model"]
    assert sorted(result["downloaded"] for result in results) == [False, True]


def test_invalid_snapshot_cleanup_failure_stops_before_download(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    model_dir = tmp_path / "models--owner--model"
    snapshot = model_dir / "snapshots" / "current"
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "refs").mkdir()
    (model_dir / "refs" / "main").write_text("current", encoding="utf-8")
    preload_calls = []
    monkeypatch.setattr(
        service,
        "preload_huggingface_snapshot",
        lambda *_args, **_kwargs: preload_calls.append(True),
    )

    def fail_remove(_path, **_kwargs):
        raise OSError("locked")

    monkeypatch.setattr(service, "remove_directory_without_links", fail_remove)

    with pytest.raises(OSError, match="locked"):
        service.download_model_asset(_spec(), update_task=lambda **_changes: None)

    assert preload_calls == []


@pytest.mark.skipif(os.name != "nt", reason="Windows verbatim paths are Windows-specific")
def test_invalid_snapshot_cleanup_supports_verbatim_long_paths(tmp_path, monkeypatch):
    normal_hub = tmp_path.joinpath(*(["deep-cache-segment-1234567890"] * 7))
    hub = Path("\\\\?\\" + str(normal_hub))
    monkeypatch.setenv("HF_HUB_CACHE", str(hub))
    model_dir = hub / "models--owner--model"
    snapshot = model_dir / "snapshots" / "current"
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "refs").mkdir()
    (model_dir / "refs" / "main").write_text("current", encoding="utf-8")

    assert len(str(snapshot)) > 260

    service._remove_invalid_main_snapshots(_spec())

    assert not snapshot.exists()


def test_download_model_asset_rejects_missing_local_directory(tmp_path):
    spec = _spec(source="local", repo_id="", local_path=tmp_path / "missing", required_file_groups=())

    with pytest.raises(ValueError, match="Local model directory does not exist"):
        service.download_model_asset(spec, update_task=lambda **_changes: None)


def test_relative_huggingface_cache_is_project_rooted_not_cwd(tmp_path, monkeypatch):
    project = tmp_path / "project"
    unrelated = tmp_path / "unrelated"
    project.mkdir()
    unrelated.mkdir()
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(project))
    monkeypatch.setenv("HF_HUB_CACHE", "data/cache/huggingface/hub")
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)
    monkeypatch.chdir(unrelated)

    assert service._huggingface_cache_roots() == (
        project / "data/cache/huggingface/hub",
    )


def test_relative_huggingface_cache_prefers_explicit_root_over_ambient_root(
    tmp_path,
    monkeypatch,
):
    ambient = tmp_path / "ambient"
    selected = tmp_path / "selected"
    unrelated = tmp_path / "unrelated"
    ambient.mkdir()
    selected.mkdir()
    unrelated.mkdir()
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(ambient))
    monkeypatch.setenv("HF_HUB_CACHE", "data/cache/huggingface/hub")
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)
    monkeypatch.chdir(unrelated)

    assert service._huggingface_cache_roots(root=selected) == (
        selected / "data/cache/huggingface/hub",
    )


def test_download_model_asset_uses_explicit_root_for_relative_cache(
    tmp_path,
    monkeypatch,
):
    ambient = tmp_path / "ambient"
    selected = tmp_path / "selected"
    ambient.mkdir()
    selected.mkdir()
    cache_root = selected / "data/cache/huggingface/hub"
    snapshot = cache_root / "models--owner--model" / "snapshots" / "downloaded"
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(ambient))
    monkeypatch.setenv("HF_HUB_CACHE", "data/cache/huggingface/hub")
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)
    calls = []

    def fake_preload(repo_id, **kwargs):
        calls.append((repo_id, kwargs))
        _write_complete_snapshot(snapshot)
        return str(snapshot)

    monkeypatch.setattr(service, "preload_huggingface_snapshot", fake_preload)

    result = service.download_model_asset(
        _spec(),
        update_task=lambda **_changes: None,
        root=selected,
    )

    assert result["path"] == str(snapshot.resolve())
    assert calls[0][1]["cache_dir"] == str(cache_root)


def test_empty_current_huggingface_cache_does_not_fall_back_to_legacy(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(project))
    monkeypatch.setenv("HF_HUB_CACHE", "")
    monkeypatch.setenv(
        "HUGGINGFACE_HUB_CACHE",
        str(tmp_path / "legacy-cache"),
    )

    with pytest.raises(ValueError, match="HF_HUB_CACHE"):
        service.active_huggingface_hub_cache_root()


def test_relative_huggingface_cache_rejects_symlinked_project_storage(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    external = tmp_path / "external"
    (project / "data").mkdir(parents=True)
    external.mkdir()
    try:
        (project / "data/cache").symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(project))
    monkeypatch.setenv("HF_HUB_CACHE", "data/cache/huggingface/hub")

    with pytest.raises(PermissionError, match="symbolic links"):
        service._huggingface_cache_roots()


def test_project_owned_hf_home_rejects_symlinked_hub_child(tmp_path, monkeypatch):
    project = tmp_path / "project"
    hf_home = project / "data/cache/huggingface"
    external = tmp_path / "external"
    hf_home.mkdir(parents=True)
    external.mkdir()
    try:
        (hf_home / "hub").symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(project))
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", "data/cache/huggingface")

    with pytest.raises(PermissionError, match="symbolic links"):
        service._huggingface_cache_roots()


def test_invalid_user_home_falls_back_to_project_model_cache(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    project.mkdir()
    invalid_home = Path(f"{tmp_path / 'home'} ")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.setattr(
        Path,
        "home",
        classmethod(lambda _cls: invalid_home),
    )

    assert service._huggingface_cache_roots() == (
        project / "data/cache/huggingface/hub",
    )
