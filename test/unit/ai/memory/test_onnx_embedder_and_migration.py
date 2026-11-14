"""Unit tests for OnnxMiniLmEmbedder, pure Unigram tokenizer, and Qdrant SQLite migration."""

from __future__ import annotations

import io
import json
from pathlib import Path
import pickle
import sqlite3
from types import SimpleNamespace
import numpy as np
import pytest

from ai.memory.backends.onnx_embedder import (
    OnnxMiniLmEmbedder,
    _PureUnigramTokenizer,
    find_onnx_model_file,
)
from ai.memory.backends.sqlite_repo import SqliteHybridMemoryRepo
from ai.memory.migration import (
    _QdrantSafeUnpickler,
    migrate_legacy_knowledge_qdrant,
    migrate_legacy_memory_qdrant,
)
from core.vector_store.sqlite_hybrid_store import SqliteHybridStore
from sdk.adapters.memory import (
    NAMESPACE_KNOWLEDGE,
    SCOPE_CHAR_CROSS_SAVE,
    SCOPE_SELF_PUBLIC,
    MemoryScopeFilter,
)


def _write_sample_tokenizer_json(snapshot: Path) -> Path:
    snapshot.mkdir(parents=True, exist_ok=True)
    vocab = [
        ["<s>", 0.0],
        ["<pad>", 0.0],
        ["</s>", 0.0],
        ["<unk>", 0.0],
        ["\u2581hello", -1.0],
        ["\u2581world", -1.2],
        ["\u2581", -0.5],
        ["希", -1.5],
        ["望", -1.5],
        ["希望", -0.8],
        ["红", -1.4],
        ["茶", -1.4],
        ["红茶", -0.7],
    ]
    path = snapshot / "tokenizer.json"
    path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "model": {
                    "unk_id": 3,
                    "vocab": vocab,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


class _FakeOnnxSession:
    def __init__(self, *, dims: int = 8, include_token_type_ids: bool = True) -> None:
        self.dims = dims
        self.calls: list[dict[str, np.ndarray]] = []
        names = ["input_ids", "attention_mask"]
        if include_token_type_ids:
            names.append("token_type_ids")
        self._inputs = [SimpleNamespace(name=n) for n in names]

    def get_inputs(self):
        return self._inputs

    def run(self, _output_names, feeds):
        self.calls.append(feeds)
        input_ids = feeds["input_ids"]
        batch_size, seq_len = input_ids.shape
        hidden = np.zeros((batch_size, seq_len, self.dims), dtype=np.float32)
        for b in range(batch_size):
            for s in range(seq_len):
                tok = int(input_ids[b, s])
                hidden[b, s, tok % self.dims] = float(tok + 1)
        return [hidden]


def test_pure_unigram_tokenizer_viterbi_and_padding(tmp_path: Path):
    tok_path = _write_sample_tokenizer_json(tmp_path)
    tok = _PureUnigramTokenizer(tok_path, max_length=12)

    input_ids, mask = tok.encode_batch(["hello world", "希望 红茶", ""])
    assert input_ids.shape == mask.shape
    assert input_ids.shape[0] == 3
    assert input_ids.dtype == np.int64
    assert mask.dtype == np.int64

    # Row 0: <s>, ▁hello, ▁world, </s> -> 4 active tokens
    assert list(input_ids[0, :4]) == [0, 4, 5, 2]
    assert list(mask[0, :4]) == [1, 1, 1, 1]

    # Row 1 prefers merged piece "希望" (score -0.8 > -3.0) and "红茶" (score -0.7 > -2.8)
    active_row1 = list(input_ids[1][mask[1] == 1])
    assert 9 in active_row1  # "希望"
    assert 12 in active_row1  # "红茶"

    # Empty string still has BOS + EOS
    assert list(input_ids[2, :2]) == [0, 2]
    assert int(mask[2].sum()) == 2


def test_onnx_minilm_embedder_mean_pooling_l2_norm_and_lru_cache(tmp_path: Path):
    tok_path = _write_sample_tokenizer_json(tmp_path)
    tokenizer = _PureUnigramTokenizer(tok_path, max_length=16)
    session = _FakeOnnxSession(dims=8, include_token_type_ids=True)

    embedder = OnnxMiniLmEmbedder(
        tmp_path,
        dimensions=8,
        query_cache_size=4,
        session=session,
        tokenizer=tokenizer,
    )
    assert embedder.dimensions == 8
    assert embedder.status().state == "ready"

    v1 = embedder.embed_query("hello world")
    assert v1.shape == (8,)
    assert v1.dtype == np.float32
    assert np.isclose(np.linalg.norm(v1), 1.0, atol=1e-5)
    assert len(session.calls) == 1
    assert "token_type_ids" in session.calls[0]

    # Repeated query hits LRU cache without invoking ONNX session again
    v2 = embedder.embed_query("  hello   world  ")
    assert len(session.calls) == 1
    assert np.allclose(v1, v2)

    docs = embedder.embed_documents(["hello", "希望", "红茶"], batch_size=2)
    assert docs.shape == (3, 8)
    assert np.allclose(np.linalg.norm(docs, axis=1), 1.0, atol=1e-5)


def test_find_onnx_model_file_prefers_quantized_graph(tmp_path: Path):
    (tmp_path / "onnx").mkdir()
    (tmp_path / "onnx" / "model.onnx").write_bytes(b"\x08" + b"\x00" * 31)
    assert find_onnx_model_file(tmp_path) == tmp_path / "onnx" / "model.onnx"

    (tmp_path / "onnx" / "model_quantized.onnx").write_bytes(b"\x08" + b"\x00" * 31)
    assert find_onnx_model_file(tmp_path) == tmp_path / "onnx" / "model_quantized.onnx"


def _write_qdrant_points_sqlite(sqlite_path: Path, rows: list[tuple[str, object]]) -> None:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(sqlite_path))
    try:
        conn.execute("CREATE TABLE points (id TEXT PRIMARY KEY, point BLOB)")
        for pid, obj in rows:
            conn.execute("INSERT INTO points(id, point) VALUES (?, ?)", (pid, pickle.dumps(obj)))
        conn.commit()
    finally:
        conn.close()


def test_legacy_qdrant_memory_and_knowledge_migration_zero_qdrant_client(tmp_path: Path):
    mem_qdrant = tmp_path / "data" / "memory" / "qdrant"
    mem_sqlite = (
        mem_qdrant
        / "collection"
        / "character_memories_multilingual_minilm"
        / "storage.sqlite"
    )
    vec_a = [1.0] + [0.0] * 383
    vec_b = [0.0, 1.0] + [0.0] * 382

    # Simulate Pydantic v2 PointStruct pickled state dict with vector={"": [384 floats]}
    point_char = {
        "id": "pt-char-1",
        "vector": {"": vec_a},
        "payload": {
            "user_id": "狛枝凪斗",
            "data": "狛枝凪斗相信绝对的希望",
            "created_at": "2026-05-01T12:00:00Z",
        },
    }
    point_user = {
        "id": "pt-user-1",
        "vector": {"": vec_b},
        "payload": {
            "user_id": "user",
            "data": "用户正在学习日语",
            "created_at": "2026-05-02T08:30:00Z",
        },
    }
    point_media = {
        "id": "pt-media-skip",
        "vector": {"": vec_a},
        "payload": {
            "user_id": "__shinsekai_media__:sprite:nagito",
            "agent_id": "semantic-media",
            "data": "calm smile",
        },
    }
    _write_qdrant_points_sqlite(
        mem_sqlite,
        [
            ("pt-char-1", point_char),
            ("pt-user-1", point_user),
            ("pt-media-skip", point_media),
        ],
    )

    store = SqliteHybridStore(tmp_path / "migrated_memory.db")
    repo = SqliteHybridMemoryRepo(store)
    try:
        migrated = migrate_legacy_memory_qdrant(mem_qdrant, repo, meta_store=store, expected_dims=384)
        assert migrated == 2

        # Second call is a fast no-op thanks to store_meta marker
        assert migrate_legacy_memory_qdrant(mem_qdrant, repo, meta_store=store, expected_dims=384) == 0

        char_rec = repo.get("pt-char-1")
        assert char_rec is not None
        assert char_rec.scope == SCOPE_CHAR_CROSS_SAVE
        assert char_rec.owner_id == "狛枝凪斗"
        assert char_rec.detail_text == "狛枝凪斗相信绝对的希望"
        assert char_rec.embedding is not None and char_rec.embedding.shape == (384,)

        self_recs = repo.list_by_scope(MemoryScopeFilter(scopes=(SCOPE_SELF_PUBLIC,)))
        assert [r.id for r in self_recs] == ["pt-user-1"]
        assert repo.get("pt-media-skip") is None
    finally:
        store.close()

    # Knowledge migration check
    kb_qdrant = tmp_path / "data" / "knowledge" / "qdrant"
    kb_sqlite = (
        kb_qdrant
        / "collection"
        / "character_knowledge_settings_rag_minilm"
        / "storage.sqlite"
    )
    _write_qdrant_points_sqlite(
        kb_sqlite,
        [
            (
                "kb-1",
                {
                    "id": "kb-1",
                    "vector": {"": vec_a},
                    "payload": {
                        "user_id": "hope_peak",
                        "data": "希望峰学园是由政府公认的特权学园",
                    },
                },
            )
        ],
    )
    kb_store = SqliteHybridStore(tmp_path / "migrated_kb.db")
    try:
        assert migrate_legacy_knowledge_qdrant(kb_qdrant, kb_store, meta_store=kb_store) == 1
        assert migrate_legacy_knowledge_qdrant(kb_qdrant, kb_store, meta_store=kb_store) == 0
        assert dict(kb_store.count_by_scope(namespace=NAMESPACE_KNOWLEDGE)) == {"hope_peak": 1}
    finally:
        kb_store.close()


def test_qdrant_safe_unpickler_blocks_arbitrary_code_execution():
    # Craft a raw pickle stream attempting to resolve os.system
    malicious_stream = b"cos\nsystem\n(S'echo pwned'\ntR."
    with pytest.raises(pickle.UnpicklingError, match="Blocked unsafe pickle import"):
        _QdrantSafeUnpickler(io.BytesIO(malicious_stream)).load()
