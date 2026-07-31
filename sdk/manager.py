"""
Plugin discovery, lifecycle, and aggregated contributions.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Iterable, Iterator, MutableMapping, Sequence
from pathlib import Path
from typing import Any, Type

import yaml

from sdk.file_transactions import (
    ensure_portable_name_available,
    portable_name_key,
    read_text_without_links,
)
from sdk.path_contract import (
    managed_child_path,
    project_root,
    require_directory_without_links,
    require_symlink_free_absolute_path,
    resolve_managed_project_path,
    resolve_project_output_path,
    resolve_project_path,
    resolve_project_read_path,
    safe_path_component,
)

from sdk.handlers import MessageHandler, UIOutputMessageHandler
from sdk.adapters import (
    ASRAdapter,
    LLMAdapter,
    T2IAdapter,
    TTSAdapter,
    VisionFallbackContribution,
)

from sdk.hooks import PluginHookDispatcher
from sdk.plugin import PluginBase
from sdk.plugin_host_context import PluginHostContext
from sdk.register import PluginCapabilityRegistry, PluginDiscoveryRegistry
from sdk.types import (
    ChatUIContribution,
    FrontendChatUIContribution,
    FrontendConfigContribution,
    FrontendPageContribution,
    OutputContractPatch,
    PluginDescriptor,
    SettingsUIContribution,
    ToolsTabContribution,
    WorkflowContribution,
)

from sdk.tool_protocol import ToolManager

logger = logging.getLogger(__name__)


class PluginManager:
    """
    Owns plugin instances and applies their hooks in a deterministic order.

    Discovery (classes / manifest entries) is separate from the runtime
    :class:`~sdk.register.PluginCapabilityRegistry` passed into each plugin's
    :meth:`~sdk.plugin.PluginBase.initialize`.

    **Typical host flow**

    1. ``load_manifest_file`` and/or ``register_plugin_class`` / ``register_plugin_entry``
    2. ``instantiate_all()`` — build instances only
    3. ``load_own_config_all(app_config=...)`` — call ``initialize`` on each plugin
    4. Apply adapter providers and collect optional capabilities such as vision fallbacks

    **Manifest:** JSON/YAML list of :class:`~sdk.types.PluginDescriptor` dicts::

        - entry: my_pkg.plugins.demo:DemoPlugin
          enabled: true
    """

    def __init__(
        self,
        *,
        plugin_data_root: Path | None = None,
        discovery: PluginDiscoveryRegistry | None = None,
        root: str | Path | None = None,
    ) -> None:
        authoritative_root = (
            project_root()
            if root is None
            else resolve_project_path(".", root=root)
        )
        configured_value = (
            os.fspath(plugin_data_root)
            if plugin_data_root is not None
            else os.fspath(authoritative_root / "data" / "plugins")
        )
        configured_root = Path(configured_value).expanduser()
        explicitly_absolute = configured_root.is_absolute()
        project_owned = not explicitly_absolute
        if explicitly_absolute:
            try:
                configured_root.relative_to(authoritative_root)
                project_owned = True
            except ValueError:
                project_owned = False
        if project_owned:
            resolved_root = resolve_managed_project_path(
                configured_value,
                root=authoritative_root,
            )
        else:
            require_symlink_free_absolute_path(
                configured_root,
                field="plugin data root",
            )
            resolved_root = resolve_project_output_path(
                configured_value,
                root=authoritative_root,
            )
        self._project_root = authoritative_root
        self._plugin_data_root = resolved_root
        self._discovery = discovery if discovery is not None else PluginDiscoveryRegistry()
        self._hook_dispatcher = PluginHookDispatcher()
        self._capabilities: PluginCapabilityRegistry | None = None
        self._instances: list[PluginBase] = []
        self._instantiated = False
        self._initialized = False

    @property
    def discovery(self) -> PluginDiscoveryRegistry:
        """Registry of plugin classes / import paths (before instantiation)."""
        return self._discovery

    @property
    def capabilities(self) -> PluginCapabilityRegistry | None:
        """Last capability registry filled by :meth:`load_own_config_all`; ``None`` until then."""
        return self._capabilities

    @property
    def hook_dispatcher(self) -> PluginHookDispatcher:
        return self._hook_dispatcher

    @property
    def plugins(self) -> Sequence[PluginBase]:
        self._ensure_plugins_instantiated()
        self._ensure_plugins_initialized()
        return tuple(self._instances)

    def register_plugin_class(self, cls: Type[PluginBase]) -> None:
        self._discovery.register_class(cls)

    def register_plugin_entry(self, entry: str, *, enabled: bool = True) -> None:
        """Register a manifest-style ``package.module:Class`` or ``package.module`` (``Plugin`` attr)."""
        self._discovery.register_entry(entry, enabled=enabled)

    def load_from_descriptors(self, descriptors: Iterable[PluginDescriptor]) -> None:
        self._discovery.register_descriptors(descriptors)

    def load_manifest_file(self, path: Path) -> None:
        source = resolve_project_read_path(path, root=self._project_root)
        text = read_text_without_links(source)
        if source.suffix.lower() in {".yaml", ".yml"}:
            raw = yaml.safe_load(text) or []
        else:
            raw = json.loads(text)
        if not isinstance(raw, list):
            raise ValueError(f"Plugin manifest must be a list: {source}")
        descs: list[PluginDescriptor] = []
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError(f"Each manifest item must be a mapping: {item!r}")
            entry = item.get("entry")
            if not entry or not isinstance(entry, str):
                raise ValueError(f"Manifest item missing string 'entry': {item!r}")
            if entry != entry.strip() or any(
                ord(character) < 32
                or ord(character) == 127
                or 0xD800 <= ord(character) <= 0xDFFF
                for character in entry
            ):
                raise ValueError(f"Manifest item entry is not exact: {item!r}")
            enabled = bool(item.get("enabled", True))
            extra = {
                k: v
                for k, v in item.items()
                if k not in ("entry", "enabled")
            }
            descs.append(
                PluginDescriptor(entry=entry, enabled=enabled, extra=extra)
            )
        self.load_from_descriptors(descs)

    def instantiate_all(self) -> None:
        """Resolve discovery entries and construct plugin instances; does **not** call ``initialize``."""
        self._ensure_plugins_instantiated()

    def _ensure_plugins_instantiated(self) -> None:
        if self._instantiated:
            return
        classes = list(self._discovery.iter_enabled_classes())
        instances: list[PluginBase] = []
        for cls in classes:
            try:
                instances.append(cls())
            except Exception:
                logger.exception(
                    "Skipping plugin class %s.%s (instantiate failed)",
                    cls.__module__,
                    cls.__qualname__,
                )
        self._instances = sorted(
            (p for p in instances if p.enabled), key=lambda p: p.priority
        )
        self._instantiated = True

    def _ensure_plugins_initialized(self, app_config: Any | None = None) -> None:
        self._ensure_plugins_instantiated()
        if self._initialized and app_config is None:
            return
        self._plugin_data_root.mkdir(parents=True, exist_ok=True)
        self._plugin_data_root = require_directory_without_links(
            self._plugin_data_root,
            field="plugin data root",
        )
        self._hook_dispatcher.clear()
        self._capabilities = PluginCapabilityRegistry(
            hook_dispatcher=self._hook_dispatcher,
        )
        host = PluginHostContext.from_config_manager(
            app_config,
            project_data_dir=self._plugin_data_root.parent,
        )

        claimed_storage: set[str] = set()
        for plugin in self._instances:
            try:
                storage_name = safe_path_component(
                    str(plugin.plugin_id),
                    field="plugin id",
                )
                storage_key = portable_name_key(storage_name)
                if storage_key in claimed_storage:
                    raise FileExistsError(
                        f"plugin id collides with another loaded plugin: {plugin.plugin_id}"
                    )
                ensure_portable_name_available(self._plugin_data_root, storage_name)
                root = managed_child_path(
                    self._plugin_data_root,
                    storage_name,
                    field="plugin id",
                )
                root.mkdir(exist_ok=True)
                root = require_directory_without_links(
                    root,
                    field="plugin data directory",
                )
                claimed_storage.add(storage_key)
                assert self._capabilities is not None
                self._capabilities.set_settings_ui_plugin_context(
                    plugin.plugin_id, plugin.plugin_version
                )
                plugin.initialize(self._capabilities, root, host)
            except Exception:
                logger.exception("initialize failed for %s", plugin.plugin_id)
            finally:
                if self._capabilities is not None:
                    self._capabilities.clear_settings_ui_plugin_context()
        self._initialized = True

    def load_own_config_all(self, app_config: Any | None = None) -> None:
        """Run :meth:`~sdk.plugin.PluginBase.initialize` for every plugin instance."""
        self._ensure_plugins_initialized(app_config=app_config)

    def apply_llm_providers(
        self, target: MutableMapping[str, Type[LLMAdapter]]
    ) -> None:
        self._ensure_plugins_initialized()
        if self._capabilities is not None:
            target.update(self._capabilities.llm_adapters)

    def apply_tts_providers(
        self, target: MutableMapping[str, Type[TTSAdapter]]
    ) -> None:
        self._ensure_plugins_initialized()
        if self._capabilities is not None:
            target.update(self._capabilities.tts_adapters)

    def apply_asr_providers(
        self, target: MutableMapping[str, Type[ASRAdapter]]
    ) -> None:
        self._ensure_plugins_initialized()
        if self._capabilities is not None:
            target.update(self._capabilities.asr_adapters)

    def apply_t2i_providers(
        self, target: MutableMapping[str, Type[T2IAdapter]]
    ) -> None:
        self._ensure_plugins_initialized()
        if self._capabilities is not None:
            target.update(self._capabilities.t2i_adapters)

    def collect_vision_fallbacks(self) -> list[VisionFallbackContribution]:
        self._ensure_plugins_initialized()
        if self._capabilities is None:
            return []
        return self._capabilities.vision_fallbacks

    def apply_llm_tools(self, tool_manager: ToolManager) -> None:
        self._ensure_plugins_initialized()
        if self._capabilities is None:
            return
        try:
            self._capabilities.apply_llm_tools(tool_manager)
        except Exception:
            logger.exception("apply_llm_tools failed")

    def collect_message_handlers(
        self,
    ) -> tuple[list[MessageHandler], list[UIOutputMessageHandler]]:
        self._ensure_plugins_initialized()
        if self._capabilities is None:
            return [], []
        return self._capabilities.message_handlers

    def wire_user_input(
        self,
        emit_user_text: Callable[[str], None],
        processors: list[Callable[[str], str | None]],
    ) -> None:
        self._ensure_plugins_initialized()
        if self._capabilities is None:
            return
        triggers, plugin_processors = self._capabilities.user_input_hooks
        for trigger in triggers:
            try:
                trigger(emit_user_text)
            except Exception:
                logger.exception("trigger_user_input failed")
        processors.extend(plugin_processors)

    def collect_settings_contributions(self) -> list[SettingsUIContribution]:
        """Return no deprecated Qt settings contributions.

        Plugin initialization still accepts and records the legacy metadata,
        but the current host must never render it.
        """
        self._ensure_plugins_initialized()
        return []

    def collect_tools_tab_contributions(self) -> list[ToolsTabContribution]:
        """Return no deprecated Qt tools contributions."""
        self._ensure_plugins_initialized()
        return []

    def collect_frontend_config_contributions(self) -> list[FrontendConfigContribution]:
        self._ensure_plugins_initialized()
        if self._capabilities is None:
            return []
        return self._capabilities.frontend_config_contributions

    def collect_frontend_page_contributions(self) -> list[FrontendPageContribution]:
        self._ensure_plugins_initialized()
        if self._capabilities is None:
            return []
        return self._capabilities.frontend_page_contributions

    def collect_frontend_chat_ui_contributions(self) -> list[FrontendChatUIContribution]:
        self._ensure_plugins_initialized()
        if self._capabilities is None:
            return []
        return self._capabilities.frontend_chat_ui_contributions

    def collect_chat_ui_contributions(self) -> list[ChatUIContribution]:
        """Return no deprecated Qt chat contributions."""
        self._ensure_plugins_initialized()
        return []

    def collect_dag_yaml_paths(self) -> list[str]:
        self._ensure_plugins_initialized()
        if self._capabilities is None:
            return []
        return self._capabilities.dag_yaml_paths

    def collect_workflow_contributions(self) -> list[WorkflowContribution]:
        self._ensure_plugins_initialized()
        if self._capabilities is None:
            return []
        return self._capabilities.workflow_contributions

    def collect_output_contract_patches(self) -> list[OutputContractPatch]:
        self._ensure_plugins_initialized()
        if self._capabilities is None:
            return []
        return self._capabilities.output_contract_patches

    def iter_plugin_ids(self) -> Iterator[str]:
        self._ensure_plugins_instantiated()
        return (p.plugin_id for p in self._instances)

    def shutdown_all(self) -> None:
        """Call :meth:`~sdk.plugin.PluginBase.shutdown` on instances (reverse priority)."""
        for plugin in sorted(self._instances, key=lambda p: p.priority, reverse=True):
            try:
                plugin.shutdown()
            except Exception:
                logger.exception("shutdown failed for %s", plugin.plugin_id)
