"""Unit tests for OnnxMiniLmEmbedder, pure Unigram tokenizer, and Qdrant SQLite migration."""

from __future__ import annotations

from collections import OrderedDict
import datetime as dt
import io
import json
from pathlib import Path
import pickle
import sqlite3
import sys
import types
from types import SimpleNamespace
import uuid

import numpy as np
import pytest

from ai.memory.backends.onnx_embedder import (
    OnnxMiniLmEmbedder,
    _PureUnigramTokenizer,
    find_onnx_model_file,
)
from ai.memory.backends.sqlite_repo import SqliteHybridMemoryRepo
from ai.memory.migration import (
    LegacyQdrantDecodeError,
    LegacyQdrantReadError,
    UnsafeLegacyQdrantDataError,
    _QdrantSafeUnpickler,
    decode_legacy_qdrant_point,
    get_knowledge_migration_status,
    get_memory_migration_status,
    iter_legacy_qdrant_points,
    migrate_legacy_knowledge_qdrant,
    migrate_legacy_knowledge_qdrant_explicit,
    migrate_legacy_memory_qdrant,
    migrate_legacy_memory_qdrant_explicit,
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


def _serialize_authentic_qdrant_point(
    *,
    point_id: str | int | uuid.UUID,
    vector: object,
    payload: dict[str, object] | None,
    sparse_bm25: tuple[list[int], list[float]] | None = None,
    protocol: int = 4,
) -> bytes:
    """Build a genuine Pydantic-v2-layout ``qdrant_client.http.models.models.PointStruct`` pickle."""
    mod_names = (
        "qdrant_client",
        "qdrant_client.http",
        "qdrant_client.http.models",
        "qdrant_client.http.models.models",
    )
    saved = {name: sys.modules.get(name) for name in mod_names}
    try:
        pkg_root = types.ModuleType("qdrant_client")
        pkg_http = types.ModuleType("qdrant_client.http")
        pkg_models = types.ModuleType("qdrant_client.http.models")
        mod = types.ModuleType("qdrant_client.http.models.models")

        class SparseVector:
            def __init__(self, indices: list[int], values: list[float]) -> None:
                self._indices = indices
                self._values = values

            def __getstate__(self):
                return {
                    "__dict__": {"indices": self._indices, "values": self._values},
                    "__pydantic_extra__": None,
                    "__pydantic_fields_set__": {"indices", "values"},
                    "__pydantic_private__": None,
                }

        class PointStruct:
            def __init__(self, pid, vec, pl) -> None:
                self._id = pid
                self._vec = vec
                self._pl = pl

            def __getstate__(self):
                return {
                    "__dict__": {
                        "id": self._id,
                        "vector": self._vec,
                        "payload": self._pl,
                        "shard_key": None,
                        "order_value": None,
                    },
                    "__pydantic_extra__": None,
                    "__pydantic_fields_set__": {"id", "vector", "payload"},
                    "__pydantic_private__": None,
                }

        SparseVector.__module__ = "qdrant_client.http.models.models"
        SparseVector.__qualname__ = "SparseVector"
        PointStruct.__module__ = "qdrant_client.http.models.models"
        PointStruct.__qualname__ = "PointStruct"
        mod.SparseVector = SparseVector
        mod.PointStruct = PointStruct

        sys.modules["qdrant_client"] = pkg_root
        sys.modules["qdrant_client.http"] = pkg_http
        sys.modules["qdrant_client.http.models"] = pkg_models
        sys.modules["qdrant_client.http.models.models"] = mod

        final_vec = vector
        if sparse_bm25 is not None and isinstance(vector, dict):
            final_vec = {
                **vector,
                "bm25": SparseVector(sparse_bm25[0], sparse_bm25[1]),
            }
        return pickle.dumps(PointStruct(point_id, final_vec, payload), protocol=protocol)
    finally:
        for name, prev in saved.items():
            if prev is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prev


def _write_qdrant_raw_blobs_sqlite(sqlite_path: Path, rows: list[tuple[str, bytes]]) -> None:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(sqlite_path))
    try:
        conn.execute("CREATE TABLE points (id TEXT PRIMARY KEY, point BLOB)")
        for pid, blob in rows:
            conn.execute("INSERT INTO points(id, point) VALUES (?, ?)", (pid, blob))
        conn.commit()
    finally:
        conn.close()


def test_pure_unigram_tokenizer_viterbi_and_padding(tmp_path: Path):
    tok_path = _write_sample_tokenizer_json(tmp_path)
    tok = _PureUnigramTokenizer(tok_path, max_length=12)

    input_ids, mask = tok.encode_batch(["hello world", "希望 红茶", ""])
    assert input_ids.shape == mask.shape
    assert input_ids.shape[0] == 3
    assert input_ids.dtype == np.int64
    assert mask.dtype == np.int64

    assert list(input_ids[0, :4]) == [0, 4, 5, 2]
    assert list(mask[0, :4]) == [1, 1, 1, 1]

    active_row1 = list(input_ids[1][mask[1] == 1])
    assert 9 in active_row1  # "希望"
    assert 12 in active_row1  # "红茶"

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


def test_legacy_qdrant_migration_decodes_authentic_point_struct_and_sparse_vectors(tmp_path: Path):
    mem_qdrant = tmp_path / "data" / "memory" / "qdrant"
    mem_sqlite = (
        mem_qdrant
        / "collection"
        / "character_memories_multilingual_minilm"
        / "storage.sqlite"
    )
    vec_a = [1.0] + [0.0] * 383
    vec_b = [0.0, 1.0] + [0.0] * 382
    uuid_user = uuid.UUID("12345678-1234-5678-1234-567812345678")

    blob_char = _serialize_authentic_qdrant_point(
        point_id="pt-char-1",
        vector={"": vec_a},
        sparse_bm25=([3, 19], [1.45, 0.72]),
        payload={
            "user_id": "狛枝凪斗",
            "data": "狛枝凪斗相信绝对的希望",
            "created_at": "2026-05-01T12:00:00Z",
        },
        protocol=4,
    )
    blob_user = _serialize_authentic_qdrant_point(
        point_id=uuid_user,
        vector={"": vec_b},
        payload={
            "user_id": "user",
            "data": "用户正在学习日语",
            "created_at": dt.datetime(2026, 5, 2, 8, 30, tzinfo=dt.timezone.utc),
        },
        protocol=3,  # exercises builtins.set in __pydantic_fields_set__
    )
    blob_media = _serialize_authentic_qdrant_point(
        point_id="pt-media-skip",
        vector={"": vec_a},
        payload={
            "user_id": "__shinsekai_media__:sprite:nagito",
            "agent_id": "semantic-media",
            "data": "calm smile",
        },
    )
    assert "qdrant_client" not in sys.modules

    _write_qdrant_raw_blobs_sqlite(
        mem_sqlite,
        [
            ("pt-char-1", blob_char),
            (str(uuid_user), blob_user),
            ("pt-media-skip", blob_media),
        ],
    )

    store = SqliteHybridStore(tmp_path / "migrated_memory.db")
    repo = SqliteHybridMemoryRepo(store)
    try:
        migrated = migrate_legacy_memory_qdrant(mem_qdrant, repo, meta_store=store, expected_dims=384)
        assert migrated == 2
        status = get_memory_migration_status(store)
        assert status["completed"] is True
        assert status["retryable"] is False
        assert status["status"] == "completed"

        assert migrate_legacy_memory_qdrant(mem_qdrant, repo, meta_store=store, expected_dims=384) == 0

        char_rec = repo.get("pt-char-1")
        assert char_rec is not None
        assert char_rec.scope == SCOPE_CHAR_CROSS_SAVE
        assert char_rec.owner_id == "狛枝凪斗"
        assert char_rec.detail_text == "狛枝凪斗相信绝对的希望"
        assert char_rec.embedding is not None and char_rec.embedding.shape == (384,)

        self_recs = repo.list_by_scope(MemoryScopeFilter(scopes=(SCOPE_SELF_PUBLIC,)))
        assert [r.id for r in self_recs] == [str(uuid_user)]
        assert repo.get("pt-media-skip") is None
    finally:
        store.close()

    kb_qdrant = tmp_path / "data" / "knowledge" / "qdrant"
    kb_sqlite = (
        kb_qdrant
        / "collection"
        / "character_knowledge_settings_rag_minilm"
        / "storage.sqlite"
    )
    blob_kb = _serialize_authentic_qdrant_point(
        point_id="kb-1",
        vector=vec_a,
        payload={
            "user_id": "hope_peak",
            "data": "希望峰学园是由政府公认的特权学园",
        },
    )
    _write_qdrant_raw_blobs_sqlite(kb_sqlite, [("kb-1", blob_kb)])

    kb_store = SqliteHybridStore(tmp_path / "migrated_kb.db")
    try:
        assert migrate_legacy_knowledge_qdrant(kb_qdrant, kb_store, meta_store=kb_store) == 1
        assert get_knowledge_migration_status(kb_store)["completed"] is True
        assert migrate_legacy_knowledge_qdrant(kb_qdrant, kb_store, meta_store=kb_store) == 0
        assert dict(kb_store.count_by_scope(namespace=NAMESPACE_KNOWLEDGE)) == {"hope_peak": 1}
    finally:
        kb_store.close()


@pytest.mark.parametrize(
    ("label", "stream"),
    [
        ("os.system", b"cos\nsystem\n(S'echo pwned'\ntR."),
        ("builtins.eval", b"cbuiltins\neval\n(S'1+1'\ntR."),
        ("builtins.getattr", b"cbuiltins\ngetattr\n(cbuiltins\nstr\nS'upper'\ntR."),
        ("collections.OrderedDict", pickle.dumps(OrderedDict([("id", "x")]), protocol=4)),
        ("numpy.ndarray", pickle.dumps({"id": "x", "vector": np.ones(4, dtype=np.float32), "payload": {}}, protocol=4)),
        ("qdrant_client.OtherClass", b"cqdrant_client.qdrant_client\nQdrantClient\n)R."),
        ("pydantic.BaseModel", b"cpydantic.main\nBaseModel\n)R."),
    ],
)
def test_qdrant_safe_unpickler_strictly_rejects_unapproved_globals(label: str, stream: bytes):
    with pytest.raises(UnsafeLegacyQdrantDataError, match="Blocked unsupported pickle global"):
        _QdrantSafeUnpickler(io.BytesIO(stream)).load()


def test_explicit_trusted_migration_requires_opt_in_and_still_blocks_code_execution(tmp_path: Path):
    mem_qdrant = tmp_path / "trusted_qdrant"
    mem_sqlite = mem_qdrant / "collection" / "character_memories" / "storage.sqlite"
    np_point = {
        "id": "np-1",
        "vector": np.array([1.0] + [0.0] * 383, dtype=np.float32),
        "payload": OrderedDict([("user_id", "Alice"), ("data", "使用旧版 numpy 向量的条目")]),
    }
    _write_qdrant_raw_blobs_sqlite(mem_sqlite, [("np-1", pickle.dumps(np_point, protocol=4))])

    store = SqliteHybridStore(tmp_path / "explicit_mem.db")
    repo = SqliteHybridMemoryRepo(store)
    try:
        # Automatic startup migration refuses numpy/OrderedDict globals and stays retryable
        assert migrate_legacy_memory_qdrant(mem_qdrant, repo, meta_store=store) == 0
        auto_status = get_memory_migration_status(store)
        assert auto_status["completed"] is False
        assert auto_status["retryable"] is True
        assert "Blocked unsupported pickle global" in auto_status["reason"]

        # Explicit migration without trusted_source=True must fail closed
        with pytest.raises(PermissionError, match="trusted_source=True"):
            migrate_legacy_memory_qdrant_explicit(
                mem_qdrant, repo, meta_store=store, trusted_source=False
            )

        # Explicit user-confirmed trusted migration imports the numpy/OrderedDict archive cleanly
        assert (
            migrate_legacy_memory_qdrant_explicit(
                mem_qdrant, repo, meta_store=store, trusted_source=True
            )
            == 1
        )
        assert get_memory_migration_status(store)["completed"] is True
        assert repo.get("np-1") is not None

        # Even trusted_source=True still rejects arbitrary execution globals
        with pytest.raises(UnsafeLegacyQdrantDataError):
            decode_legacy_qdrant_point(b"cos\nsystem\n(S'id'\ntR.", trusted_source=True)
    finally:
        store.close()


def test_empty_legacy_qdrant_db_marks_completed_while_read_failure_raises_in_reader(tmp_path: Path):
    empty_qdrant = tmp_path / "empty_qdrant"
    empty_sqlite = empty_qdrant / "collection" / "character_memories" / "storage.sqlite"
    _write_qdrant_raw_blobs_sqlite(empty_sqlite, [])

    store = SqliteHybridStore(tmp_path / "empty_target.db")
    repo = SqliteHybridMemoryRepo(store)
    try:
        assert migrate_legacy_memory_qdrant(empty_qdrant, repo, meta_store=store) == 0
        status = get_memory_migration_status(store)
        assert status["completed"] is True
        assert status["empty_source"] is True
        assert status["reason"] == ""
    finally:
        store.close()

    corrupt_sqlite = tmp_path / "corrupt" / "storage.sqlite"
    corrupt_sqlite.parent.mkdir(parents=True)
    corrupt_sqlite.write_bytes(b"not-a-valid-sqlite-header")
    with pytest.raises(LegacyQdrantReadError):
        iter_legacy_qdrant_points(corrupt_sqlite)


def test_memory_migration_retries_after_initial_read_or_partial_failure_without_duplicates(
    tmp_path: Path,
):
    mem_qdrant = tmp_path / "mem_retry_qdrant"
    mem_sqlite = mem_qdrant / "collection" / "character_memories" / "storage.sqlite"
    mem_sqlite.parent.mkdir(parents=True, exist_ok=True)
    # Step 1: Corrupt / unreadable SQLite file on first startup
    mem_sqlite.write_bytes(b"corrupted-sqlite-bytes")

    store = SqliteHybridStore(tmp_path / "mem_retry.db")
    repo = SqliteHybridMemoryRepo(store)
    vec = [1.0] + [0.0] * 383
    try:
        assert migrate_legacy_memory_qdrant(mem_qdrant, repo, meta_store=store) == 0
        first_status = get_memory_migration_status(store)
        assert first_status["completed"] is False
        assert first_status["retryable"] is True
        assert first_status["status"] == "read_failed"
        assert first_status["reason"] != ""

        # Step 2: Partial decode error (1 valid point + 1 corrupted blob) -> imports valid, stays retryable
        mem_sqlite.unlink()
        valid_blob_1 = _serialize_authentic_qdrant_point(
            point_id="mem-1",
            vector={"": vec},
            payload={"user_id": "Alice", "data": "爱丽丝的第一条旧记忆"},
        )
        _write_qdrant_raw_blobs_sqlite(
            mem_sqlite,
            [("mem-1", valid_blob_1), ("mem-2", b"truncated-corrupt-pickle")],
        )
        assert migrate_legacy_memory_qdrant(mem_qdrant, repo, meta_store=store) == 1
        partial_status = get_memory_migration_status(store)
        assert partial_status["completed"] is False
        assert partial_status["retryable"] is True
        assert partial_status["status"] == "partial_error"
        assert "mem-2" in partial_status["reason"]

        # Step 3: Restore clean SQLite DB containing both mem-1 and mem-2 -> retry imports mem-2 without duplicating mem-1
        mem_sqlite.unlink()
        valid_blob_2 = _serialize_authentic_qdrant_point(
            point_id="mem-2",
            vector={"": vec},
            payload={"user_id": "Alice", "data": "爱丽丝的第二条旧记忆"},
        )
        _write_qdrant_raw_blobs_sqlite(
            mem_sqlite,
            [("mem-1", valid_blob_1), ("mem-2", valid_blob_2)],
        )
        assert migrate_legacy_memory_qdrant(mem_qdrant, repo, meta_store=store) == 1
        final_status = get_memory_migration_status(store)
        assert final_status["completed"] is True
        assert final_status["retryable"] is False
        assert final_status["reason"] == ""

        # Step 4: Running again (both with meta_store and without meta_store) never creates duplicates
        assert migrate_legacy_memory_qdrant(mem_qdrant, repo, meta_store=store) == 0
        assert migrate_legacy_memory_qdrant(mem_qdrant, repo, meta_store=None) == 0
        records = repo.list_by_scope(
            MemoryScopeFilter(scopes=(SCOPE_CHAR_CROSS_SAVE,), owner_ids=("Alice",))
        )
        assert sorted(r.id for r in records) == ["mem-1", "mem-2"]
    finally:
        store.close()


def test_knowledge_migration_retries_after_initial_read_or_partial_failure_without_duplicates(
    tmp_path: Path,
):
    kb_qdrant = tmp_path / "kb_retry_qdrant"
    kb_sqlite = (
        kb_qdrant
        / "collection"
        / "character_knowledge_settings_rag_minilm"
        / "storage.sqlite"
    )
    kb_sqlite.parent.mkdir(parents=True, exist_ok=True)
    # Step 1: 0-byte SQLite file missing `points` table on first startup
    kb_sqlite.write_bytes(b"")

    kb_store = SqliteHybridStore(tmp_path / "kb_retry.db")
    vec = [0.0, 1.0] + [0.0] * 382
    try:
        assert migrate_legacy_knowledge_qdrant(kb_qdrant, kb_store, meta_store=kb_store) == 0
        first_status = get_knowledge_migration_status(kb_store)
        assert first_status["completed"] is False
        assert first_status["retryable"] is True
        assert first_status["status"] == "read_failed"
        assert "points" in first_status["reason"]

        # Step 2: Partial decode failure (1 valid slice + 1 undecodable slice)
        kb_sqlite.unlink()
        kb_blob_1 = _serialize_authentic_qdrant_point(
            point_id="slice-1",
            vector={"": vec},
            payload={"user_id": "lore_world", "data": "世界观设定第一条"},
        )
        _write_qdrant_raw_blobs_sqlite(
            kb_sqlite,
            [("slice-1", kb_blob_1), ("slice-2", b"cos\nsystem\n(S'nope'\ntR.")],
        )
        assert migrate_legacy_knowledge_qdrant(kb_qdrant, kb_store, meta_store=kb_store) == 1
        partial_status = get_knowledge_migration_status(kb_store)
        assert partial_status["completed"] is False
        assert partial_status["retryable"] is True
        assert partial_status["status"] == "partial_error"
        assert "Blocked unsupported pickle global" in partial_status["reason"]

        # Step 3: Restore valid SQLite DB with slice-1 and slice-2 -> retry imports only slice-2 and marks completed
        kb_sqlite.unlink()
        kb_blob_2 = _serialize_authentic_qdrant_point(
            point_id="slice-2",
            vector={"": vec},
            payload={"user_id": "lore_world", "data": "世界观设定第二条"},
        )
        _write_qdrant_raw_blobs_sqlite(
            kb_sqlite,
            [("slice-1", kb_blob_1), ("slice-2", kb_blob_2)],
        )
        assert migrate_legacy_knowledge_qdrant(kb_qdrant, kb_store, meta_store=kb_store) == 1
        final_status = get_knowledge_migration_status(kb_store)
        assert final_status["completed"] is True
        assert final_status["retryable"] is False
        assert final_status["reason"] == ""

        # Step 4: Subsequent calls (with or without meta_store) produce zero duplicates
        assert migrate_legacy_knowledge_qdrant(kb_qdrant, kb_store, meta_store=kb_store) == 0
        assert migrate_legacy_knowledge_qdrant(kb_qdrant, kb_store, meta_store=None) == 0
        slices = kb_store.list_slices(namespace=NAMESPACE_KNOWLEDGE, scope_id="lore_world")
        assert sorted(s.id for s in slices) == ["slice-1", "slice-2"]
    finally:
        kb_store.close()
