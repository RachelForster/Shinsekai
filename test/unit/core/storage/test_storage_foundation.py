"""Unit tests for Phase 1 SOLID storage ports and core/storage infrastructure."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sqlite3
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
import pytest

from core.storage import (
    FileDocumentStore,
    InMemoryCatalogStore,
    InMemoryDocumentStore,
    IndexedColumn,
    NoopUnitOfWork,
    PydanticJsonCodec,
    PydanticYamlCodec,
    SqliteCatalogStore,
    SqliteEngine,
    SqliteMigration,
    StorageHub,
    StorageLayout,
)
from sdk.adapters.storage import (
    BackendStatus,
    CatalogStore,
    Codec,
    DocumentStore,
    ManagedBackend,
    Migratable,
    ReadableCatalog,
    ReadableDocument,
    UnitOfWork,
)


class _SampleDoc(BaseModel):
    model_config = ConfigDict(frozen=False)

    title: str = "default"
    count: int = 0
    tags: list[str] = Field(default_factory=list)


class _CatalogItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    bio: str = ""
    hot_note: str = ""


# ── Protocol Compliance ─────────────────────────────────────────────────────


def test_storage_implementations_satisfy_sdk_protocols(tmp_path: Path) -> None:
    yaml_codec = PydanticYamlCodec(_SampleDoc)
    json_codec = PydanticJsonCodec(_SampleDoc)
    file_store = FileDocumentStore("doc.sample", tmp_path / "sample.yaml", yaml_codec)
    mem_doc = InMemoryDocumentStore("doc.mem", _SampleDoc, codec=json_codec)
    engine = SqliteEngine("db.test", ":memory:")
    sql_cat = SqliteCatalogStore(
        engine,
        name="cat.items",
        table="items",
        codec=PydanticJsonCodec(_CatalogItem),
        key_of=lambda item: item.id,
    )
    mem_cat = InMemoryCatalogStore("cat.mem", key_of=lambda item: item.id)

    assert isinstance(yaml_codec, Codec)
    assert isinstance(json_codec, Codec)

    for doc_store in (file_store, mem_doc):
        assert isinstance(doc_store, ManagedBackend)
        assert isinstance(doc_store, ReadableDocument)
        assert isinstance(doc_store, DocumentStore)

    assert isinstance(engine, ManagedBackend)
    assert isinstance(engine, Migratable)
    assert isinstance(engine, UnitOfWork)
    assert isinstance(NoopUnitOfWork(), UnitOfWork)

    assert isinstance(sql_cat, ManagedBackend)
    assert isinstance(sql_cat, Migratable)
    assert isinstance(sql_cat, ReadableCatalog)
    assert isinstance(sql_cat, CatalogStore)

    assert isinstance(mem_cat, ManagedBackend)
    assert isinstance(mem_cat, ReadableCatalog)
    assert isinstance(mem_cat, CatalogStore)
    engine.close()


# ── StorageLayout ───────────────────────────────────────────────────────────


def test_storage_layout_env_resolution_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit = tmp_path / "explicit"
    shin_root = tmp_path / "shin"
    easy_root = tmp_path / "easy"
    cwd_root = tmp_path / "cwd"
    for folder in (explicit, shin_root, easy_root, cwd_root):
        folder.mkdir()

    monkeypatch.chdir(cwd_root)
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(easy_root))
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(shin_root))

    assert StorageLayout.from_env(explicit).project_root == explicit.resolve()
    assert StorageLayout.from_env().project_root == shin_root.resolve()

    monkeypatch.delenv("SHINSEKAI_PROJECT_ROOT")
    assert StorageLayout.from_env().project_root == easy_root.resolve()

    monkeypatch.delenv("EASYAI_PROJECT_ROOT")
    assert StorageLayout.from_env().project_root == cwd_root.resolve()


def test_storage_layout_exposes_directories_and_rejects_traversal(tmp_path: Path) -> None:
    layout = StorageLayout(tmp_path)
    assert layout.data_dir == layout.project_root / "data"
    assert layout.config_file("api.yaml") == layout.config_dir / "api.yaml"
    assert layout.state_file("ui_state.json") == layout.state_dir / "ui_state.json"
    assert layout.cache_file("models.json") == layout.cache_dir / "models.json"
    assert layout.db_file("shinsekai.db") == layout.main_db_path
    assert layout.media_dir("sprite", "alice") == layout.data_dir / "sprite" / "alice"
    assert layout.media_dir("sprite") == layout.data_dir / "sprite"
    assert layout.legacy_backup_dir == layout.config_dir / "legacy_backup"
    assert layout.migration_lock_path == layout.data_dir / ".storage_migration.lock"

    for bad in ("../outside.yaml", "/etc/passwd", "C:\\escape.yaml", "bad\x00.yaml", "."):
        with pytest.raises((PermissionError, ValueError)):
            layout.config_file(bad)
        with pytest.raises((PermissionError, ValueError)):
            layout.media_dir("sprite", bad)


# ── StorageHub ──────────────────────────────────────────────────────────────


def test_storage_hub_migrates_in_order_closes_in_reverse_and_isolates_failures(
    tmp_path: Path,
) -> None:
    events: list[str] = []

    class _FakeBackend:
        def __init__(
            self,
            name: str,
            *,
            fail_status: bool = False,
            fail_close: bool = False,
        ) -> None:
            self.name = name
            self._fail_status = fail_status
            self._fail_close = fail_close

        def migrate(self) -> None:
            events.append(f"migrate:{self.name}")

        def status(self) -> BackendStatus:
            if self._fail_status:
                raise OSError("status probe failed")
            return BackendStatus(name=self.name, kind="memory", location=f"mem://{self.name}")

        def close(self) -> None:
            events.append(f"close:{self.name}")
            if self._fail_close:
                raise RuntimeError(f"close error in {self.name}")

    hub = StorageHub(StorageLayout(tmp_path))
    first = hub.register(_FakeBackend("first"))
    hub.register(_FakeBackend("second", fail_status=True, fail_close=True))
    hub.register(_FakeBackend("third"))

    assert hub.get_backend("first") is first
    assert len(hub.backends) == 3

    with pytest.raises(ValueError, match="Duplicate"):
        hub.register(_FakeBackend("first"))

    hub.migrate_all()
    assert events == ["migrate:first", "migrate:second", "migrate:third"]

    statuses = hub.statuses()
    assert [s.name for s in statuses] == ["first", "second", "third"]
    assert statuses[0].healthy is True
    assert statuses[1].healthy is False
    assert "status probe failed" in statuses[1].detail
    assert statuses[2].healthy is True

    with pytest.raises(RuntimeError, match="close error in second"):
        hub.close_all()
    # Every backend still received close() in reverse order despite second failing.
    assert events[3:] == ["close:third", "close:second", "close:first"]

    # Idempotent second close does nothing and does not re-raise.
    hub.close_all()
    assert len(events) == 6

    with pytest.raises(RuntimeError, match="closed"):
        hub.register(_FakeBackend("fourth"))


# ── FileDocumentStore ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("filename", "codec_cls", "null_content"),
    [
        ("settings.yaml", PydanticYamlCodec, "null\n"),
        ("settings.json", PydanticJsonCodec, ""),
    ],
)
def test_file_document_store_defaults_and_pre_decode(
    tmp_path: Path, filename: str, codec_cls: Any, null_content: str
) -> None:
    def upgrade(raw: Any) -> Any:
        if isinstance(raw, dict) and "legacy_title" in raw:
            return {**raw, "title": raw.pop("legacy_title")}
        return raw

    codec = codec_cls(_SampleDoc, pre_decode=upgrade)
    target = tmp_path / filename
    store = FileDocumentStore("doc.test", target, codec)

    # Missing file yields default without creating a file.
    assert store.get() == _SampleDoc()
    assert not target.exists()

    # Empty or null content falls back cleanly to default.
    target.write_text(null_content, encoding="utf-8")
    assert store.get() == _SampleDoc()

    # Legacy payloads transform through pre_decode cleanly.
    if filename.endswith(".yaml"):
        target.write_text("legacy_title: migrated\ncount: 7\n", encoding="utf-8")
    else:
        target.write_text('{"legacy_title": "migrated", "count": 7}', encoding="utf-8")
    loaded = store.get()
    assert loaded == _SampleDoc(title="migrated", count=7)


def test_file_document_store_cache_hit_external_reload_snapshots_and_revision(
    tmp_path: Path,
) -> None:
    decode_calls = 0
    inner = PydanticYamlCodec(_SampleDoc)

    class _CountingCodec:
        def default(self) -> _SampleDoc:
            return inner.default()

        def decode(self, raw: bytes) -> _SampleDoc:
            nonlocal decode_calls
            decode_calls += 1
            return inner.decode(raw)

        def encode(self, value: _SampleDoc) -> bytes:
            return inner.encode(value)

    target = tmp_path / "doc.yaml"
    store = FileDocumentStore("doc.counted", target, _CountingCodec())
    rev_initial = store.save(_SampleDoc(title="alpha", count=1, tags=["a"]))
    assert decode_calls == 0

    # Repeated reads with unchanged stat hit memory cache.
    snapshot = store.get()
    assert store.get() == _SampleDoc(title="alpha", count=1, tags=["a"])
    assert decode_calls == 0

    # Mutating returned snapshot cannot leak back into cache.
    snapshot.title = "mutated-by-caller"
    snapshot.tags.append("injected")
    assert store.get() == _SampleDoc(title="alpha", count=1, tags=["a"])

    # Saving semantically equal value preserves revision.
    rev_same = store.save(_SampleDoc(title="alpha", count=1, tags=["a"]))
    assert rev_same == rev_initial

    # External edit on disk invalidates cache via mtime/size change.
    target.write_text("title: external\ncount: 9\ntags:\n- b\n", encoding="utf-8")
    stat = target.stat()
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert store.get() == _SampleDoc(title="external", count=9, tags=["b"])
    assert decode_calls == 1
    assert store.revision != rev_initial


def test_file_document_store_concurrent_updates_and_failure_leaves_no_tmp(
    tmp_path: Path,
) -> None:
    target = tmp_path / "counter.json"
    store = FileDocumentStore("doc.counter", target, PydanticJsonCodec(_SampleDoc))
    store.save(_SampleDoc(title="counter", count=0))

    def worker() -> None:
        for _ in range(25):
            store.update(lambda d: d.model_copy(update={"count": d.count + 1}))

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(worker) for _ in range(8)]
        for fut in futures:
            fut.result()

    assert store.get().count == 200

    # Invalid mutation / encoding error preserves prior content and cleans up temp files.
    class _FailingValue:
        def model_dump(self, **_kwargs: Any) -> Any:
            raise ValueError("serialization boom")

    with pytest.raises(ValueError, match="serialization boom"):
        store.save(_FailingValue())  # type: ignore[arg-type]

    assert store.get().count == 200
    assert not list(tmp_path.glob("*.tmp"))


# ── SqliteEngine ────────────────────────────────────────────────────────────


def test_sqlite_engine_wal_foreign_keys_migrations_and_rollback(tmp_path: Path) -> None:
    db_path = tmp_path / "main.db"

    bad_engine = SqliteEngine(
        "db.bad",
        db_path,
        migrations=(
            SqliteMigration(
                1,
                "partial failure",
                """
                CREATE TABLE parents (id INTEGER PRIMARY KEY);
                INSERT INTO non_existent_table VALUES (1);
                """,
            ),
        ),
    )
    with pytest.raises(sqlite3.OperationalError):
        bad_engine.migrate()
    assert bad_engine.schema_version() == 0
    with bad_engine.read_connection() as conn:
        tables = [
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
    assert "parents" not in tables
    bad_engine.close()

    engine = SqliteEngine(
        "db.good",
        db_path,
        migrations=(
            SqliteMigration(
                1,
                "parents and children",
                """
                CREATE TABLE parents (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
                CREATE TABLE children (
                    id INTEGER PRIMARY KEY,
                    parent_id INTEGER NOT NULL REFERENCES parents(id) ON DELETE CASCADE
                );
                """,
            ),
            SqliteMigration(
                2,
                "seed parent via callable",
                lambda conn: conn.execute("INSERT INTO parents(id, name) VALUES (1, 'Alice')"),
            ),
        ),
    )
    engine.migrate()
    assert engine.schema_version() == 2

    with engine.read_connection() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("SELECT name FROM parents WHERE id = 1").fetchone()["name"] == "Alice"

    with pytest.raises(sqlite3.IntegrityError):
        with engine.write_connection() as conn:
            conn.execute("INSERT INTO children(id, parent_id) VALUES (1, 999)")

    engine.close()

    # Opening with fewer migrations than persisted user_version triggers downgrade guard.
    older = SqliteEngine(
        "db.older",
        db_path,
        migrations=(SqliteMigration(1, "v1 only", "SELECT 1;"),),
    )
    with pytest.raises(RuntimeError, match="newer than supported version"):
        older.migrate()
    older.close()


def test_sqlite_engine_nested_savepoints_and_concurrent_writes(tmp_path: Path) -> None:
    engine = SqliteEngine(
        "db.tx",
        tmp_path / "tx.db",
        migrations=(SqliteMigration(1, "events", "CREATE TABLE events (id INTEGER PRIMARY KEY, tag TEXT);"),),
    )
    engine.migrate()

    # Inner savepoint rolls back while outer transaction survives.
    with engine.atomic():
        with engine.write_connection() as conn:
            conn.execute("INSERT INTO events(id, tag) VALUES (1, 'outer-keep')")
        with pytest.raises(ValueError, match="inner-abort"):
            with engine.atomic():
                with engine.write_connection() as conn:
                    conn.execute("INSERT INTO events(id, tag) VALUES (2, 'inner-drop')")
                raise ValueError("inner-abort")
        with engine.write_connection() as conn:
            conn.execute("INSERT INTO events(id, tag) VALUES (3, 'outer-after')")

    # Outer failure rolls back everything including committed-looking inner savepoint.
    with pytest.raises(RuntimeError, match="outer-abort"):
        with engine.atomic():
            with engine.atomic():
                with engine.write_connection() as conn:
                    conn.execute("INSERT INTO events(id, tag) VALUES (4, 'inner-lost-with-outer')")
            raise RuntimeError("outer-abort")

    with engine.read_connection() as conn:
        tags = [row["tag"] for row in conn.execute("SELECT tag FROM events ORDER BY id")]
    assert tags == ["outer-keep", "outer-after"]

    # Concurrent multi-thread writes through atomic().
    def write_batch(worker_id: int) -> None:
        for i in range(15):
            with engine.write_connection() as conn:
                conn.execute(
                    "INSERT INTO events(id, tag) VALUES (?, ?)",
                    (100 + worker_id * 100 + i, f"w{worker_id}-{i}"),
                )

    with ThreadPoolExecutor(max_workers=6) as pool:
        for fut in [pool.submit(write_batch, wid) for wid in range(6)]:
            fut.result()

    with engine.read_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert total == 2 + 6 * 15
    engine.close()


# ── CatalogStore Contract (InMemory & SqliteCatalogStore) ───────────────────


@pytest.fixture(params=["memory", "sqlite"])
def catalog_pair(request: pytest.FixtureRequest, tmp_path: Path):
    def should_bump_revision(old: _CatalogItem, new: _CatalogItem) -> bool:
        return (old.id, old.name, old.bio) != (new.id, new.name, new.bio)

    if request.param == "memory":
        store = InMemoryCatalogStore(
            "cat.items",
            key_of=lambda item: item.id,
            unique_indexes={"name": lambda item: item.name},
            case_insensitive_indexes=frozenset({"name"}),
            revision_filter=should_bump_revision,
        )
        yield store, None
        store.close()
        return

    engine = SqliteEngine("db.cat", tmp_path / "catalog.db")
    store = SqliteCatalogStore(
        engine,
        name="cat.items",
        table="items",
        codec=PydanticJsonCodec(_CatalogItem),
        key_of=lambda item: item.id,
        indexed_columns=(
            IndexedColumn("name", lambda item: item.name, unique=True, nocase=True),
        ),
        revision_filter=should_bump_revision,
    )
    engine.migrate()
    store.migrate()
    yield store, engine
    store.close()
    engine.close()


def test_catalog_store_crud_order_preservation_and_uniqueness(catalog_pair) -> None:
    store, _engine = catalog_pair
    first = _CatalogItem(id="id-1", name="Alice", bio="first")
    second = _CatalogItem(id="id-2", name="Bob", bio="second")

    rev0 = store.revision
    rev1 = store.put(first.id, first)
    rev2 = store.put(second.id, second)
    assert rev1 != rev0
    assert rev2 != rev1

    # Updating first preserves its original position before second.
    patched = store.patch("id-1", lambda cur: cur.model_copy(update={"bio": "edited"}))
    assert patched.bio == "edited"
    assert [item.id for item in store.list_all()] == ["id-1", "id-2"]
    assert store.get("id-1") == _CatalogItem(id="id-1", name="Alice", bio="edited")

    # Case-insensitive indexed column lookup & unique collision enforcement.
    assert store.get_by_column("name", "alice") == _CatalogItem(
        id="id-1", name="Alice", bio="edited"
    )
    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        store.put("id-3", _CatalogItem(id="id-3", name="ALICE"))

    # Key mismatch and missing patch errors.
    with pytest.raises(ValueError, match="does not match"):
        store.put("wrong-id", _CatalogItem(id="id-3", name="Carol"))
    with pytest.raises(KeyError):
        store.patch("missing", lambda cur: cur)

    # revision_filter suppresses revision bump when only hot_note changes.
    rev_before_hot = store.revision
    store.patch("id-1", lambda cur: cur.model_copy(update={"hot_note": "transient"}))
    assert store.revision == rev_before_hot
    assert store.get("id-1").hot_note == "transient"

    # Delete behavior.
    assert store.delete("id-1") is True
    assert store.delete("id-1") is False
    assert [item.id for item in store.list_all()] == ["id-2"]


def test_sqlite_cross_catalog_unit_of_work_atomic_rollback(tmp_path: Path) -> None:
    engine = SqliteEngine("db.uow", tmp_path / "uow.db")
    characters = SqliteCatalogStore(
        engine,
        name="cat.chars",
        table="characters",
        codec=PydanticJsonCodec(_CatalogItem),
        key_of=lambda item: item.id,
        indexed_columns=(IndexedColumn("name", lambda item: item.name, unique=True, nocase=True),),
    )
    notes = SqliteCatalogStore(
        engine,
        name="cat.notes",
        table="notes",
        codec=PydanticJsonCodec(_CatalogItem),
        key_of=lambda item: item.id,
        indexed_columns=(IndexedColumn("name", lambda item: item.name, unique=True, nocase=True),),
    )
    engine.migrate()
    characters.migrate()
    notes.migrate()

    characters.put("c1", _CatalogItem(id="c1", name="Alice"))
    notes.put("n1", _CatalogItem(id="n1", name="AliceNote"))

    with pytest.raises(sqlite3.IntegrityError):
        with engine.atomic():
            characters.delete("c1")
            # Force collision on notes to trigger rollback across both catalogs.
            notes.put("n2", _CatalogItem(id="n2", name="alicenote"))

    assert characters.get("c1") is not None
    assert notes.get("n1") is not None
    assert notes.get("n2") is None
    engine.close()
