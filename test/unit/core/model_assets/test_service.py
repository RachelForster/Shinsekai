from __future__ import annotations

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
    snapshot.mkdir(parents=True)
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


def test_download_model_asset_uses_shared_progress_downloader_and_token(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "empty-cache"))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "unused-home"))
    snapshot = tmp_path / "downloaded"
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
    assert updates[-1]["progress"] == 0.5


def test_download_model_asset_rejects_missing_local_directory(tmp_path):
    spec = _spec(source="local", repo_id="", local_path=tmp_path / "missing", required_file_groups=())

    with pytest.raises(ValueError, match="Local model directory does not exist"):
        service.download_model_asset(spec, update_task=lambda **_changes: None)
