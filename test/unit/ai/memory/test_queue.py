from __future__ import annotations

import json

import pytest

import ai.memory.queue as memory_queue_module
from ai.memory.queue import MemoryWriteQueue, QueuePersistenceError


def test_memory_write_queue_persists_dedupes_and_flushes(tmp_path):
    saved = []

    def remember(content, character_name=None):
        saved.append((character_name, content))
        return {"ok": True}

    path = tmp_path / "queue.json"
    queue = MemoryWriteQueue(path=path, remember_func=remember)

    first = queue.enqueue("用户喜欢咖啡", character_name="Alice", source="test", confidence="bad")
    duplicate = queue.enqueue("用户喜欢咖啡", character_name="Alice")

    assert first["queued"] is True
    assert duplicate["duplicate"] is True
    assert len(queue) == 1
    assert json.loads(path.read_text(encoding="utf-8"))["items"][0]["confidence"] == 1.0

    reloaded = MemoryWriteQueue(path=path, remember_func=remember)
    assert len(reloaded) == 1

    result = reloaded.flush()

    assert result["saved"] == 1
    assert result["pending"] == 0
    assert saved == [("Alice", "用户喜欢咖啡")]


def test_memory_write_queue_keeps_failed_items(tmp_path):
    def remember(_content, character_name=None):
        return {"status": "loading", "message": "loading"}

    queue = MemoryWriteQueue(path=tmp_path / "queue.json", remember_func=remember)
    queue.enqueue("待写入记忆", character_name="Alice")

    result = queue.flush()

    assert result["saved"] == 0
    assert result["pending"] == 1
    assert result["errors"]


def test_memory_write_queue_only_removes_explicitly_successful_items(tmp_path):
    outcomes = [
        {"ok": True},
        {"status": "missing_dependency", "message": "mem0 is not installed"},
        {"kind": "missing_dependency", "message": "mem0 is not installed"},
        {"status": "error", "message": "runtime failed"},
        {"ok": False},
        None,
    ]

    def remember(_content, character_name=None):
        return outcomes.pop(0)

    queue = MemoryWriteQueue(path=tmp_path / "queue.json", remember_func=remember)
    for index in range(6):
        queue.enqueue(f"memory {index}", character_name="Alice")

    result = queue.flush()

    assert result["saved"] == 1
    assert result["pending"] == 5
    assert len(result["errors"]) == 5
    assert len(queue) == 5
    assert [item["memory"] for item in queue.pending()] == [f"memory {index}" for index in range(1, 6)]


def test_memory_write_queue_reports_persistence_failure_and_keeps_items(tmp_path, monkeypatch):
    saved = []

    def remember(content, character_name=None):
        saved.append((character_name, content))
        return {"ok": True}

    queue = MemoryWriteQueue(path=tmp_path / "queue.json", remember_func=remember)
    queue.enqueue("persist me", character_name="Alice")

    def fail_write(_path, _data):
        raise OSError("disk full")

    monkeypatch.setattr(memory_queue_module, "atomic_write_text", fail_write)

    with pytest.raises(QueuePersistenceError):
        queue.flush()

    assert saved == [("Alice", "persist me")]
    assert len(queue) == 1
    assert queue.pending()[0]["memory"] == "persist me"


def test_default_memory_queue_path_uses_project_root_after_cwd_changes(tmp_path, monkeypatch):
    project = tmp_path / "project"
    unrelated = tmp_path / "unrelated"
    project.mkdir()
    unrelated.mkdir()
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    monkeypatch.chdir(unrelated)
    queue = MemoryWriteQueue(remember_func=lambda *_args: {"ok": True})

    queue.enqueue("persist in selected project")

    assert queue.path == project / "data/memory/pending_queue.json"
    assert queue.path.is_file()
    assert not (unrelated / "data").exists()


def test_default_memory_queue_rejects_intermediate_symlink_escape(tmp_path, monkeypatch):
    project = tmp_path / "project"
    external = tmp_path / "external"
    (project / "data").mkdir(parents=True)
    external.mkdir()
    try:
        (project / "data" / "memory").symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())

    with pytest.raises(PermissionError, match="escapes project root"):
        MemoryWriteQueue()

    assert list(external.iterdir()) == []


def test_external_memory_queue_rejects_linked_parent(tmp_path, monkeypatch):
    project = tmp_path / "project"
    external = tmp_path / "external"
    alias = tmp_path / "alias"
    project.mkdir()
    external.mkdir()
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())

    with pytest.raises(PermissionError, match="symbolic link"):
        MemoryWriteQueue(path=alias / "pending.json")

    assert list(external.iterdir()) == []
