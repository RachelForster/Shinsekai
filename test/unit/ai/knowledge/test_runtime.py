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
