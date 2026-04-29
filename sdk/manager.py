"""
Plugin discovery, lifecycle, and aggregated contributions.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Iterator, MutableMapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Type

import yaml

from core.handlers.handler_registry import MessageHandler, UIOutputMessageHandler
from llm.llm_adapter import LLMAdapter
from llm.tools.tool_manager import ToolManager
from tts.tts_adapter import TTSAdapter

from sdk.plugin import PluginBase
from sdk.register import PluginRegister
from sdk.types import (
    DesktopUIContribution,
    PluginDescriptor,
    SettingsUIContribution,
    ToolsTabContribution,
)

if TYPE_CHECKING:
    from config.config_manager import ConfigManager

logger = logging.getLogger(__name__)

class PluginManager:
    """
    Owns plugin instances and applies their hooks in a deterministic order.

    **Basic usage**

    .. code-block:: python

        mgr = PluginManager()
        mgr.register_plugin_class(MyPlugin)
        mgr.load_own_config_all(Path("data/plugins"))
        merged_llm = {}
        mgr.apply_llm_providers(merged_llm)
        # merge merged_llm into LLMAdapterFactory._adapters

    **Manifest:** JSON/YAML list of :class:`~sdk.types.PluginDescriptor` dicts::

        - entry: my_pkg.plugins.demo:DemoPlugin
          enabled: true
    """

    def __init__(
        self,
        *,
        plugin_data_root: Path | None = None,
        register: PluginRegister | None = None,
    ) -> None:
        self._plugin_data_root = (
            Path(plugin_data_root) if plugin_data_root is not None else Path("data/plugins")
        )
        self._register = register if register is not None else PluginRegister()
        self._capabilities = PluginRegister()
        self._instances: list[PluginBase] = []
        self._instantiated = False
        self._initialized = False

    @property
    def plugins(self) -> Sequence[PluginBase]:
        self._ensure_plugins_instantiated()
        self._ensure_plugins_initialized()
        return tuple(self._instances)

    def register_plugin_class(self, cls: Type[PluginBase]) -> None:
        self._register.register_class(cls)

    def load_from_descriptors(self, descriptors: Iterable[PluginDescriptor]) -> None:
        self._register.register_descriptors(descriptors)

    def load_manifest_file(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() in {".yaml", ".yml"}:
            raw = yaml.safe_load(text) or []
        else:
            raw = json.loads(text)
        if not isinstance(raw, list):
            raise ValueError(f"Plugin manifest must be a list: {path}")
        descs: list[PluginDescriptor] = []
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError(f"Each manifest item must be a mapping: {item!r}")
            entry = item.get("entry")
            if not entry or not isinstance(entry, str):
                raise ValueError(f"Manifest item missing string 'entry': {item!r}")
            enabled = bool(item.get("enabled", True))
            extra = {
                k: v
                for k, v in item.items()
                if k not in ("entry", "enabled")
            }
            descs.append(
                PluginDescriptor(entry=entry.strip(), enabled=enabled, extra=extra)
            )
        self.load_from_descriptors(descs)

    def instantiate_all(self) -> None:
        self._ensure_plugins_instantiated()
        self._ensure_plugins_initialized()

    def _ensure_plugins_instantiated(self) -> None:
        if self._instantiated:
            return
        classes = list(self._register.iter_enabled_classes())
        instances = [cls() for cls in classes]
        self._instances = sorted((p for p in instances if p.enabled), key=lambda p: p.priority)
        self._instantiated = True

    def _ensure_plugins_initialized(self, app_config: ConfigManager | None = None) -> None:
        self._ensure_plugins_instantiated()
        if self._initialized and app_config is None:
            return
        self._plugin_data_root.mkdir(parents=True, exist_ok=True)
        # refresh runtime capability registry on initialization
        self._capabilities = PluginRegister()
        for plugin in self._instances:
            root = self._plugin_data_root / plugin.plugin_id.replace("/", "_")
            root.mkdir(parents=True, exist_ok=True)
            try:
                plugin.initialize(self._capabilities, root, app_config=app_config)
            except Exception:
                logger.exception("initialize failed for %s", plugin.plugin_id)
        self._initialized = True

    def load_own_config_all(self, app_config: ConfigManager | None = None) -> None:
        self._ensure_plugins_initialized(app_config=app_config)

    def apply_llm_providers(
        self, target: MutableMapping[str, Type[LLMAdapter]]
    ) -> None:
        self._ensure_plugins_instantiated()
        self._ensure_plugins_initialized()
        target.update(self._capabilities.llm_adapters)

    def apply_tts_providers(
        self, target: MutableMapping[str, Type[TTSAdapter]]
    ) -> None:
        self._ensure_plugins_instantiated()
        self._ensure_plugins_initialized()
        target.update(self._capabilities.tts_adapters)

    def apply_llm_tools(self, tool_manager: ToolManager) -> None:
        self._ensure_plugins_instantiated()
        self._ensure_plugins_initialized()
        try:
            self._capabilities.apply_llm_tools(tool_manager)
        except Exception:
            logger.exception("apply_llm_tools failed")

    def collect_message_handlers(
        self,
    ) -> tuple[list[MessageHandler], list[UIOutputMessageHandler]]:
        self._ensure_plugins_instantiated()
        self._ensure_plugins_initialized()
        return self._capabilities.message_handlers

    def wire_user_input(
        self,
        emit_user_text: Callable[[str], None],
        processors: list[Callable[[str], str | None]],
    ) -> None:
        self._ensure_plugins_instantiated()
        self._ensure_plugins_initialized()
        triggers, plugin_processors = self._capabilities.user_input_hooks
        for trigger in triggers:
            try:
                trigger(emit_user_text)
            except Exception:
                logger.exception("trigger_user_input failed")
        processors.extend(plugin_processors)

    def collect_settings_contributions(self) -> list[SettingsUIContribution]:
        self._ensure_plugins_instantiated()
        self._ensure_plugins_initialized()
        return self._capabilities.settings_contributions

    def collect_tools_tab_contributions(self) -> list[ToolsTabContribution]:
        self._ensure_plugins_instantiated()
        self._ensure_plugins_initialized()
        return self._capabilities.tools_tab_contributions

    def collect_desktop_contributions(self) -> list[DesktopUIContribution]:
        self._ensure_plugins_instantiated()
        self._ensure_plugins_initialized()
        return self._capabilities.desktop_contributions

    def iter_plugin_ids(self) -> Iterator[str]:
        return (p.plugin_id for p in self._instances)
