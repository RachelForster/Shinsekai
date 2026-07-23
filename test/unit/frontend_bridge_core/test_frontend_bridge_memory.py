import pytest


class _ImmediateThread:
    def __init__(self, *, target, **kwargs):
        self._target = target

    def start(self):
        self._target()


@pytest.fixture(autouse=True)
def _compatible_memory_runtime(monkeypatch):
    monkeypatch.setattr(
        "frontend_bridge_core.runtime_dependencies.runtime_dependency_error_for_module",
        lambda _module_name: None,
    )


def test_mem0_telemetry_defaults_off_but_preserves_explicit_opt_in(monkeypatch):
    from ai.memory import runtime

    monkeypatch.delenv("MEM0_TELEMETRY", raising=False)
    runtime._configure_mem0_environment()
    assert runtime.os.environ["MEM0_TELEMETRY"] == "False"

    monkeypatch.setenv("MEM0_TELEMETRY", "True")
    runtime._configure_mem0_environment()
    assert runtime.os.environ["MEM0_TELEMETRY"] == "True"


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
    assert result.get("packageName") == "mem0ai"


def test_get_mem0_status_returns_valid_status():
    from frontend_bridge_core.memory import _get_mem0_status

    result = _get_mem0_status(start_loading=False)
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
    assert result["packageName"] == "mem0ai"


def test_get_mem0_status_reports_an_incompatible_memory_dependency_group(monkeypatch):
    from frontend_bridge_core import runtime_dependencies
    from frontend_bridge_core.memory import _get_mem0_status
    from sdk.exception.types import runtime_dependency_error_from_module

    dependency_error = runtime_dependency_error_from_module("mem0")
    dependency_error["message"] = (
        "Missing or incompatible Python runtime dependencies: "
        "huggingface-hub 1.24.0 does not satisfy huggingface-hub==0.36.2"
    )
    monkeypatch.setattr(
        runtime_dependencies,
        "runtime_dependency_error_for_module",
        lambda _module_name: dependency_error,
    )

    result = _get_mem0_status(start_loading=False)

    assert result["status"] == "missing_dependency"
    assert result["moduleName"] == "mem0"
    assert result["packageName"] == "mem0ai"
    assert "1.24.0" in result["message"]


def test_check_mem0_status_includes_task_when_import_fails(monkeypatch):
    import builtins

    from ai.memory import runtime

    original_import = builtins.__import__
    task = {"id": "mem0-embedding-model", "status": "running"}

    def _fake_import(name, *args, **kwargs):
        if name == "mem0":
            raise ModuleNotFoundError("No module named 'qdrant_client'", name="qdrant_client")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(runtime, "_mem0", None)
    monkeypatch.setattr(runtime, "_mem0_loading", False)
    monkeypatch.setattr(runtime, "_mem0_load_error", None)
    monkeypatch.setattr(runtime, "current_mem0_task", lambda: task)
    monkeypatch.setattr(builtins, "__import__", _fake_import)

    result = runtime.check_mem0_status()

    assert result == {
        "status": "missing_dependency",
        "message": "Missing Python module: qdrant_client",
        "moduleName": "qdrant_client",
        "packageName": "qdrant_client",
        "task": task,
    }


def test_check_mem0_status_does_not_retry_an_unresolved_dependency(monkeypatch):
    from ai.memory import runtime

    error = ModuleNotFoundError("No module named 'qdrant_client'", name="qdrant_client")
    starts = []
    monkeypatch.setattr(runtime, "_mem0", None)
    monkeypatch.setattr(runtime, "_mem0_loading", False)
    monkeypatch.setattr(runtime, "_mem0_load_error", error)
    monkeypatch.setattr(runtime, "current_mem0_task", lambda: None)
    monkeypatch.setattr(runtime, "_module_is_available", lambda module_name: False)
    monkeypatch.setattr(runtime, "start_mem0_loading", lambda: starts.append(True))

    result = runtime.check_mem0_status(start_loading=True)

    assert result == {
        "status": "missing_dependency",
        "message": "Missing Python module: qdrant_client",
        "moduleName": "qdrant_client",
        "packageName": "qdrant_client",
    }
    assert starts == []


def test_check_mem0_status_recovers_after_dependency_install(monkeypatch):
    import sys
    import types

    from ai.memory import runtime

    error = ModuleNotFoundError("No module named 'qdrant_client'", name="qdrant_client")
    starts = []
    monkeypatch.setitem(sys.modules, "mem0", types.ModuleType("mem0"))
    monkeypatch.setattr(runtime, "_mem0", None)
    monkeypatch.setattr(runtime, "_mem0_loading", False)
    monkeypatch.setattr(runtime, "_mem0_load_error", error)
    monkeypatch.setattr(runtime, "current_mem0_task", lambda: None)
    monkeypatch.setattr(runtime, "_module_is_available", lambda module_name: True)
    monkeypatch.setattr(runtime, "is_embedding_model_cached", lambda: False)
    monkeypatch.setattr(runtime, "start_mem0_loading", lambda: starts.append(True))

    assert runtime.check_mem0_status(start_loading=False) == {
        "status": "not_started",
        "modelCached": False,
    }
    assert runtime._mem0_load_error is None
    assert starts == []

    runtime._mem0_load_error = error
    assert runtime.check_mem0_status(start_loading=True) == {
        "status": "loading",
        "modelCached": False,
    }
    assert runtime._mem0_load_error is None
    assert starts == [True]


def test_check_mem0_status_returns_loading_when_retrying_an_error(monkeypatch):
    from ai.memory import runtime

    task = {"id": "mem0-embedding-model", "status": "running"}
    starts = []
    monkeypatch.setattr(runtime, "_mem0", None)
    monkeypatch.setattr(runtime, "_mem0_loading", False)
    monkeypatch.setattr(runtime, "_mem0_load_error", RuntimeError("initialization failed"))
    monkeypatch.setattr(runtime, "current_mem0_task", lambda: task)
    monkeypatch.setattr(runtime, "is_embedding_model_cached", lambda: True)
    monkeypatch.setattr(runtime, "start_mem0_loading", lambda: starts.append(True))

    result = runtime.check_mem0_status(start_loading=True)

    assert result == {"status": "loading", "modelCached": True, "task": task}
    assert starts == [True]


def test_start_mem0_loading_preserves_internal_missing_dependency(monkeypatch):
    import sys
    import types

    from ai.memory import runtime

    error = ModuleNotFoundError("No module named 'qdrant_client'", name="qdrant_client")
    updates = []

    def _raise_missing_dependency(*args, **kwargs):
        raise error

    mem0_module = types.ModuleType("mem0")
    mem0_module.Memory = object
    monkeypatch.setitem(sys.modules, "mem0", mem0_module)
    monkeypatch.setattr(runtime, "_mem0", None)
    monkeypatch.setattr(runtime, "_mem0_loading", False)
    monkeypatch.setattr(runtime, "_mem0_load_error", None)
    monkeypatch.setattr(runtime, "is_embedding_model_cached", lambda: True)
    monkeypatch.setattr(runtime, "_preload_embedding_model", lambda: r"\\?\D:\model")
    monkeypatch.setattr(runtime, "_create_mem0_instance", _raise_missing_dependency)
    monkeypatch.setattr(runtime, "set_mem0_task", lambda **update: updates.append(update))
    monkeypatch.setattr(runtime.threading, "Thread", _ImmediateThread)

    runtime.start_mem0_loading()

    assert runtime._mem0_load_error is error
    assert runtime._mem0_loading is False
    assert updates[-1]["error"] == "No module named 'qdrant_client'"
    assert updates[-1]["message"] == "Missing Python module: qdrant_client"


def test_start_mem0_loading_reports_post_download_failure_as_initialization(monkeypatch):
    import sys
    import types

    from ai.memory import runtime

    error = OSError(123, "invalid model path")
    updates = []

    def _raise_initialization_error(*args, **kwargs):
        raise error

    mem0_module = types.ModuleType("mem0")
    mem0_module.Memory = object
    monkeypatch.setitem(sys.modules, "mem0", mem0_module)
    monkeypatch.setattr(runtime, "_mem0", None)
    monkeypatch.setattr(runtime, "_mem0_loading", False)
    monkeypatch.setattr(runtime, "_mem0_load_error", None)
    monkeypatch.setattr(runtime, "is_embedding_model_cached", lambda: True)
    monkeypatch.setattr(runtime, "_preload_embedding_model", lambda: r"\\?\D:\model")
    monkeypatch.setattr(runtime, "_create_mem0_instance", _raise_initialization_error)
    monkeypatch.setattr(runtime, "set_mem0_task", lambda **update: updates.append(update))
    monkeypatch.setattr(runtime.threading, "Thread", _ImmediateThread)

    runtime.start_mem0_loading()

    assert runtime._mem0_load_error is error
    assert updates[-1]["errorCode"] == "memory_initialization_failed"
    assert updates[-1]["message"].startswith("长期记忆初始化失败：")


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


def test_preload_embedding_model_uses_shared_asset_service(monkeypatch):
    from ai.memory import runtime

    captured = {}
    snapshot_path = r"\\?\C:\very\deep\cache\snapshots\abc123"

    def _fake_download_model_asset(spec, *, update_task):
        captured["spec"] = spec
        captured["update_task"] = update_task
        return {"path": snapshot_path}

    monkeypatch.setattr(runtime, "download_model_asset", _fake_download_model_asset)

    result = runtime._preload_embedding_model()

    assert result == snapshot_path
    assert captured == {
        "spec": runtime.EMBEDDING_MODEL_ASSET,
        "update_task": runtime.set_mem0_task,
    }


def test_preload_embedding_model_requires_a_resolved_path(monkeypatch):
    import pytest

    from ai.memory import runtime

    monkeypatch.setattr(runtime, "download_model_asset", lambda *args, **kwargs: {})

    with pytest.raises(RuntimeError, match="could not be located"):
        runtime._preload_embedding_model()


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
    result = runtime._create_mem0_instance(_FakeMemory, snapshot_path)

    assert result == "memory-instance"
    assert captured["config"]["embedder"]["config"]["model"] == snapshot_path
