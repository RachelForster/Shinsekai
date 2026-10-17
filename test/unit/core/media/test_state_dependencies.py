import json
from types import SimpleNamespace

import pytest

from core.media.avatar import state_dependencies as indexes


@pytest.fixture
def assets(tmp_path):
    model = tmp_path / "model.demo"
    model.write_bytes(b"model")
    saved = tmp_path / "states" / "saved.json"
    saved.parent.mkdir()
    saved.write_text('{"pose": [1, 2, 3]}')
    dependency = tmp_path / "pose.demo"
    dependency.write_bytes(b"validated dependency")
    adapter = SimpleNamespace(format_id="demo", state_files=lambda model, value: (dependency, dependency))
    indexes.write_state_index(adapter, model, saved, {"pose": [1, 2, 3]})
    return model, saved, dependency, adapter


def test_index_is_format_agnostic_deduplicated_and_never_reads_dependencies(assets, monkeypatch):
    model, saved, dependency, adapter = assets
    original = type(dependency).open

    def no_dependency_read(path, *args, **kwargs):
        if path in (model, dependency):
            pytest.fail("Index authorization read a model/dependency's contents")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(type(dependency), "open", no_dependency_read)
    assert indexes.indexed_state_files(model, saved, adapter.format_id) == (dependency,)


@pytest.mark.parametrize("field,value", [
    ("version", 2), ("format", "other"), ("model", "other.demo"),
    ("model_stamp", [0, 0]), ("state_sha256", "bad"),
    ("files", None), ("files", [{}]), ("files", [0] * 513),
])
def test_rejects_invalid_record_headers_or_entries(assets, field, value):
    model, saved, _, adapter = assets
    path = indexes.index_path(saved)
    record = json.loads(path.read_text())
    record[field] = value
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        indexes.indexed_state_files(model, saved, adapter.format_id)


@pytest.mark.parametrize("relative", [
    "../pose.demo", "/pose.demo", "C:/pose.demo", "a\\pose.demo",
    "./pose.demo", "a//pose.demo", "a/../pose.demo", "pose.demo?x",
    "pose.demo#x", "%2e%2e/pose.demo", "",
])
def test_rejects_dependency_path_traversal_and_url_ambiguity(assets, relative):
    model, saved, _, adapter = assets
    path = indexes.index_path(saved)
    record = json.loads(path.read_text())
    record["files"][0]["path"] = relative
    path.write_text(json.dumps(record))
    with pytest.raises((ValueError, PermissionError)):
        indexes.indexed_state_files(model, saved, adapter.format_id)


@pytest.mark.parametrize("resource", ["index", "state", "model", "dependency"])
def test_non_regular_resources_are_rejected(assets, resource):
    model, saved, dependency, adapter = assets
    target = {"index": indexes.index_path(saved), "state": saved,
              "model": model, "dependency": dependency}[resource]
    target.unlink()
    target.mkdir()
    with pytest.raises(ValueError, match="regular"):
        indexes.indexed_state_files(model, saved, adapter.format_id)


@pytest.mark.parametrize("resource,limit", [
    ("index", indexes.MAX_INDEX_BYTES), ("state", indexes.MAX_STATE_BYTES),
])
def test_record_reads_are_bounded(assets, resource, limit):
    model, saved, _, adapter = assets
    target = indexes.index_path(saved) if resource == "index" else saved
    target.write_bytes(b" " * (limit + 1))
    with pytest.raises(ValueError, match="too large"):
        indexes.indexed_state_files(model, saved, adapter.format_id)


def test_index_writer_refuses_uncontrolled_or_excessive_dependencies(assets, tmp_path):
    model, saved, _, adapter = assets
    outside = tmp_path.parent / "outside.demo"
    adapter.state_files = lambda model, value: (outside,)
    with pytest.raises(PermissionError):
        indexes.write_state_index(adapter, model, saved, {})
    paths = [tmp_path / f"pose-{index}.demo" for index in range(513)]
    for path in paths:
        path.touch()
    adapter.state_files = lambda model, value: paths
    with pytest.raises(ValueError, match="Too many"):
        indexes.write_state_index(adapter, model, saved, {})
