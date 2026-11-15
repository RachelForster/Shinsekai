from __future__ import annotations

from types import SimpleNamespace

import pytest

import frontend_bridge
from application.chat import composition as chat


class _ChatStreamStub:
    def __init__(self):
        self.sent = []
        self.stopped = False

    def send_command(self, session_id, command):
        self.sent.append((session_id, command))
        return True

    def stop(self):
        self.stopped = True


def test_plugin_frontend_input_forwards_to_active_chat_stream() -> None:
    stream = _ChatStreamStub()
    state = SimpleNamespace(
        chat_session={"sessionId": "session-1"},
        chat_stream=stream,
    )

    frontend_bridge._forward_plugin_user_input(
        state,
        {
            "pluginId": "demo.plugin",
            "text": "[短信] 请角色回复",
            "type": "plugin.user-input.submit",
        },
    )

    assert len(stream.sent) == 1
    session_id, command = stream.sent[0]
    assert session_id == "session-1"
    assert command["type"] == "send-message"
    assert command["payload"] == {
        "attachments": [],
        "text": "[短信] 请角色回复",
    }
    assert command["cmdId"]


def test_shutdown_bridge_runtime_stops_active_chat_and_stream(monkeypatch):
    calls = []
    stream = _ChatStreamStub()
    state = SimpleNamespace(chat_stream=stream)

    def fake_shutdown_active_chat_process(*, wait_timeout, wait_before_signal=0.0):
        calls.append((wait_timeout, wait_before_signal))

    monkeypatch.setattr(
        chat, "shutdown_active_chat_process", fake_shutdown_active_chat_process
    )
    frontend_bridge._set_bridge_state(state)
    try:
        frontend_bridge._shutdown_bridge_runtime("unit-test")
    finally:
        frontend_bridge._set_bridge_state(None)

    assert calls == [(1.5, 0.0)]
    assert stream.stopped is True


def test_parent_watchdog_exit_cleans_bridge_runtime_before_process_exit(monkeypatch):
    calls = []

    def fake_exit(code):
        raise SystemExit(code)

    monkeypatch.setattr(
        frontend_bridge, "_shutdown_bridge_runtime", lambda reason: calls.append(reason)
    )
    monkeypatch.setattr(frontend_bridge.os, "_exit", fake_exit)

    with pytest.raises(SystemExit) as exc:
        frontend_bridge._exit_bridge_after_parent_loss("parent_missing parent_pid=123")

    assert exc.value.code == 0
    assert calls == ["parent watchdog parent_missing parent_pid=123"]


def test_agent_service_closes_before_other_bridge_transports(monkeypatch):
    calls = []
    monkeypatch.setattr(
        chat, "shutdown_active_chat_process", lambda **kwargs: calls.append("chat")
    )
    frontend_bridge._set_bridge_state(
        SimpleNamespace(
            services=SimpleNamespace(close=lambda: calls.append("agent")),
            chat_stream=SimpleNamespace(stop=lambda: calls.append("stream")),
        )
    )
    try:
        frontend_bridge._shutdown_bridge_runtime("unit-test")
    finally:
        frontend_bridge._set_bridge_state(None)
    assert calls == ["agent", "chat", "stream"]


def test_threading_http_server_memory_and_knowledge_routes_bound_connections_and_shutdown_closes_stores(
    monkeypatch,
    tmp_path,
):
    from concurrent.futures import ThreadPoolExecutor
    from http.server import ThreadingHTTPServer
    import json
    import threading
    from urllib import request as urllib_request

    from ai.knowledge.config import HybridKnowledgeStore
    from ai.memory import runtime as memory_runtime
    from ai.memory.backends.in_memory import DeterministicHashEmbedder
    from ai.memory.backends.sqlite_repo import SqliteHybridMemoryRepo
    from ai.memory.engine import HybridMemoryEngine
    from application.knowledge import runtime as knowledge_runtime
    from application.memory import manage_memories
    from core.knowledge import catalog as knowledge_catalog
    from core.vector_store.sqlite_hybrid_store import SqliteHybridStore
    from frontend_bridge_core.routes.api import BRIDGE_AUTH_HEADER, FrontendBridgeHandler

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "application.runtime.dependencies.runtime_dependency_error_for_module",
        lambda _module_name: None,
    )
    monkeypatch.setattr(
        "frontend_bridge_core.memory._check_mem0_before_call",
        lambda: None,
    )
    monkeypatch.setattr(
        "frontend_bridge_core.knowledge._check_mem0_before_call",
        lambda: None,
    )
    monkeypatch.setattr(
        chat, "shutdown_active_chat_process", lambda **_kwargs: None
    )

    mem_db = tmp_path / "data" / "memory" / "bridge_memory.db"
    know_db = tmp_path / "data" / "knowledge" / "bridge_knowledge.db"
    embedder = DeterministicHashEmbedder(dimensions=384)
    mem_store = SqliteHybridStore(mem_db, max_idle_connections=2)
    mem_engine = HybridMemoryEngine(
        embedder=embedder,
        repo=SqliteHybridMemoryRepo(mem_store),
        vector_store=mem_store,
        store=mem_store,
    )
    know_store = SqliteHybridStore(know_db, max_idle_connections=2)
    know_client = HybridKnowledgeStore(
        embedder=embedder,
        port=know_store,
        store=know_store,
    )

    memory_runtime.shutdown_memory_runtime()
    knowledge_runtime.shutdown_knowledge_runtime()
    monkeypatch.setattr(memory_runtime, "_mem0", mem_engine)
    monkeypatch.setattr(memory_runtime, "_mem0_loading", False)
    monkeypatch.setattr(memory_runtime, "_mem0_load_error", None)
    monkeypatch.setattr(knowledge_runtime, "_mem0", know_client)
    monkeypatch.setattr(knowledge_runtime, "_mem0_loading", False)
    monkeypatch.setattr(knowledge_runtime, "_mem0_load_error", None)

    token = "bridge-test-secret-token"
    state = SimpleNamespace(
        auth_token=token,
        project_root_dir=str(tmp_path),
        app_root_dir=str(tmp_path),
        frontend_dist_dir="",
        chat_stream=None,
    )
    frontend_bridge._set_bridge_state(state)

    server = ThreadingHTTPServer(("127.0.0.1", 0), FrontendBridgeHandler)
    server.state = state  # type: ignore[attr-defined]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    def _post_json(path: str, payload: dict[str, object]) -> dict[str, object]:
        req = urllib_request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Origin": base_url,
                BRIDGE_AUTH_HEADER: token,
                "Connection": "close",
            },
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=10.0) as resp:
            assert resp.status == 200
            return json.loads(resp.read().decode("utf-8"))

    try:
        # 24 requests served by distinct short-lived ThreadingHTTPServer worker threads
        def _exercise_pair(idx: int) -> None:
            r1 = _post_json(
                "/api/memory/remember",
                {"characterName": "Alice", "content": f"第 {idx} 次桥接记忆写入"},
            )
            assert r1.get("ok") is True
            r2 = _post_json(
                "/api/memory/search",
                {"characterName": "Alice", "query": f"第 {idx} 次", "limit": 3},
            )
            assert "error" not in r2 and isinstance(r2.get("memories"), list)
            r3 = _post_json(
                "/api/knowledge/remember",
                {"knowledge_id": "lore-main", "content": f"设定条目 {idx}：世界树支脉"},
            )
            assert r3.get("ok") is True
            r4 = _post_json(
                "/api/knowledge/entries/search",
                {"knowledge_id": "lore-main", "query": f"设定条目 {idx}", "limit": 5},
            )
            assert isinstance(r4.get("memories"), list) and r4.get("count", 0) >= 1

        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(_exercise_pair, range(6)))

        assert mem_store.active_connection_count == 0
        assert mem_store.idle_connection_count <= 2
        assert know_store.active_connection_count == 0
        assert know_store.idle_connection_count <= 2

        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5.0)

        frontend_bridge._shutdown_bridge_runtime("unit-test-close-stores")

        assert mem_store.is_closed is True
        assert mem_store.idle_connection_count == 0
        assert know_store.is_closed is True
        assert know_store.idle_connection_count == 0
        assert memory_runtime._mem0 is None
        assert knowledge_runtime._mem0 is None
        assert knowledge_catalog._catalog_client is None

        # Proves zero leaked Windows file handles / WAL handles after bridge shutdown
        mem_db.unlink()
        know_db.unlink()
    finally:
        server.shutdown()
        server.server_close()
        frontend_bridge._set_bridge_state(None)
        manage_memories.shutdown_memory_runtime()
        knowledge_runtime.shutdown_knowledge_runtime()


def test_shutdown_runtime_prevents_inflight_loader_from_publishing_unclosed_stores(
    monkeypatch,
):
    import threading

    from ai.memory import runtime as memory_runtime
    from application.knowledge import runtime as knowledge_runtime

    mem_entered = threading.Event()
    mem_release = threading.Event()
    closed_mem: list[str] = []

    class _FakeMemEngine:
        def close(self) -> None:
            closed_mem.append("mem_closed")

    def _slow_create_mem_engine(_cls, _snapshot_path):
        mem_entered.set()
        mem_release.wait(timeout=5.0)
        return _FakeMemEngine()

    memory_runtime.shutdown_memory_runtime()
    monkeypatch.setattr(memory_runtime, "is_embedding_model_cached", lambda: True)
    monkeypatch.setattr(memory_runtime, "_preload_embedding_model", lambda: "snap")
    monkeypatch.setattr(memory_runtime, "_create_mem0_instance", _slow_create_mem_engine)
    monkeypatch.setattr(
        "application.runtime.dependencies.runtime_dependency_error_for_module",
        lambda _m: None,
    )

    memory_runtime.start_mem0_loading()
    assert mem_entered.wait(timeout=5.0)
    memory_runtime.shutdown_memory_runtime()
    mem_release.set()

    for t in list(threading.enumerate()):
        if t is not threading.current_thread() and t.daemon:
            if t.name in {"Thread", "knowledge-loader"} or "load" in t.name or t.name.startswith("Thread-"):
                t.join(timeout=2.0)

    assert closed_mem == ["mem_closed"]
    assert memory_runtime._mem0 is None

    know_entered = threading.Event()
    know_release = threading.Event()
    closed_know: list[str] = []

    class _FakeKnowClient:
        def close(self) -> None:
            closed_know.append("know_closed")

    def _slow_create_know_client(_cls, _snapshot_path):
        know_entered.set()
        know_release.wait(timeout=5.0)
        return _FakeKnowClient()

    knowledge_runtime.shutdown_knowledge_runtime()
    monkeypatch.setattr(
        knowledge_runtime, "configure_mem0_environment", lambda: None
    )
    monkeypatch.setattr(
        knowledge_runtime, "_preload_embedding_model", lambda: "snap"
    )
    monkeypatch.setattr(
        knowledge_runtime, "create_knowledge_mem0", _slow_create_know_client
    )

    knowledge_runtime.start_mem0_loading()
    assert know_entered.wait(timeout=5.0)
    knowledge_runtime.shutdown_knowledge_runtime()
    know_release.set()

    for t in list(threading.enumerate()):
        if t is not threading.current_thread() and t.daemon:
            if t.name in {"Thread", "knowledge-loader"} or "load" in t.name or t.name.startswith("Thread-"):
                t.join(timeout=2.0)

    assert closed_know == ["know_closed"]
    assert knowledge_runtime._mem0 is None
