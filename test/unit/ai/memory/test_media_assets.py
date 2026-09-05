from __future__ import annotations

from ai.memory import media_assets


class _FakeMemory:
    def __init__(self) -> None:
        self.added = []
        self.filters = None

    def get_all(self, *, filters, top_k=20):
        return {"results": []}

    def add(self, text, **kwargs):
        self.added.append((text, kwargs))
        return {"results": [{"id": str(len(self.added))}]}

    def search(self, query, *, filters, top_k=20):
        self.filters = filters
        return {
            "results": [
                {"metadata": {"asset_id": "2"}, "score": 0.88},
                {"metadata": {"asset_id": "1"}, "score": 0.51},
            ]
        }


def test_local_media_search_indexes_raw_tags_and_returns_asset_ids(monkeypatch):
    memory = _FakeMemory()
    monkeypatch.setattr(media_assets, "ensure_mem0", lambda: memory)

    matches = media_assets._local_search(
        scope="sprite:Alice",
        vibe="angry",
        candidates=[
            {"asset_id": "1", "path": "calm.png", "tags": "calm"},
            {"asset_id": "2", "path": "angry.png", "tags": "angry"},
        ],
        limit=2,
    )

    assert matches == [
        {"asset_id": "2", "score": 0.88},
        {"asset_id": "1", "score": 0.51},
    ]
    assert [entry[0] for entry in memory.added] == ["calm", "angry"]
    assert all(entry[1]["infer"] is False for entry in memory.added)
    assert memory.filters["user_id"] == "__shinsekai_media__:sprite:alice"
    assert memory.filters["agent_id"] == "semantic-media"
    assert memory.filters["run_id"]


def test_media_search_uses_owner_service_when_configured(monkeypatch):
    monkeypatch.setattr(
        media_assets,
        "_memory_service_request",
        lambda endpoint, payload: {
            "matches": [{"asset_id": "4", "score": 0.9}],
            "endpoint": endpoint,
        },
    )
    monkeypatch.setattr(
        media_assets,
        "_local_search",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("local search should not run")),
    )

    matches = media_assets.search_media_assets(
        scope="bgm:school",
        vibe="tense",
        candidates=[{"asset_id": "4", "path": "tense.mp3", "tags": "tense"}],
    )

    assert matches == [{"asset_id": "4", "score": 0.9}]
