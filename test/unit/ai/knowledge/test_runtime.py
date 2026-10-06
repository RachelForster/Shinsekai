import importlib


import sys


from pathlib import Path


from types import SimpleNamespace


import pytest


from ai.knowledge import runtime, tasks


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch):
    monkeypatch.setattr(runtime, "_mem0", None)
    monkeypatch.setattr(runtime, "_mem0_load_error", None)
    monkeypatch.setattr(runtime, "_mem0_loading", False)
    monkeypatch.setattr(tasks, "_mem0_task", None)
    monkeypatch.setitem(sys.modules, "mem0", SimpleNamespace(Memory=object()))
    monkeypatch.setattr(runtime, "embedding_model_snapshot_path", lambda: Path("cached-model"))


def test_telemetry_defaults_off_and_preserves_opt_in(monkeypatch):
    monkeypatch.delenv("MEM0_TELEMETRY", raising=False)
    runtime._configure_mem0_environment()
    import os
    assert os.environ["MEM0_TELEMETRY"] == "False"
    monkeypatch.setenv("MEM0_TELEMETRY", "True")
    runtime._configure_mem0_environment()
    assert os.environ["MEM0_TELEMETRY"] == "True"


def test_status_preserves_missing_transitive_dependency(monkeypatch):
    def missing(_name):
        raise ModuleNotFoundError("No module named 'sentence_transformers'", name="sentence_transformers")
    monkeypatch.setattr(importlib, "import_module", missing)
    result = runtime.check_mem0_status(start_loading=False)
    assert result["status"] == "missing_dependency"
    assert result["moduleName"] == "sentence_transformers"


def test_peek_does_not_create_store_or_download(monkeypatch):
    monkeypatch.setattr(importlib, "import_module", lambda _: object())
    monkeypatch.setattr(runtime, "embedding_model_snapshot_path", lambda: None)
    monkeypatch.setattr(runtime, "start_mem0_loading", lambda: pytest.fail("peek started loading"))
    assert runtime.check_mem0_status(start_loading=False) == {"status": "not_started", "modelCached": False}


def test_cached_snapshot_and_knowledge_config_are_used_once(monkeypatch):
    import sys
    calls = []
    config = {"embedder": {"config": {}}, "vector_store": {"config": {"collection_name": "knowledge_knowledge"}}}
    store = object()
    def create(value):
        calls.append(value)
        return store
    monkeypatch.setitem(sys.modules, "mem0", SimpleNamespace(Memory=SimpleNamespace(from_config=create)))
    monkeypatch.setattr(runtime, "embedding_model_snapshot_path", lambda: Path("cached-model"))
    monkeypatch.setattr(runtime, "build_knowledge_mem0_config", lambda: config)
    monkeypatch.setattr(runtime, "download_model_asset", lambda *_: pytest.fail("unexpected download"))
    assert runtime.get_mem0() is store
    assert runtime.get_mem0() is store
    assert calls == [config]
    assert config["embedder"]["config"]["model"] == str(Path("cached-model"))


def test_background_initialization_is_single_and_reports_loading(monkeypatch):
    import threading
    entered = threading.Event()
    release = threading.Event()
    threads = []
    calls = []
    real_thread = threading.Thread
    def tracked_thread(**kwargs):
        thread = real_thread(**kwargs)
        threads.append(thread)
        return thread
    def create(*_args):
        calls.append(True)
        entered.set()
        assert release.wait(5)
        return object()
    monkeypatch.setattr(runtime.threading, "Thread", tracked_thread)
    monkeypatch.setattr(runtime, "_create_mem0_instance", create)
    try:
        runtime.start_mem0_loading()
        assert entered.wait(5)
        runtime.start_mem0_loading()
        assert runtime.check_mem0_status(start_loading=False)["status"] == "loading"
    finally:
        release.set()
        for thread in threads:
            thread.join(5)
    assert calls == [True]
    assert len(threads) == 1
    assert runtime.check_mem0_status(start_loading=False)["status"] == "ready"


def test_cold_knowledge_download_does_not_initialize_memory(monkeypatch):
    import sys
    from ai.memory import runtime as memory_runtime
    from core.model_assets.service import download_model_asset as real_download
    import inspect

    monkeypatch.setattr(memory_runtime, "get_mem0", lambda: pytest.fail("Knowledge initialized Memory"))
    monkeypatch.setattr(memory_runtime, "ensure_mem0", lambda: pytest.fail("Knowledge initialized Memory"))
    monkeypatch.setattr(memory_runtime, "_mem0_load_error", RuntimeError("Memory failed"))
    monkeypatch.setattr(runtime, "embedding_model_snapshot_path", lambda: None)
    downloads = []
    def download(*args, **kwargs):
        inspect.signature(real_download).bind(*args, **kwargs)
        kwargs["update_task"](phase="download", progress=0.5)
        downloads.append(args[0])
        return {"path": "knowledge-downloaded-model"}
    monkeypatch.setattr(runtime, "download_model_asset", download)
    config = {"embedder": {"config": {}}}
    monkeypatch.setattr(runtime, "build_knowledge_mem0_config", lambda: config)
    store = object()
    monkeypatch.setitem(sys.modules, "mem0", SimpleNamespace(Memory=SimpleNamespace(from_config=lambda _: store)))
    assert runtime.get_mem0() is store
    assert len(downloads) == 1
    assert config["embedder"]["config"]["model"] == "knowledge-downloaded-model"
    assert tasks.current_mem0_task()["status"] == "succeeded"


def test_failed_dependency_waits_for_install_then_can_restart(monkeypatch):
    monkeypatch.setattr(runtime, "_mem0_load_error", ModuleNotFoundError("No module named 'mem0'", name="mem0"))
    monkeypatch.setattr(importlib.util, "find_spec", lambda _: None)
    assert runtime.check_mem0_status()["status"] == "missing_dependency"
    monkeypatch.setattr(importlib.util, "find_spec", lambda _: object())
    monkeypatch.setattr(importlib, "import_module", lambda _: object())
    monkeypatch.setattr(runtime, "embedding_model_snapshot_path", lambda: Path("cached"))
    starts = []
    monkeypatch.setattr(runtime, "start_mem0_loading", lambda **kwargs: starts.append(kwargs))
    assert runtime.check_mem0_status()["status"] == "error"
    assert starts == []
    assert runtime.check_mem0_status(retry=True)["status"] == "loading"
    assert starts == [{"retry": True}]


def test_initialization_failure_is_reported_and_success_clears_it(monkeypatch):
    def fail(*_args):
        raise RuntimeError("bad config")
    monkeypatch.setattr(runtime, "_create_mem0_instance", fail)
    with pytest.raises(RuntimeError, match="bad config"):
        runtime.get_mem0()
    assert runtime.check_mem0_status(start_loading=False)["error"] == "bad config"
    assert runtime.check_mem0_status()["status"] == "error"
    store = object()
    monkeypatch.setattr(runtime, "_create_mem0_instance", lambda *_: store)
    runtime.start_mem0_loading(retry=True)
    assert runtime.get_mem0() is store
    assert runtime._mem0_load_error is None
    assert runtime.check_mem0_status()["status"] == "ready"


def test_failed_knowledge_polling_does_not_restart(monkeypatch):
    calls = []
    def fail(*_args):
        calls.append(True)
        raise RuntimeError("download unavailable")
    monkeypatch.setattr(runtime, "_create_mem0_instance", fail)
    with pytest.raises(RuntimeError, match="download unavailable"):
        runtime.get_mem0()
    for _ in range(3):
        assert runtime.check_mem0_status()["error"] == "download unavailable"
        runtime.start_mem0_loading()
        with pytest.raises(RuntimeError, match="download unavailable"):
            runtime.get_mem0()
    assert len(calls) == 1


def test_retry_implies_start_even_when_peeking(monkeypatch):
    monkeypatch.setattr(runtime, "_mem0_load_error", RuntimeError("failed"))
    monkeypatch.setattr(importlib, "import_module", lambda _: object())
    monkeypatch.setattr(runtime, "embedding_model_snapshot_path", lambda: None)
    calls = []
    monkeypatch.setattr(runtime, "start_mem0_loading", lambda **kwargs: calls.append(kwargs))
    assert runtime.check_mem0_status(start_loading=False, retry=True)["status"] == "loading"
    assert calls == [{"retry": True}]


def test_get_waits_for_background_creation_and_times_out(monkeypatch):
    import threading
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    caller = threading.get_ident()
    workers = []
    store = object()

    def create(*_args):
        workers.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
        return store

    real_thread = threading.Thread
    def tracked_thread(**kwargs):
        target = kwargs.pop("target")
        def run():
            try:
                target()
            finally:
                finished.set()
        return real_thread(target=run, **kwargs)

    monkeypatch.setattr(runtime.threading, "Thread", tracked_thread)
    monkeypatch.setattr(runtime, "_create_mem0_instance", create)
    monkeypatch.setattr(runtime, "_GET_MEM0_TIMEOUT_SEC", 0.02)
    try:
        with pytest.raises(TimeoutError, match="Knowledge mem0"):
            runtime.get_mem0()
        assert entered.is_set()
        assert workers == [workers[0]] and workers[0] != caller
        assert runtime._mem0_loading
    finally:
        release.set()
        assert finished.wait(5)
    assert runtime.get_mem0() is store


@pytest.mark.parametrize("module_name", ["sentence_transformers", None])
def test_background_dependency_error_has_structured_task(monkeypatch, module_name):
    error = ModuleNotFoundError("dependency unavailable", name=module_name)
    def fail(*_args):
        raise error
    monkeypatch.setattr(runtime, "_create_mem0_instance", fail)
    monkeypatch.setattr(importlib.util, "find_spec", lambda _: None)
    with pytest.raises(ModuleNotFoundError):
        runtime.get_mem0()
    status = runtime.check_mem0_status(start_loading=False)
    assert status["status"] == "missing_dependency"
    assert status["moduleName"] == (module_name or "mem0")
    assert status["task"]["errorCode"] == "missing_dependency"
    assert status["task"]["status"] == "failed"
    assert status["task"]["errorUserMessage"]


def test_download_error_and_retry_reset_task(monkeypatch):
    import httpx
    request = httpx.Request("GET", "https://example.test/model")
    response = httpx.Response(503, request=request)
    error = httpx.HTTPStatusError("unavailable", request=request, response=response)
    monkeypatch.setattr(runtime, "embedding_model_snapshot_path", lambda: None)
    def download(*_args, **_kwargs):
        raise error
    monkeypatch.setattr(runtime, "download_model_asset", download)
    with pytest.raises(httpx.HTTPStatusError):
        runtime.get_mem0()
    status = runtime.check_mem0_status(start_loading=False)
    task = status["task"]
    assert task["httpStatus"] == 503
    assert task["errorCode"] != "knowledge_initialization_failed"
    assert status["message"] == task["errorUserMessage"]
    tasks.set_mem0_task(logs=["previous attempt"], result="old result")
    snapshots = []
    store = object()
    def create(*_args):
        snapshots.append(tasks.current_mem0_task())
        return store
    monkeypatch.setattr(runtime, "embedding_model_snapshot_path", lambda: Path("cached"))
    monkeypatch.setattr(runtime, "_create_mem0_instance", create)
    runtime.start_mem0_loading(retry=True)
    assert runtime.get_mem0() is store
    clean = snapshots[0]
    assert clean["error"] == clean["errorCode"] == clean["errorUserMessage"] == ""
    assert clean["httpStatus"] is None
    assert clean["logs"] == [] and clean["result"] is None
    assert runtime.check_mem0_status()["task"]["status"] == "succeeded"


def test_thread_start_failure_is_recorded(monkeypatch):
    def fail():
        raise RuntimeError("cannot start thread")
    monkeypatch.setattr(runtime.threading, "Thread", lambda **_: SimpleNamespace(start=fail))
    with pytest.raises(RuntimeError, match="cannot start thread"):
        runtime.start_mem0_loading()
    assert not runtime._mem0_loading
    status = runtime.check_mem0_status(start_loading=False)
    assert status["task"]["status"] == "failed"
    assert status["task"]["errorCode"] == "knowledge_initialization_failed"
    with pytest.raises(RuntimeError, match="cannot start thread"):
        runtime.get_mem0()
