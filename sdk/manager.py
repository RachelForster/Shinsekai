"""
Plugin discovery, lifecycle, and aggregated contributions.
"""

from __future__ import annotations

import importlib
import json
import logging
from collections.abc import Callable, Iterable, Iterator, MutableMapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Type

import yaml

from core.handler_registry import MessageHandler, UIOutputMessageHandler
from llm.llm_adapter import LLMAdapter
from llm.tools.tool_manager import ToolManager
from tts.tts_adapter import TTSAdapter

from sdk.plugin import ShinsekaiPlugin
from sdk.types import (
    DesktopUIContribution,
    PluginDescriptor,
    SettingsUIContribution,
    ToolsTabContribution,
)

if TYPE_CHECKING:
    from config.config_manager import ConfigManager

logger = logging.getLogger(__name__)


def _import_class(entry: str) -> Type[ShinsekaiPlugin]:
    """
    Resolve ``package.module:ClassName`` or ``package.module`` (attribute ``Plugin``).
    """
    entry = entry.strip()
    if ":" in entry:
        mod_name, _, attr = entry.partition(":")
        module = importlib.import_module(mod_name)
        cls = getattr(module, attr)
    else:
        module = importlib.import_module(entry)
        cls = getattr(module, "Plugin", None)
        if cls is None:
            raise AttributeError(
                f"Module {entry!r} has no 'Plugin' attribute; use package.module:ClassName"
            )
    if not isinstance(cls, type) or not issubclass(cls, ShinsekaiPlugin):
        raise TypeError(f"{cls!r} is not a subclass of ShinsekaiPlugin")
    return cls


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

    def __init__(self, *, plugin_data_root: Path | None = None) -> None:
        self._plugin_data_root = (
            Path(plugin_data_root) if plugin_data_root is not None else Path("data/plugins")
        )
        self._classes: list[Type[ShinsekaiPlugin]] = []
        self._instances: list[ShinsekaiPlugin] = []

    @property
    def plugins(self) -> Sequence[ShinsekaiPlugin]:
        return tuple(self._instances)

    def register_plugin_class(self, cls: Type[ShinsekaiPlugin]) -> None:
        if not isinstance(cls, type) or not issubclass(cls, ShinsekaiPlugin):
            raise TypeError(f"{cls!r} must be a subclass of ShinsekaiPlugin")
        self._classes.append(cls)

    def load_from_descriptors(self, descriptors: Iterable[PluginDescriptor]) -> None:
        for d in descriptors:
            if not d.enabled:
                continue
            self._classes.append(_import_class(d.entry))

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
        self._instances = [cls() for cls in self._classes]

    def load_own_config_all(self, app_config: ConfigManager | None = None) -> None:
        self._plugin_data_root.mkdir(parents=True, exist_ok=True)
        for p in self._instances:
            root = self._plugin_data_root / p.plugin_id.replace("/", "_")
            root.mkdir(parents=True, exist_ok=True)
            try:
                p.load_own_config(root, app_config=app_config)
            except Exception:
                logger.exception("load_own_config failed for %s", p.plugin_id)

    def apply_llm_providers(
        self, target: MutableMapping[str, Type[LLMAdapter]]
    ) -> None:
        for p in self._instances:
            try:
                p.customize_llm_adapter(target)
            except Exception:
                logger.exception("customize_llm_adapter failed for %s", p.plugin_id)

    def apply_tts_providers(
        self, target: MutableMapping[str, Type[TTSAdapter]]
    ) -> None:
        for p in self._instances:
            try:
                p.customize_tts_adapter(target)
            except Exception:
                logger.exception("customize_tts_adapter failed for %s", p.plugin_id)

    def apply_llm_tools(self, tool_manager: ToolManager) -> None:
        for p in self._instances:
            try:
                p.add_llm_tools(tool_manager)
            except Exception:
                logger.exception("add_llm_tools failed for %s", p.plugin_id)

    def collect_message_handlers(
        self,
    ) -> tuple[list[MessageHandler], list[UIOutputMessageHandler]]:
        tts: list[MessageHandler] = []
        ui: list[UIOutputMessageHandler] = []
        for p in self._instances:
            try:
                p.add_message_handler(tts, ui)
            except Exception:
                logger.exception("add_message_handler failed for %s", p.plugin_id)
        return tts, ui

    def wire_user_input(
        self,
        emit_user_text: Callable[[str], None],
        processors: list[Callable[[str], str | None]],
    ) -> None:
        for p in self._instances:
            try:
                p.trigger_user_input(emit_user_text)
            except Exception:
                logger.exception("trigger_user_input failed for %s", p.plugin_id)
        for p in self._instances:
            try:
                p.handle_user_input(processors)
            except Exception:
                logger.exception("handle_user_input failed for %s", p.plugin_id)

    def collect_settings_contributions(self) -> list[SettingsUIContribution]:
        out: list[SettingsUIContribution] = []
        for p in self._instances:
            try:
                p.add_settings_ui_widgets(out)
            except Exception:
                logger.exception("add_settings_ui_widgets failed for %s", p.plugin_id)
        out.sort(key=lambda c: c.order)
        return out

    def collect_tools_tab_contributions(self) -> list[ToolsTabContribution]:
        out: list[ToolsTabContribution] = []
        for p in self._instances:
            try:
                p.add_tools_tab(out)
            except Exception:
                logger.exception("add_tools_tab failed for %s", p.plugin_id)
        out.sort(key=lambda c: c.order)
        return out

    def collect_desktop_contributions(self) -> list[DesktopUIContribution]:
        out: list[DesktopUIContribution] = []
        for p in self._instances:
            try:
                p.add_desktop_ui_widgets(out)
            except Exception:
                logger.exception("add_desktop_ui_widgets failed for %s", p.plugin_id)
        out.sort(key=lambda c: c.order)
        return out

    def iter_plugin_ids(self) -> Iterator[str]:
        return (p.plugin_id for p in self._instances)
