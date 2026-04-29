"""
Plugin registration center with lazy class resolution.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Type

from sdk.plugin import PluginBase
from sdk.types import PluginDescriptor

from core.handlers.handler_registry import MessageHandler, UIOutputMessageHandler
from llm.llm_adapter import LLMAdapter
from llm.tools.tool_manager import ToolManager
from tts.tts_adapter import TTSAdapter

if TYPE_CHECKING:
    from sdk.types import (
        DesktopUIContribution,
        SettingsUIContribution,
        ToolsTabContribution,
    )


@dataclass(frozen=True)
class _ClassEntry:
    cls: Type[PluginBase]
    enabled: bool = True


@dataclass(frozen=True)
class _ImportEntry:
    entry: str
    enabled: bool = True


class PluginRegister:
    """
    Keep plugin registrations and resolve classes only when needed.
    """

    def __init__(self) -> None:
        self._class_entries: list[_ClassEntry] = []
        self._import_entries: list[_ImportEntry] = []
        self._llm_adapters: dict[str, Type[LLMAdapter]] = {}
        self._tts_adapters: dict[str, Type[TTSAdapter]] = {}
        self._llm_tool_registrars: list[Callable[[ToolManager], None]] = []
        self._tts_handlers: list[MessageHandler] = []
        self._ui_handlers: list[UIOutputMessageHandler] = []
        self._user_input_triggers: list[Callable[[Callable[[str], None]], None]] = []
        self._user_input_processors: list[Callable[[str], str | None]] = []
        self._settings_contributions: list[SettingsUIContribution] = []
        self._tools_tab_contributions: list[ToolsTabContribution] = []
        self._desktop_contributions: list[DesktopUIContribution] = []

    def register_class(self, cls: Type[PluginBase], *, enabled: bool = True) -> None:
        if not isinstance(cls, type) or not issubclass(cls, PluginBase):
            raise TypeError(f"{cls!r} must be a subclass of PluginBase")
        self._class_entries.append(_ClassEntry(cls=cls, enabled=enabled))

    def register_entry(self, entry: str, *, enabled: bool = True) -> None:
        cleaned = entry.strip()
        if not cleaned:
            raise ValueError("Plugin entry cannot be empty")
        self._import_entries.append(_ImportEntry(entry=cleaned, enabled=enabled))

    def register_descriptors(self, descriptors: Iterable[PluginDescriptor]) -> None:
        for d in descriptors:
            self.register_entry(d.entry, enabled=d.enabled)

    def iter_enabled_classes(self) -> Iterator[Type[PluginBase]]:
        seen: set[str] = set()
        for class_entry in self._class_entries:
            if not class_entry.enabled:
                continue
            key = f"{class_entry.cls.__module__}:{class_entry.cls.__qualname__}"
            if key in seen:
                continue
            seen.add(key)
            yield class_entry.cls
        for import_entry in self._import_entries:
            if not import_entry.enabled:
                continue
            cls = self._import_class(import_entry.entry)
            key = f"{cls.__module__}:{cls.__qualname__}"
            if key in seen:
                continue
            seen.add(key)
            yield cls

    def _import_class(self, entry: str) -> Type[PluginBase]:
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
        if not isinstance(cls, type) or not issubclass(cls, PluginBase):
            raise TypeError(f"{cls!r} is not a subclass of PluginBase")
        return cls

    # --- capability registration API ---

    def register_llm_adapter(self, provider: str, adapter_cls: Type[LLMAdapter]) -> None:
        self._llm_adapters[provider] = adapter_cls

    def register_tts_adapter(self, provider: str, adapter_cls: Type[TTSAdapter]) -> None:
        self._tts_adapters[provider] = adapter_cls

    def register_llm_tool(self, registrar: Callable[[ToolManager], None]) -> None:
        self._llm_tool_registrars.append(registrar)

    def register_message_handler(
        self,
        *,
        tts_handler: MessageHandler | None = None,
        ui_handler: UIOutputMessageHandler | None = None,
    ) -> None:
        if tts_handler is not None:
            self._tts_handlers.append(tts_handler)
        if ui_handler is not None:
            self._ui_handlers.append(ui_handler)

    def register_user_input_trigger(
        self,
        trigger: Callable[[Callable[[str], None]], None],
    ) -> None:
        self._user_input_triggers.append(trigger)

    def register_user_input_processor(self, processor: Callable[[str], str | None]) -> None:
        self._user_input_processors.append(processor)

    def register_settings_ui(self, contribution: SettingsUIContribution) -> None:
        self._settings_contributions.append(contribution)

    def register_tools_tab(self, contribution: ToolsTabContribution) -> None:
        self._tools_tab_contributions.append(contribution)

    def register_desktop_widget(self, contribution: DesktopUIContribution) -> None:
        self._desktop_contributions.append(contribution)

    # --- capability readers for host/manager ---

    @property
    def llm_adapters(self) -> dict[str, Type[LLMAdapter]]:
        return dict(self._llm_adapters)

    @property
    def tts_adapters(self) -> dict[str, Type[TTSAdapter]]:
        return dict(self._tts_adapters)

    @property
    def message_handlers(self) -> tuple[list[MessageHandler], list[UIOutputMessageHandler]]:
        return list(self._tts_handlers), list(self._ui_handlers)

    @property
    def user_input_hooks(
        self,
    ) -> tuple[list[Callable[[Callable[[str], None]], None]], list[Callable[[str], str | None]]]:
        return list(self._user_input_triggers), list(self._user_input_processors)

    @property
    def settings_contributions(self) -> list[SettingsUIContribution]:
        return sorted(self._settings_contributions, key=lambda c: c.order)

    @property
    def tools_tab_contributions(self) -> list[ToolsTabContribution]:
        return sorted(self._tools_tab_contributions, key=lambda c: c.order)

    @property
    def desktop_contributions(self) -> list[DesktopUIContribution]:
        return sorted(self._desktop_contributions, key=lambda c: c.order)

    def apply_llm_tools(self, tool_manager: ToolManager) -> None:
        for registrar in self._llm_tool_registrars:
            registrar(tool_manager)
