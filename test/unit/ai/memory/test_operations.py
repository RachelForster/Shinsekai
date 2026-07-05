from __future__ import annotations

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


def test_memory_list_normalizes_rows(monkeypatch):
    monkeypatch.delenv("SHINSEKAI_MEMORY_SERVICE_URL", raising=False)
    monkeypatch.setattr(operations, "get_mem0", lambda: _FakeMemory())

    result = operations.memory_list("Alice")

    assert result == {
        "agentId": "Alice",
        "count": 3,
        "memories": [
            {"id": "1", "memory": "likes tea"},
            {"id": "2", "memory": "likes books"},
            {"id": "", "memory": "loose row"},
        ],
    }


def test_local_memory_operations_are_serialized(monkeypatch):
    lock = _RecordingLock()
    memory = _LockedFakeMemory(lock)
    monkeypatch.delenv("SHINSEKAI_MEMORY_SERVICE_URL", raising=False)
    monkeypatch.setattr(operations, "_mem0_operation_lock", lock)
    monkeypatch.setattr(operations, "get_mem0", lambda: memory)
    monkeypatch.setattr(operations, "ensure_mem0", lambda: memory)

    assert operations.memory_list("Alice")["count"] == 0
    assert operations.memory_search("tea", character_name="Alice")["count"] == 0
    assert operations.memory_remember("tea", character_name="Alice")["ok"] is True
    assert operations.memory_forget("mem-1")["ok"] is True
    assert lock.enter_count == 4


def test_memory_remember_and_list_rejects_empty_content():
    assert operations.memory_remember_and_list("  ", character_name="Alice") == {
        "error": "memory content is required"
    }


def test_memory_forget_and_list_rejects_empty_id():
    assert operations.memory_forget_and_list("  ", character_name="Alice") == {
        "error": "memory id is required"
    }


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


def test_memory_service_loading_starts_ready_monitor(monkeypatch):
    started = []

    def fake_urlopen(_request, timeout):
        return _FakeHttpResponse({"status": "loading", "message": "loading"})

    monkeypatch.setenv("SHINSEKAI_MEMORY_SERVICE_URL", "http://127.0.0.1:8787/api/memory")
    monkeypatch.setattr(operations.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(operations, "_start_memory_service_ready_monitor", lambda: started.append(True))

    assert operations.memory_search("tea", character_name="Alice") == {"status": "loading", "message": "loading"}
    assert started == [True]


def test_memory_service_owner_skips_proxy(monkeypatch):
    monkeypatch.setenv("SHINSEKAI_MEMORY_SERVICE_URL", "http://127.0.0.1:8787/api/memory")
    monkeypatch.setenv("SHINSEKAI_MEMORY_SERVICE_OWNER", "1")
    monkeypatch.setattr(operations, "get_mem0", lambda: _FakeMemory())

    result = operations.memory_list("Alice")

    assert result["count"] == 3


def test_memory_remember_and_list_preserves_loading_result(monkeypatch):
    monkeypatch.setattr(
        operations,
        "memory_remember",
        lambda _text, character_name=None: {"status": "loading", "message": "loading"},
    )
    monkeypatch.setattr(
        operations,
        "memory_list",
        lambda character_name=None: (_ for _ in ()).throw(AssertionError("should not list while loading")),
    )

    assert operations.memory_remember_and_list("tea", character_name="Alice") == {
        "status": "loading",
        "message": "loading",
    }
