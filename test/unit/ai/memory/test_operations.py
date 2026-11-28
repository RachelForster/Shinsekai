from __future__ import annotations

import io
import json
import urllib.error

from ai.memory import operations


class _FakeMemory:
    def get_all(self, *, filters, limit):
        assert filters == {"user_id": "Alice"}
        assert limit == 200
        return {
            "results": [
                {"id": "1", "memory": "likes tea"},
                {"id": "2", "content": "likes books"},
                "loose row",
            ]
        }


class _TopKFakeMemory:
    def __init__(self):
        self.requested_top_k = None

    def get_all(self, *, filters, top_k=20, **kwargs):
        assert filters == {"user_id": "Alice"}
        self.requested_top_k = top_k
        return {"results": [{"id": str(index), "memory": f"memory-{index}"} for index in range(top_k)]}


class _RecordingLock:
    def __init__(self):
        self.active = False
        self.enter_count = 0

    def __enter__(self):
        assert not self.active
        self.active = True
        self.enter_count += 1
        return self

    def __exit__(self, *_args):
        assert self.active
        self.active = False
        return False


class _LockedFakeMemory:
    def __init__(self, lock: _RecordingLock):
        self.lock = lock

    def get_all(self, *, filters, limit):
        assert self.lock.active
        return {"results": []}

    def search(self, query, *, filters, limit):
        assert self.lock.active
        return []

    def add(self, content, *, user_id, infer):
        assert self.lock.active

    def delete(self, memory_id):
        assert self.lock.active


class _DedupeFakeMemory:
    def __init__(self, search_result):
        self.search_result = search_result
        self.search_calls = []
        self.add_calls = []

    def search(self, query, *, filters, limit):
        self.search_calls.append((query, filters, limit))
        return self.search_result

    def add(self, content, *, user_id, infer):
        self.add_calls.append((content, user_id, infer))


class _TopKSearchFakeMemory:
    def __init__(self):
        self.requested_top_k = None

    def search(self, query, *, filters, top_k=20, **kwargs):
        self.requested_top_k = top_k
        return {"results": []}


def test_memory_list_normalizes_rows(monkeypatch):
    monkeypatch.delenv("SHINSEKAI_MEMORY_SERVICE_URL", raising=False)
    monkeypatch.setattr(operations, "ensure_mem0", lambda: _FakeMemory())

    result = operations.memory_list("Alice")

    assert result == {
        "agentId": "Alice",
        "count": 3,
        "memories": [
            {"id": "1", "memory": "likes tea"},
            {"id": "2", "memory": "likes books"},
            {"id": "", "memory": "loose row"},
        ],
        "total": 3,
    }


def test_memory_list_uses_top_k_with_new_mem0_versions(monkeypatch):
    memory = _TopKFakeMemory()
    monkeypatch.delenv("SHINSEKAI_MEMORY_SERVICE_URL", raising=False)
    monkeypatch.setattr(operations, "ensure_mem0", lambda: memory)

    result = operations.memory_list("Alice", limit=200)

    assert memory.requested_top_k == 200
    assert result["count"] == 200


def test_local_memory_operations_are_serialized(monkeypatch):
    lock = _RecordingLock()
    memory = _LockedFakeMemory(lock)
    monkeypatch.delenv("SHINSEKAI_MEMORY_SERVICE_URL", raising=False)
    monkeypatch.setattr(operations, "_mem0_operation_lock", lock)
    monkeypatch.setattr(operations, "ensure_mem0", lambda: memory)

    assert operations.memory_list("Alice")["count"] == 0
    assert operations.memory_search("tea", character_name="Alice")["count"] == 0
    assert operations.memory_remember("tea", character_name="Alice")["ok"] is True
    assert operations.memory_forget("mem-1")["ok"] is True
    assert lock.enter_count == 4


def test_memory_remember_skips_semantic_duplicate_for_same_character(monkeypatch):
    memory = _DedupeFakeMemory(
        {"results": [{"id": "existing-1", "memory": "Alice likes black tea", "score": 0.95}]}
    )
    monkeypatch.delenv("SHINSEKAI_MEMORY_SERVICE_URL", raising=False)
    monkeypatch.setattr(operations, "ensure_mem0", lambda: memory)

    result = operations.memory_remember("Alice loves black tea", character_name="Alice")

    assert result["ok"] is True
    assert result["duplicate"] is True
    assert result["duplicate_type"] == "semantic"
    assert result["existing_memory_id"] == "existing-1"
    assert memory.search_calls == [
        (
            "Alice loves black tea",
            {"user_id": "Alice"},
            operations._SEMANTIC_DEDUPLICATION_SEARCH_LIMIT,
        )
    ]
    assert memory.add_calls == []


def test_memory_remember_adds_when_existing_memory_is_below_threshold(monkeypatch):
    memory = _DedupeFakeMemory(
        {"results": [{"id": "existing-1", "memory": "Alice likes coffee", "score": 0.72}]}
    )
    monkeypatch.delenv("SHINSEKAI_MEMORY_SERVICE_URL", raising=False)
    monkeypatch.setattr(operations, "ensure_mem0", lambda: memory)

    result = operations.memory_remember("Alice likes black tea", character_name="Alice")

    assert result == {
        "ok": True,
        "duplicate": False,
        "agent_id": "Alice",
        "content": "Alice likes black tea",
    }
    assert memory.add_calls == [("Alice likes black tea", "Alice", False)]


def test_memory_remember_detects_exact_duplicate_without_search_score(monkeypatch):
    memory = _DedupeFakeMemory({"results": [{"id": "existing-1", "memory": "Alice likes tea"}]})
    monkeypatch.delenv("SHINSEKAI_MEMORY_SERVICE_URL", raising=False)
    monkeypatch.setattr(operations, "ensure_mem0", lambda: memory)

    result = operations.memory_remember("  Alice likes tea  ", character_name="Alice")

    assert result["duplicate"] is True
    assert result["duplicate_type"] == "exact"
    assert memory.add_calls == []


def test_memory_search_uses_top_k_with_new_mem0_versions(monkeypatch):
    memory = _TopKSearchFakeMemory()
    monkeypatch.delenv("SHINSEKAI_MEMORY_SERVICE_URL", raising=False)
    monkeypatch.setattr(operations, "ensure_mem0", lambda: memory)

    result = operations.memory_search("tea", character_name="Alice", limit=200)

    assert result["count"] == 0
    assert memory.requested_top_k == 200


def test_memory_remember_and_list_rejects_empty_content():
    assert operations.memory_remember_and_list("  ", character_name="Alice") == {
        "error": "memory content is required"
    }


def test_memory_forget_and_list_rejects_empty_id():
    assert operations.memory_forget_and_list("  ", character_name="Alice") == {
        "error": "memory id is required"
    }


def test_memory_forget_many_and_list_rejects_empty_ids():
    assert operations.memory_forget_many_and_list(["", "  "], character_name="Alice") == {
        "error": "memory ids are required"
    }


def test_memory_forget_many_and_list_dedupes_and_reports_failures(monkeypatch):
    forgotten: list[str] = []

    def fake_forget(memory_id, *, session_id=None, memory_mode=""):
        forgotten.append(memory_id)
        if memory_id == "missing":
            return {"error": "memory not found", "memory_id": memory_id}
        return {"ok": True, "memory_id": memory_id}

    list_calls: list[tuple] = []

    def fake_list(character_name=None, **kwargs):
        list_calls.append((character_name, kwargs))
        return {"agentId": character_name, "count": 1, "memories": [{"id": "keep", "memory": "x"}]}

    monkeypatch.setattr(operations, "memory_forget", fake_forget)
    monkeypatch.setattr(operations, "memory_list", fake_list)

    result = operations.memory_forget_many_and_list(["a", "b", "a", "missing"], character_name="Alice")

    assert forgotten == ["a", "b", "missing"]
    assert list_calls == [("Alice", {})]
    assert result["deleted"] == ["a", "b"]
    assert result["failed"] == [{"memoryId": "missing", "error": "memory not found"}]
    assert result["memories"] == [{"id": "keep", "memory": "x"}]


def test_memory_forget_many_and_list_returns_error_when_all_fail(monkeypatch):
    monkeypatch.setattr(
        operations,
        "memory_forget",
        lambda memory_id, **_kwargs: {"error": "memory not found", "memory_id": memory_id},
    )
    monkeypatch.setattr(operations, "memory_list", lambda *_a, **_k: {"memories": []})

    result = operations.memory_forget_many_and_list(["x"], character_name="Alice")

    assert result["error"] == "memory not found"


class _FakeHttpResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int = -1):
        import json

        return json.dumps(self.payload).encode("utf-8")


class _RawHttpResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int = -1):
        return self.body


def test_memory_search_uses_memory_service_without_local_mem0(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = request.data
        captured["token"] = request.headers.get("X-shinsekai-bridge-token")
        return _FakeHttpResponse({"count": 1, "memories": [{"memory": "likes tea"}]})

    def fail_ensure_mem0():
        raise AssertionError("memory_search should not initialize local mem0 when service is configured")

    monkeypatch.setenv("SHINSEKAI_MEMORY_SERVICE_URL", "http://127.0.0.1:8787/api/memory")
    monkeypatch.setenv("SHINSEKAI_MEMORY_SERVICE_TOKEN", "secret")
    monkeypatch.setattr(operations.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(operations, "ensure_mem0", fail_ensure_mem0)

    result = operations.memory_search("tea", character_name="Alice", limit=3)

    assert result == {"count": 1, "memories": [{"memory": "likes tea"}]}
    assert captured["url"] == "http://127.0.0.1:8787/api/memory/search"
    assert captured["timeout"] == 60
    assert captured["token"] == "secret"
    assert b'"query": "tea"' in captured["body"]
    assert b'"characterName": "Alice"' in captured["body"]
    assert b'"limit": 3' in captured["body"]


def test_memory_search_uses_configured_memory_service_timeout(monkeypatch):
    captured = {}

    def fake_urlopen(_request, timeout):
        captured["timeout"] = timeout
        return _FakeHttpResponse({"count": 0, "memories": []})

    monkeypatch.setenv("SHINSEKAI_MEMORY_SERVICE_URL", "http://127.0.0.1:8787/api/memory")
    monkeypatch.setenv("SHINSEKAI_MEMORY_SERVICE_TIMEOUT_SEC", "12.5")
    monkeypatch.setattr(operations.urllib.request, "urlopen", fake_urlopen)

    assert operations.memory_search("tea", character_name="Alice") == {"count": 0, "memories": []}
    assert captured["timeout"] == 12.5


def test_memory_search_reports_memory_service_http_error(monkeypatch):
    def fake_urlopen(_request, timeout=None):
        raise urllib.error.HTTPError(
            url="http://127.0.0.1:8787/api/memory/search",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=io.BytesIO(b"bridge unavailable"),
        )

    monkeypatch.setenv("SHINSEKAI_MEMORY_SERVICE_URL", "http://127.0.0.1:8787/api/memory")
    monkeypatch.setattr(operations.urllib.request, "urlopen", fake_urlopen)

    result = operations.memory_search("tea", character_name="Alice")

    assert "error" in result
    assert "503" in result["error"]
    assert "bridge unavailable" in result["error"]


def test_memory_search_reports_memory_service_invalid_json(monkeypatch):
    def fake_urlopen(_request, timeout=None):
        return _RawHttpResponse(b"not-json")

    monkeypatch.setenv("SHINSEKAI_MEMORY_SERVICE_URL", "http://127.0.0.1:8787/api/memory")
    monkeypatch.setattr(operations.urllib.request, "urlopen", fake_urlopen)

    result = operations.memory_search("tea", character_name="Alice")

    assert "error" in result
    assert "memory service returned invalid JSON" in result["error"]
    assert "not-json" in result["error"]


def test_memory_service_loading_starts_ready_monitor(monkeypatch):
    started = []

    def fake_urlopen(_request, timeout):
        return _FakeHttpResponse({"status": "loading", "message": "loading"})

    monkeypatch.setenv("SHINSEKAI_MEMORY_SERVICE_URL", "http://127.0.0.1:8787/api/memory")
    monkeypatch.setattr(operations.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(operations, "_start_memory_service_ready_monitor", lambda: started.append(True))

    assert operations.memory_search("tea", character_name="Alice") == {"status": "loading", "message": "loading"}
    assert started == [True]


def test_memory_service_status_controls_loading_without_background_monitor(monkeypatch):
    captured = {}
    started = []

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeHttpResponse({"status": "loading", "message": "loading"})

    monkeypatch.setenv("SHINSEKAI_MEMORY_SERVICE_URL", "http://127.0.0.1:8787/api/memory")
    monkeypatch.setattr(operations.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(operations, "_start_memory_service_ready_monitor", lambda: started.append(True))

    result = operations.memory_service_status(start_loading=False, monitor_ready=False)

    assert result == {"status": "loading", "message": "loading"}
    assert captured == {
        "url": "http://127.0.0.1:8787/api/memory/status",
        "body": {"startLoading": False},
    }
    assert started == []


def test_memory_service_owner_skips_proxy(monkeypatch):
    monkeypatch.setenv("SHINSEKAI_MEMORY_SERVICE_URL", "http://127.0.0.1:8787/api/memory")
    monkeypatch.setenv("SHINSEKAI_MEMORY_SERVICE_OWNER", "1")
    monkeypatch.setattr(operations, "ensure_mem0", lambda: _FakeMemory())

    result = operations.memory_list("Alice")

    assert result["count"] == 3


def test_memory_remember_and_list_preserves_loading_result(monkeypatch):
    def remember(_text, *, character_name, source_session_id):
        assert character_name == "Alice"
        assert source_session_id == ""
        return {"status": "loading", "message": "loading"}

    monkeypatch.setattr(operations, "memory_remember", remember)
    monkeypatch.setattr(
        operations,
        "memory_list",
        lambda character_name=None: (_ for _ in ()).throw(AssertionError("should not list while loading")),
    )

    assert operations.memory_remember_and_list("tea", character_name="Alice") == {
        "status": "loading",
        "message": "loading",
    }


def test_memory_list_all_pages_until_total(monkeypatch):
    rows = [{"id": f"m{i}", "memory": f"memory {i}"} for i in range(7)]
    calls: list[tuple[int, int]] = []

    def fake_list(character_name=None, *, limit=200, offset=0, **_kwargs):
        calls.append((offset, limit))
        window = rows[offset:offset + limit]
        return {
            "agentId": character_name,
            "count": len(window),
            "memories": window,
            "total": len(rows),
            "offset": offset,
        }

    monkeypatch.setattr(operations, "memory_list", fake_list)

    result = operations.memory_list_all("Alice", batch_size=3)

    assert calls == [(0, 3), (3, 3), (6, 3)]
    assert [row["id"] for row in result["memories"]] == [f"m{i}" for i in range(7)]
    assert result["total"] == 7


def test_memory_list_all_stops_when_backend_ignores_offset(monkeypatch):
    rows = [{"id": f"m{i}", "memory": "x"} for i in range(3)]
    monkeypatch.setattr(
        operations,
        "memory_list",
        lambda *_a, **_k: {"agentId": "Alice", "count": 3, "memories": rows},
    )

    result = operations.memory_list_all("Alice", batch_size=3)

    assert [row["id"] for row in result["memories"]] == ["m0", "m1", "m2"]


def test_memory_list_mem0_fallback_windows_rows(monkeypatch):
    class _Mem:
        def get_all(self, *, filters, limit):
            return {"results": [{"id": str(i), "memory": f"m{i}"} for i in range(min(limit, 5))]}

    monkeypatch.delenv("SHINSEKAI_MEMORY_SERVICE_URL", raising=False)
    monkeypatch.setattr(operations, "ensure_mem0", lambda: _Mem())

    result = operations.memory_list("Alice", limit=2, offset=2)

    assert [row["id"] for row in result["memories"]] == ["2", "3"]
    assert result["offset"] == 2
    assert "total" not in result  # backend returned a full window, total unknown


def test_memory_list_and_list_all_support_repo_without_count_memories(monkeypatch):
    from ai.memory.backends.in_memory import DeterministicHashEmbedder
    from ai.memory.engine import HybridMemoryEngine
    from core.vector_store.in_memory import InMemoryMemoryRepository
    from sdk.adapters.memory import SCOPE_CHAR_CROSS_SAVE, MemoryRecord

    inner = InMemoryMemoryRepository()
    embedder = DeterministicHashEmbedder(dimensions=64)
    for index in range(5):
        inner.upsert(
            MemoryRecord(
                id=f"m{index}",
                scope=SCOPE_CHAR_CROSS_SAVE,
                owner_id="Alice",
                detail_text=f"Alice memory {index}",
                gist_text=f"Alice memory {index}",
                created_at=100.0 + index,
                embedding=embedder.embed_query(f"Alice memory {index}"),
            )
        )

    class _NoCountRepo:
        def upsert(self, record):
            return inner.upsert(record)

        def get(self, memory_id):
            return inner.get(memory_id)

        def search_candidates(self, query):
            return inner.search_candidates(query)

        def expand_entities(self, entities, scope_filter, *, limit=10):
            return inner.expand_entities(entities, scope_filter, limit=limit)

        def list_by_scope(self, scope_filter, *, limit=200):
            return inner.list_by_scope(scope_filter, limit=limit)

        def record_recall(self, memory_ids, *, recalled_at):
            return inner.record_recall(memory_ids, recalled_at=recalled_at)

        def rollback_after_turn(self, session_id, turn_seq, *, protected_turn_seqs=()):
            return inner.rollback_after_turn(session_id, turn_seq, protected_turn_seqs=protected_turn_seqs)

        def set_pinned(self, memory_id, pinned):
            return inner.set_pinned(memory_id, pinned)

        def delete(self, memory_id):
            return inner.delete(memory_id)

    engine = HybridMemoryEngine(repo=_NoCountRepo(), embedder=embedder)
    monkeypatch.delenv("SHINSEKAI_MEMORY_SERVICE_URL", raising=False)
    monkeypatch.setattr(operations, "ensure_mem0", lambda: engine)

    first = operations.memory_list("Alice", limit=2, offset=0)
    last = operations.memory_list("Alice", limit=2, offset=4)
    exported = operations.memory_list_all("Alice", batch_size=2)

    assert [row["id"] for row in first["memories"]] == ["m4", "m3"]
    assert first["total"] == 3  # lower bound signals more pages exist
    assert [row["id"] for row in last["memories"]] == ["m0"]
    assert last["total"] == 5
    assert exported["count"] == 5
    assert exported["total"] == 5
    assert [row["id"] for row in exported["memories"]] == ["m4", "m3", "m2", "m1", "m0"]


def test_memory_list_all_unbounded_by_default_and_preserves_total_when_capped(monkeypatch):
    import inspect

    from ai.memory.backends.in_memory import DeterministicHashEmbedder
    from ai.memory.engine import HybridMemoryEngine
    from core.vector_store.in_memory import InMemoryMemoryRepository
    from sdk.adapters.memory import SCOPE_CHAR_CROSS_SAVE, MemoryRecord

    assert inspect.signature(operations.memory_list_all).parameters["max_items"].default is None

    repo = InMemoryMemoryRepository()
    embedder = DeterministicHashEmbedder(dimensions=64)
    for index in range(7):
        repo.upsert(
            MemoryRecord(
                id=f"m{index}",
                scope=SCOPE_CHAR_CROSS_SAVE,
                owner_id="Alice",
                detail_text=f"Alice memory {index}",
                gist_text=f"Alice memory {index}",
                created_at=100.0 + index,
                embedding=embedder.embed_query(f"Alice memory {index}"),
            )
        )
    engine = HybridMemoryEngine(repo=repo, embedder=embedder)
    monkeypatch.delenv("SHINSEKAI_MEMORY_SERVICE_URL", raising=False)
    monkeypatch.setattr(operations, "ensure_mem0", lambda: engine)

    capped = operations.memory_list_all("Alice", batch_size=2, max_items=4)
    assert capped["count"] == 4
    assert len(capped["memories"]) == 4
    assert capped["total"] == 7

    rows = [{"id": f"p{i}", "memory": f"paged {i}"} for i in range(7)]
    monkeypatch.setattr(
        operations,
        "memory_list",
        lambda character_name=None, *, limit=200, offset=0, **_k: {
            "agentId": character_name,
            "count": len(rows[offset:offset + limit]),
            "memories": rows[offset:offset + limit],
            "total": len(rows),
            "offset": offset,
        },
    )
    paged_capped = operations.memory_list_all("Alice", batch_size=2, max_items=3)
    assert paged_capped["count"] == 3
    assert [row["id"] for row in paged_capped["memories"]] == ["p0", "p1", "p2"]
    assert paged_capped["total"] == 7


def test_memory_list_all_reads_consistent_snapshot_under_lock(monkeypatch):
    import threading
    import time

    from ai.memory.backends.in_memory import DeterministicHashEmbedder
    from ai.memory.engine import HybridMemoryEngine
    from core.vector_store.in_memory import InMemoryMemoryRepository
    from sdk.adapters.memory import SCOPE_CHAR_CROSS_SAVE, MemoryRecord

    inner = InMemoryMemoryRepository()
    embedder = DeterministicHashEmbedder(dimensions=64)
    for index in range(6):
        inner.upsert(
            MemoryRecord(
                id=f"m{index}",
                scope=SCOPE_CHAR_CROSS_SAVE,
                owner_id="Alice",
                detail_text=f"Alice memory {index}",
                gist_text=f"Alice memory {index}",
                created_at=100.0 + index,
                embedding=embedder.embed_query(f"Alice memory {index}"),
            )
        )

    read_inside_lock = threading.Event()
    writer_about_to_lock = threading.Event()
    writer_finished = threading.Event()

    class _SnapshotHookRepo:
        def __init__(self):
            self.list_calls = 0

        def count_memories(self, scope_filter):
            return inner.count_memories(scope_filter)

        def list_by_scope(self, scope_filter, *, limit=200):
            self.list_calls += 1
            read_inside_lock.set()
            assert writer_about_to_lock.wait(timeout=2.0)
            time.sleep(0.02)
            assert not writer_finished.is_set()
            return inner.list_by_scope(scope_filter, limit=limit)

        def delete(self, memory_id):
            return inner.delete(memory_id)

    hook_repo = _SnapshotHookRepo()
    engine = HybridMemoryEngine(repo=hook_repo, embedder=embedder)
    monkeypatch.delenv("SHINSEKAI_MEMORY_SERVICE_URL", raising=False)
    monkeypatch.setattr(operations, "ensure_mem0", lambda: engine)

    def _concurrent_delete():
        assert read_inside_lock.wait(timeout=2.0)
        writer_about_to_lock.set()
        operations.memory_forget("m5")
        writer_finished.set()

    worker = threading.Thread(target=_concurrent_delete)
    worker.start()
    result = operations.memory_list_all("Alice", batch_size=2)
    worker.join(timeout=2.0)

    assert writer_finished.is_set()
    assert hook_repo.list_calls == 1
    assert result["count"] == 6
    assert [row["id"] for row in result["memories"]] == ["m5", "m4", "m3", "m2", "m1", "m0"]
