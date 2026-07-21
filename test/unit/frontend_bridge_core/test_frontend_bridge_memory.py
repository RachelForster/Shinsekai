def test_check_mem0_before_call_returns_none_when_mem0_importable(monkeypatch):
    import importlib

    from frontend_bridge_core.memory import _check_mem0_before_call

    def _fake_find_spec(name):
        if name == "mem0":
            return object()
        return importlib.util.find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec)
    result = _check_mem0_before_call()
    assert result is None, f"expected None when mem0 is importable, got {result}"


def test_check_mem0_before_call_returns_dep_error_when_missing(monkeypatch):
    import importlib

    from frontend_bridge_core.memory import _check_mem0_before_call

    def _fake_find_spec(name):
        if name == "mem0":
            return None
        return importlib.util.find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec)

    result = _check_mem0_before_call()
    assert isinstance(result, dict), f"expected dict, got {type(result)}"
    assert result.get("kind") == "missing_dependency"
    assert result.get("moduleName") == "mem0"
    assert result.get("packageName") == "mem0ai[extras]"


def test_get_mem0_status_returns_valid_status():
    from frontend_bridge_core.memory import _get_mem0_status

    result = _get_mem0_status()
    assert isinstance(result, dict)
    assert "status" in result
    valid = {"ready", "loading", "not_started", "error", "missing_dependency"}
    assert result["status"] in valid, f"unexpected status: {result['status']}"


def test_get_mem0_status_can_peek_without_starting_loading(monkeypatch):
    import importlib

    from frontend_bridge_core.memory import _get_mem0_status

    def _fake_find_spec(name):
        if name == "mem0":
            return object()
        return importlib.util.find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec)
    captured = {}

    def _fake_check_mem0_status(*, start_loading=True):
        captured["start_loading"] = start_loading
        return {"status": "not_started", "modelCached": False}

    monkeypatch.setattr("ai.memory.runtime.check_mem0_status", _fake_check_mem0_status)

    result = _get_mem0_status(start_loading=False)

    assert result["status"] == "not_started"
    assert result["modelCached"] is False
    assert captured["start_loading"] is False


def test_get_mem0_status_missing_dependency_when_not_importable(monkeypatch):
    import importlib

    from frontend_bridge_core.memory import _get_mem0_status

    def _fake_find_spec(name):
        if name == "mem0":
            return None
        return importlib.util.find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec)

    result = _get_mem0_status()
    assert result["status"] == "missing_dependency"
    assert result["moduleName"] == "mem0"
    assert result["packageName"] == "mem0ai[extras]"


def test_check_mem0_status_includes_task_when_import_fails(monkeypatch):
    import builtins

    from ai.memory import runtime

    original_import = builtins.__import__
    task = {"id": "mem0-embedding-model", "status": "running"}

    def _fake_import(name, *args, **kwargs):
        if name == "mem0":
            raise ImportError("No module named 'mem0'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(runtime, "_mem0", None)
    monkeypatch.setattr(runtime, "_mem0_loading", False)
    monkeypatch.setattr(runtime, "_mem0_load_error", None)
    monkeypatch.setattr(runtime, "current_mem0_task", lambda: task)
    monkeypatch.setattr(builtins, "__import__", _fake_import)

    result = runtime.check_mem0_status()

    assert result == {
        "status": "missing_dependency",
        "moduleName": "mem0",
        "packageName": "mem0ai",
        "task": task,
    }


def test_check_mem0_status_exposes_cache_state_while_loading(monkeypatch):
    from ai.memory import runtime

    task = {"id": "mem0-embedding-model", "status": "running"}
    monkeypatch.setattr(runtime, "_mem0", None)
    monkeypatch.setattr(runtime, "_mem0_loading", True)
    monkeypatch.setattr(runtime, "_mem0_load_error", None)
    monkeypatch.setattr(runtime, "current_mem0_task", lambda: task)

    for cached in (False, True):
        monkeypatch.setattr(runtime, "is_embedding_model_cached", lambda cached=cached: cached)

        assert runtime.check_mem0_status() == {
            "status": "loading",
            "modelCached": cached,
            "task": task,
        }


def test_preload_embedding_model_limits_huggingface_snapshot(monkeypatch):
    from ai.memory import runtime

    captured = {}
    snapshot_path = r"\\?\C:\very\deep\cache\snapshots\abc123"

    def _fake_preload_huggingface_snapshot(repo_id, **kwargs):
        captured["repo_id"] = repo_id
        captured.update(kwargs)
        return snapshot_path

    monkeypatch.setattr(runtime, "preload_huggingface_snapshot", _fake_preload_huggingface_snapshot)
    monkeypatch.setattr(runtime, "embedding_model_snapshot_path", lambda: snapshot_path)

    result = runtime._preload_embedding_model(cached=False)

    assert result == snapshot_path
    assert captured["repo_id"] == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    assert captured["cached"] is False
    patterns = captured["allow_patterns"]
    assert "model.safetensors" in patterns
    assert "tokenizer.json" in patterns
    assert not any(pattern.startswith("onnx/") for pattern in patterns)
    assert not any(pattern.startswith("openvino/") for pattern in patterns)
    assert "tf_model.h5" not in patterns
    assert "pytorch_model.bin" not in patterns


def test_preload_embedding_model_rejects_incomplete_download(monkeypatch):
    import pytest

    from ai.memory import runtime

    monkeypatch.setattr(
        runtime,
        "preload_huggingface_snapshot",
        lambda *args, **kwargs: r"C:\partial-cache\snapshots\abc123",
    )
    monkeypatch.setattr(runtime, "embedding_model_snapshot_path", lambda: None)

    with pytest.raises(RuntimeError, match="snapshot is incomplete"):
        runtime._preload_embedding_model(cached=False)


def test_create_mem0_instance_uses_local_snapshot_instead_of_repo_id(monkeypatch):
    from ai.memory import runtime

    snapshot_path = r"\\?\C:\very\deep\cache\snapshots\abc123"
    config = {
        "embedder": {
            "provider": "huggingface",
            "config": {"model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"},
        },
        "llm": {"provider": "openai", "config": {}},
    }
    captured = {}

    class _FakeMemory:
        @classmethod
        def from_config(cls, value):
            captured["config"] = value
            return "memory-instance"

    monkeypatch.setattr(runtime, "build_mem0_config", lambda: config)
    monkeypatch.setattr(runtime, "_preload_embedding_model", lambda *, cached: snapshot_path)

    result = runtime._create_mem0_instance(_FakeMemory, cached=True)

    assert result == "memory-instance"
    assert captured["config"]["embedder"]["config"]["model"] == snapshot_path
