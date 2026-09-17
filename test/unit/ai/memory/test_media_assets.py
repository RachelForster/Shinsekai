from __future__ import annotations

import pytest

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


class _StatefulMemory:
    def __init__(self) -> None:
        self.rows = []

    def get_all(self, *, filters, top_k=20):
        matches = []
        for _text, kwargs in self.rows:
            if all(kwargs.get(key) == value for key, value in filters.items()):
                matches.append({"metadata": kwargs["metadata"]})
        return {"results": matches[:top_k]}

    def add(self, text, **kwargs):
        self.rows.append((text, kwargs))
        return {"results": [{"id": str(len(self.rows))}]}

    def search(self, query, *, filters, top_k=20):
        matches = [
            {"metadata": kwargs["metadata"], "score": 1.0}
            for text, kwargs in self.rows
            if text == query
            and all(kwargs.get(key) == value for key, value in filters.items())
        ]
        return {"results": matches[:top_k]}


class _LegacyStatefulMemory(_StatefulMemory):
    def get_all(self, *, filters, limit=20):
        return super().get_all(filters=filters, top_k=limit)

    def search(self, query, *, filters, limit=20):
        return super().search(query, filters=filters, top_k=limit)


def _candidates(count):
    return [
        {"asset_id": str(index), "path": f"{index}.png", "tags": f"expression {index}"}
        for index in range(1, count + 1)
    ]


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


@pytest.mark.parametrize("memory_type", [_StatefulMemory, _LegacyStatefulMemory])
@pytest.mark.parametrize("asset_count", [2, 501, 1200])
def test_local_catalog_index_is_idempotent(monkeypatch, memory_type, asset_count):
    memory = memory_type()
    monkeypatch.setattr(media_assets, "ensure_mem0", lambda: memory)
    catalogs = [
        {
            "scope": "sprite:Alice",
            "candidates": _candidates(asset_count),
        }
    ]

    first = media_assets._local_index_catalogs(catalogs)
    second = media_assets._local_index_catalogs(catalogs)

    assert first == {"catalogCount": 1, "assetCount": asset_count, "addedCount": asset_count}
    assert second == {"catalogCount": 1, "assetCount": asset_count, "addedCount": 0}
    assert len(memory.rows) == asset_count


@pytest.mark.parametrize("memory_type", [_StatefulMemory, _LegacyStatefulMemory])
@pytest.mark.parametrize("use_owner_service", [False, True])
def test_large_catalog_search_can_match_last_asset(
    monkeypatch, memory_type, use_owner_service
):
    memory = memory_type()
    monkeypatch.setattr(media_assets, "ensure_mem0", lambda: memory)
    endpoints = {
        "asset-index": media_assets.media_asset_index_response,
        "asset-search": media_assets.media_asset_search_response,
    }
    monkeypatch.setattr(
        media_assets,
        "_memory_service_request",
        lambda endpoint, payload: endpoints[endpoint](payload) if use_owner_service else None,
    )
    candidates = _candidates(1200)

    result = media_assets.ensure_media_asset_indexes(
        [{"scope": "sprite:Alice", "candidates": candidates}]
    )
    matches = media_assets.search_media_assets(
        scope="sprite:Alice", vibe="expression 1200", candidates=candidates
    )

    assert result == {"catalogCount": 1, "assetCount": 1200, "addedCount": 1200}
    assert matches == [{"asset_id": "1200", "score": 1.0}]
    assert len(memory.rows) == 1200


def test_catalog_index_uses_owner_service_when_configured(monkeypatch):
    requests = []

    def request(endpoint, payload):
        requests.append((endpoint, payload))
        return {"catalogCount": 1, "assetCount": 1, "addedCount": 1}

    monkeypatch.setattr(media_assets, "_memory_service_request", request)
    monkeypatch.setattr(
        media_assets,
        "_local_index_catalogs",
        lambda _catalogs: (_ for _ in ()).throw(
            AssertionError("local indexing should not run")
        ),
    )

    result = media_assets.ensure_media_asset_indexes(
        [
            {
                "scope": "bgm:school",
                "candidates": [
                    {"asset_id": "1", "path": "quiet.mp3", "tags": "quiet"}
                ],
            }
        ]
    )

    assert result == {"catalogCount": 1, "assetCount": 1, "addedCount": 1}
    assert requests[0][0] == "asset-index"
    assert requests[0][1]["catalogs"][0]["scope"] == "bgm:school"


def test_catalog_index_rejects_owner_service_error(monkeypatch):
    monkeypatch.setattr(
        media_assets,
        "_memory_service_request",
        lambda _endpoint, _payload: {"status": "loading", "message": "loading mem0"},
    )

    with pytest.raises(RuntimeError, match="loading mem0"):
        media_assets.ensure_media_asset_indexes([])
