"""Phase 4 unit tests: ManagedBackend lifecycle wiring and narrow port injection."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from ai.memory import config as memory_config
from ai.memory import runtime as memory_runtime
from ai.memory.backends.in_memory import DeterministicHashEmbedder
from ai.memory.backends.sqlite_repo import SqliteHybridMemoryRepo
from ai.memory.engine import HybridMemoryEngine
from ai.tools import character_tools
from application.effects import (
    EffectOperation,
    EffectRequest,
    EffectUseCase,
)
from application.knowledge import runtime as knowledge_runtime
from application.localization.field_translation import translate_character_name_and_tags
from application.runtime.services import ApplicationServices
from application.runtime.stores import build_app_stores
from application.story.characters import CatalogCharacterLibrary, ConfigCharacterLibrary
from application.story.generation import ConfigStoryAuthorModel
from application.story.scene import ConfigSceneModel
from config.feature_flags import FeatureFlag, FeatureFlagConfigManager
from config.models import ApiConfig, Character
from core.agent.storage import AgentStore
from core.chat_history.sqlite_session_store import (
    SqliteSessionStore,
    close_all_session_stores,
    open_session_store_for_dir,
)
from core.storage import InMemoryDocumentStore, StorageHub, StorageLayout
from core.vector_store.sqlite_hybrid_store import SqliteHybridStore
from sdk.adapters.storage import ManagedBackend


def test_sqlite_hybrid_agent_and_session_stores_implement_managed_backend(
    tmp_path: Path,
) -> None:
    hybrid_mem = SqliteHybridStore(":memory:")
    hybrid_disk = SqliteHybridStore(tmp_path / "memory" / "mem.db", name="db.memory")
    agent_store = AgentStore(tmp_path / "agent" / "agent.sqlite")
    session_store = SqliteSessionStore(
        tmp_path / "chat_history" / "save_1",
        session_id="sess-1234567890",
    )

    try:
        for backend in (hybrid_mem, hybrid_disk, agent_store, session_store):
            assert isinstance(backend, ManagedBackend)
            status = backend.status()
            assert status.healthy is True
            assert status.name == backend.name

        assert hybrid_mem.name == "db.hybrid.memory"
        assert hybrid_disk.name == "db.memory"
        assert agent_store.name == "db.agent"
        assert session_store.name == "db.session.sess-1234567"
    finally:
        session_store.close()
        session_store.close()
        agent_store.close()
        agent_store.close()
        hybrid_disk.close()
        hybrid_disk.close()
        hybrid_mem.close()
        hybrid_mem.close()

    assert hybrid_disk.status().healthy is False
    assert hybrid_disk.status().detail == "closed"
    assert agent_store.status().healthy is False
    assert agent_store.status().detail == "closed"
    assert session_store.status().healthy is False
    assert session_store.status().detail == "closed"

    # Lease on AgentStore is released after close()
    reopened = AgentStore(tmp_path / "agent" / "agent.sqlite")
    reopened.close()


def test_storage_hub_dynamic_registration_and_application_services_teardown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    layout = StorageLayout(tmp_path)
    hub = StorageHub(layout)
    first = SqliteHybridStore(":memory:", name="db.dynamic")
    second = SqliteHybridStore(":memory:", name="db.dynamic")

    hub.register_or_replace(first)
    assert hub.get_backend("db.dynamic") is first
    hub.register_or_replace(second)
    assert hub.get_backend("db.dynamic") is second
    detached = hub.unregister("db.dynamic")
    assert detached is second
    assert hub.get_backend("db.dynamic") is None
    hub.close_all()
    first.close()
    second.close()

    stores = build_app_stores(tmp_path, bind_globals=True)
    services = ApplicationServices(stores=stores)
    session_dir = tmp_path / "data" / "chat_history" / "save_phase4"
    tracked_session = open_session_store_for_dir(session_dir)
    assert tracked_session.session_id

    try:
        from application.agent import runtime as agent_runtime_mod
        from sdk.agent import AgentBackendConfig

        class _FakeModelCfg:
            def get_llm_api_config(self):
                return "ChatGPT", "gpt-4o", "https://example.com/v1", "sk-test"

        monkeypatch.setattr(
            agent_runtime_mod,
            "resolve_pi_model",
            lambda _cfg: SimpleNamespace(reference="ChatGPT/gpt-4o"),
        )
        services.agent = agent_runtime_mod.AgentRuntime(
            _FakeModelCfg(),
            tmp_path / "data" / "agent",
            prepare=lambda *_args, **_kwargs: SimpleNamespace(
                backend=AgentBackendConfig(backend_id="mock", backend_version="1"),
                model_ref="ChatGPT/gpt-4o",
                worker_environment=lambda: {},
            ),
        )
        services.start_agent(
            _FakeModelCfg(),
            tmp_path / "data" / "agent",
        )
        assert services.agent is not None
        services.agent._thread.join(timeout=8.0)
        # Register dynamic memory & knowledge stores via observers
        embedder = DeterministicHashEmbedder(dimensions=16)
        mem_sql = SqliteHybridStore(tmp_path / "data" / "memory" / "m.db", name="db.memory")
        mem_engine = HybridMemoryEngine(
            embedder=embedder,
            repo=SqliteHybridMemoryRepo(mem_sql),
            vector_store=mem_sql,
            store=mem_sql,
        )
        know_sql = SqliteHybridStore(tmp_path / "data" / "knowledge" / "k.db", name="db.knowledge")
        know_client = SimpleNamespace(
            store=know_sql,
            close=know_sql.close,
        )
        with memory_runtime._lock:
            memory_runtime._mem0 = mem_engine
            mem_obs = memory_runtime._store_observer
        if mem_obs is not None:
            mem_obs(mem_sql)
        with knowledge_runtime._lock:
            knowledge_runtime._mem0 = know_client
            know_obs = knowledge_runtime._store_observer
        if know_obs is not None:
            know_obs(know_sql)

        names = {snap.name: snap for snap in stores.hub.statuses()}
        assert {"db.main", "db.agent", "db.memory", "db.knowledge"} <= set(names)
        assert names["db.main"].healthy is True
        assert names["db.agent"].healthy is True
        assert names["db.memory"].healthy is True
        assert names["db.knowledge"].healthy is True

        # Early close_runtimes shuts down agent while leaving stores healthy
        services.close_runtimes()
        assert stores.main_db.status().healthy is True

        # Full close shuts down tracked memory, knowledge, session stores, and hub
        services.close()

        assert mem_sql.is_closed is True
        assert know_sql.is_closed is True
        assert tracked_session.status().healthy is False
        assert stores.hub._closed is True
    finally:
        close_all_session_stores()
        services.close()


def test_narrow_ports_operate_without_instantiating_config_manager(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _forbid_config_manager(*_args, **_kwargs):
        raise AssertionError("Phase 4 narrow-port consumer must not instantiate ConfigManager")

    monkeypatch.setattr("config.config_manager.ConfigManager", _forbid_config_manager)

    stores = build_app_stores(tmp_path, bind_globals=False)
    try:
        alice = Character(
            id="char-alice",
            name="Alice",
            color="#ff99aa",
            sprite_prefix="alice",
            character_setting="Library archivist",
            emotion_tags="微笑：温和一笑\n",
        )
        stores.characters.put(alice.id, alice)

        # 1. character_tools bound via CharacterCatalogPort
        character_tools.bind_character_tool_catalog(stores.characters)
        try:
            assert character_tools.get_available_character_name_list() == ["Alice"]
            info = character_tools.get_character_info("Alice")
            assert info["name"] == "Alice"
            assert info["setting"] == "Library archivist"
        finally:
            character_tools.bind_character_tool_catalog(None)

        # 2. CatalogCharacterLibrary & ConfigCharacterLibrary(catalog)
        lib_direct = CatalogCharacterLibrary(stores.characters).load_character("Alice", None)
        lib_compat = ConfigCharacterLibrary(stores.characters).load_character("Alice", None)
        assert lib_direct["id"] == "char-alice"
        assert lib_compat["name"] == "Alice"

        # 3. EffectUseCase driven solely by EffectCatalogPort
        src_wav = tmp_path / "chime.wav"
        src_wav.write_bytes(b"RIFFdemo")
        uc = EffectUseCase(
            None,
            effects=stores.effects,
            project_root=tmp_path,
            local_file_access_roots=[tmp_path],
        )
        saved = uc.execute(
            EffectRequest(
                EffectOperation.SAVE,
                {"name": "Bell", "color": "#abcdef", "prompt_text": "ring"},
            )
        )
        saved_id = saved.id
        with_audio = uc.execute(
            EffectRequest(
                EffectOperation.UPLOAD_AUDIO,
                {"name": "Bell", "paths": [str(src_wav)]},
            )
        )
        assert len(with_audio.audio_list) == 1
        renamed = uc.execute(
            EffectRequest(
                EffectOperation.SAVE,
                {
                    "originalName": "Bell",
                    "effect": {
                        "name": "Chime",
                        "color": "#123456",
                        "prompt_text": "ring",
                        "audio_list": list(with_audio.audio_list),
                        "audio_tags": "特效 1：清脆铃声\n",
                    },
                },
            )
        )
        assert renamed.id == saved_id
        assert renamed.name == "Chime"
        exported = uc.execute(EffectRequest(EffectOperation.EXPORT, {"name": "Chime"}))
        archive = tmp_path / exported.path
        assert zipfile.is_zipfile(archive)
        imported = uc.execute(EffectRequest(EffectOperation.IMPORT, {"paths": [str(archive)]}))
        assert len(imported) == 1
        assert imported[0].name == "Chime_1"
        assert imported[0].id != saved_id
        uc.execute(EffectRequest(EffectOperation.DELETE, {"name": "Chime_1"}))
        assert stores.effects.get_by_name("Chime_1") is None

        # 4. ApiConfig ReadableDocument consumers (memory config, story models, field translation)
        api_doc = InMemoryDocumentStore(
            "settings.api",
            lambda: ApiConfig(),
            initial=ApiConfig(
                llm_provider="ChatGPT",
                llm_api_key={"ChatGPT": "sk-port"},
                llm_model={"ChatGPT": "gpt-4o-mini"},
                llm_base_urls={"ChatGPT": "https://api.example/v1"},
                llm_extra_configs={"ChatGPT": {"timeout": 12}},
            ),
        )
        mem_cfg = memory_config.build_memory_engine_config(
            api_settings=api_doc,
            layout=stores.layout,
        )
        assert mem_cfg["llm"]["provider"] == "openai"
        assert mem_cfg["llm"]["config"]["api_key"] == "sk-port"
        assert mem_cfg["llm"]["config"]["openai_base_url"] == "https://api.example/v1"
        assert Path(mem_cfg["vector_store"]["config"]["path"]).resolve().is_relative_to(
            stores.layout.data_dir.resolve()
        )

        created_calls: list[dict] = []

        class _FakeAdapter:
            def chat(self, messages, stream=False, **kwargs):
                return '{"name":"Alice","emotion_block":"Smile","character_setting":"Archivist"}'

        class _FakeFactory:
            @staticmethod
            def create_adapter(**kwargs):
                created_calls.append(dict(kwargs))
                return _FakeAdapter()

        class _FakeLLMManager:
            def __init__(self, adapter=None, user_template=""):
                self.llm_adapter = adapter

            def chat(self, user, **kwargs):
                return '{"name":"Alice","emotion_block":"Smile","character_setting":"Archivist"}'

        from ai.llm import llm_manager as llm_manager_mod

        monkeypatch.setattr(llm_manager_mod, "LLMAdapterFactory", _FakeFactory)
        monkeypatch.setattr(llm_manager_mod, "LLMManager", _FakeLLMManager)

        flags = FeatureFlagConfigManager(
            environ={},
            overrides={FeatureFlag.STORY_SYSTEM: True},
        )
        author = ConfigStoryAuthorModel(flags, api_doc)
        scene = ConfigSceneModel(flags, api_doc)
        assert author._llm_manager() is not None
        assert scene._llm_manager() is not None
        err, out_name, out_emo, out_set = translate_character_name_and_tags(
            api_doc,
            "en",
            "艾丽丝",
            "微笑",
            "档案员",
        )
        assert err == ""
        assert (out_name, out_emo, out_set) == ("Alice", "Smile", "Archivist")
        assert len(created_calls) >= 2
        assert created_calls[0]["timeout"] == 12
        assert created_calls[0]["api_key"] == "sk-port"
    finally:
        stores.close()
