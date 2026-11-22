"""Application composition root for unified document, UI state, and SQLite stores."""

from __future__ import annotations

from collections.abc import Sequence
import contextlib
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from ai.memory.config import bind_memory_api_settings
from ai.memory.runtime import set_memory_store_observer
from ai.tools.character_tools import bind_character_tool_catalog
from application.chat.presentation.updates import bind_presentation_character_catalog
from application.knowledge.runtime import set_knowledge_store_observer
from application.reminders import ReminderStore
from config.backend_port import ConfigBackendPort
from config.config_manager import ConfigManager
from config.models import (
    ApiConfig,
    Background,
    Character,
    Effect,
    McpConfig,
    SystemConfig,
    UiRuntimeState,
    UserPromptPresetLibrary,
    normalize_api_config_dict,
    normalize_system_config_dict,
    normalize_user_prompt_presets_dict,
)
from core.knowledge.bindings import bind_knowledge_binding_store
from core.storage.codecs import PydanticJsonCodec, PydanticYamlCodec
from core.storage.file_store import FileDocumentStore
from core.storage.hub import StorageHub
from core.storage.layout import StorageLayout
from core.storage.migrations import LegacyDataMigrator, MAIN_DB_MIGRATIONS
from core.storage.sqlite_engine import SqliteEngine
from core.storage.stores import (
    SqliteBackgroundCatalog,
    SqliteCharacterCatalog,
    SqliteConversationStore,
    SqliteEffectCatalog,
    SqliteKnowledgeBindingStore,
)
from sdk.adapters.storage import ManagedBackend


class _SystemConfigYamlCodec(PydanticYamlCodec[SystemConfig]):
    """Persist declarative system settings in YAML while excluding transient window geometry."""

    def encode(self, value: SystemConfig) -> bytes:
        payload = value.model_dump(
            mode="json",
            by_alias=self._by_alias,
            exclude_none=self._exclude_none,
            exclude={"chat_window_geometry_b64"},
        )
        return self._dump_text(payload).encode("utf-8")


@dataclass
class AppStores:
    """Explicit dependency container owning all managed application stores."""

    layout: StorageLayout
    hub: StorageHub
    api_settings: FileDocumentStore[ApiConfig]
    system_settings: FileDocumentStore[SystemConfig]
    mcp_settings: FileDocumentStore[McpConfig]
    prompt_presets: FileDocumentStore[UserPromptPresetLibrary]
    ui_state: FileDocumentStore[UiRuntimeState]
    main_db: SqliteEngine
    characters: SqliteCharacterCatalog
    backgrounds: SqliteBackgroundCatalog
    effects: SqliteEffectCatalog
    conversations: SqliteConversationStore
    knowledge_bindings: SqliteKnowledgeBindingStore
    reminders: ReminderStore
    migrator: LegacyDataMigrator
    bound_globals: bool = False

    def close(self) -> None:
        """Unbind compatibility singletons if owned and close all storage backends."""
        if self.bound_globals:
            set_memory_store_observer(None)
            set_knowledge_store_observer(None)
            bind_character_tool_catalog(None)
            bind_memory_api_settings(None)
            bind_presentation_character_catalog(None)
            ConfigManager.unbind_backend(self.layout.project_root)
            bind_knowledge_binding_store(None)
            self.bound_globals = False
        self.hub.close_all()


class AppStoresConfigBackend:
    """Adapter presenting ``AppStores`` behind ``ConfigBackendPort`` for ``ConfigManager``."""

    def __init__(self, stores: AppStores) -> None:
        self._stores = stores

    @property
    def characters_revision(self) -> str:
        return self._stores.characters.revision

    def load_api_config(self) -> ApiConfig:
        return self._stores.api_settings.get()

    def save_api_config(self, value: ApiConfig) -> None:
        self._stores.api_settings.save(value)

    def load_system_config(self) -> SystemConfig:
        config = self._stores.system_settings.get()
        geometry = self._stores.ui_state.get().chat_window_geometry_b64
        if geometry:
            config.chat_window_geometry_b64 = geometry
        return config

    def save_system_config(self, value: SystemConfig) -> None:
        geometry = str(value.chat_window_geometry_b64 or "")
        current_ui = self._stores.ui_state.get()
        if geometry != current_ui.chat_window_geometry_b64:
            self._stores.ui_state.update(
                lambda state: state.model_copy(
                    update={"chat_window_geometry_b64": geometry}
                )
            )
        self._stores.system_settings.save(value)

    def list_characters(self) -> list[Character]:
        return list(self._stores.characters.list_all())

    def save_characters(self, items: Sequence[Character]) -> str:
        return self._stores.characters.replace_all(items)

    def get_character_by_id(self, char_id: str) -> Character | None:
        return self._stores.characters.get(char_id)

    def get_character_by_name(self, name: str) -> Character | None:
        return self._stores.characters.get_by_name(name)

    def ensure_self_persona(self) -> Character:
        return self._stores.characters.ensure_self_persona()

    def put_character(self, character: Character) -> None:
        self._stores.characters.put(character.id, character)

    def delete_character(self, char_id: str) -> bool:
        return bool(self._stores.characters.delete(char_id))

    def list_backgrounds(self) -> list[Background]:
        return list(self._stores.backgrounds.list_all())

    def save_backgrounds(self, items: Sequence[Background]) -> str:
        return self._stores.backgrounds.replace_all(items)

    def get_background_by_id(self, bg_id: str) -> Background | None:
        return self._stores.backgrounds.get(bg_id)

    def get_background_by_name(self, name: str) -> Background | None:
        return self._stores.backgrounds.get_by_name(name)

    def put_background(self, background: Background) -> None:
        self._stores.backgrounds.put(background.id, background)

    def delete_background(self, bg_id: str) -> bool:
        return bool(self._stores.backgrounds.delete(bg_id))

    def list_effects(self) -> list[Effect]:
        return list(self._stores.effects.list_all())

    def save_effects(self, items: Sequence[Effect]) -> str:
        return self._stores.effects.replace_all(items)


def _hub_backend_observer(hub: StorageHub, logical_name: str):
    def _observe(backend: ManagedBackend | None) -> None:
        if backend is None:
            hub.unregister(logical_name)
            return
        with contextlib.suppress(RuntimeError):
            hub.register_or_replace(backend)

    return _observe


def build_app_stores(
    project_root: str | os.PathLike[str] | None = None,
    *,
    bind_globals: bool = True,
) -> AppStores:
    """Create, register, migrate, and optionally bind all application stores for ``project_root``."""
    layout = StorageLayout.from_env(project_root)
    hub = StorageHub(layout)

    api_settings = hub.register(
        FileDocumentStore(
            "settings.api",
            layout.config_file("api.yaml"),
            PydanticYamlCodec(ApiConfig, pre_decode=normalize_api_config_dict),
        )
    )
    system_settings = hub.register(
        FileDocumentStore(
            "settings.system",
            layout.config_file("system_config.yaml"),
            _SystemConfigYamlCodec(
                SystemConfig, pre_decode=normalize_system_config_dict
            ),
        )
    )
    mcp_settings = hub.register(
        FileDocumentStore(
            "settings.mcp",
            layout.config_file("mcp.yaml"),
            PydanticYamlCodec(McpConfig),
        )
    )
    prompt_presets = hub.register(
        FileDocumentStore(
            "settings.prompt_presets",
            layout.config_file("user_prompt_presets.json"),
            PydanticJsonCodec(
                UserPromptPresetLibrary,
                pre_decode=normalize_user_prompt_presets_dict,
                exclude_none=True,
            ),
        )
    )
    ui_state = hub.register(
        FileDocumentStore(
            "state.ui",
            layout.state_file("ui_state.json"),
            PydanticJsonCodec(UiRuntimeState),
        )
    )

    main_db = hub.register(
        SqliteEngine(
            "db.main",
            layout.main_db_path,
            migrations=MAIN_DB_MIGRATIONS,
        )
    )
    characters = hub.register(SqliteCharacterCatalog(main_db))
    backgrounds = hub.register(SqliteBackgroundCatalog(main_db))
    effects = hub.register(SqliteEffectCatalog(main_db))
    conversations = hub.register(SqliteConversationStore(main_db))
    knowledge_bindings = hub.register(
        SqliteKnowledgeBindingStore(main_db, characters=characters)
    )

    reminders = ReminderStore(layout.project_root, engine=main_db)
    if reminders._unified is not None:
        hub.register(reminders._unified)

    migrator = hub.register(
        LegacyDataMigrator(
            layout,
            main_db,
            system_store=system_settings,
            ui_state_store=ui_state,
        )
    )

    try:
        hub.migrate_all()
    except BaseException:
        hub.close_all()
        raise

    stores = AppStores(
        layout=layout,
        hub=hub,
        api_settings=api_settings,
        system_settings=system_settings,
        mcp_settings=mcp_settings,
        prompt_presets=prompt_presets,
        ui_state=ui_state,
        main_db=main_db,
        characters=characters,
        backgrounds=backgrounds,
        effects=effects,
        conversations=conversations,
        knowledge_bindings=knowledge_bindings,
        reminders=reminders,
        migrator=migrator,
        bound_globals=bind_globals,
    )

    if bind_globals:
        backend: ConfigBackendPort = AppStoresConfigBackend(stores)
        ConfigManager.bind_backend(layout.project_root, backend)
        bind_knowledge_binding_store(knowledge_bindings, project_root=layout.project_root)
        bind_character_tool_catalog(characters)
        bind_memory_api_settings(api_settings, layout=layout)
        bind_presentation_character_catalog(characters)
        set_memory_store_observer(_hub_backend_observer(hub, "db.memory"))
        set_knowledge_store_observer(_hub_backend_observer(hub, "db.knowledge"))

    return stores


__all__ = ["AppStores", "AppStoresConfigBackend", "build_app_stores"]
