"""
Plugin discovery (class / import paths) vs runtime capability registration (LLM, TTS, handlers, …).
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Type

from sdk.handlers import MessageHandler, UIOutputMessageHandler
from sdk.adapters import ASRAdapter, LLMAdapter, T2IAdapter, TTSAdapter
from sdk.hooks import (
    BeforeChatContext,
    BeforeCompactContext,
    MessageAddedContext,
    PluginHookDispatcher,
)

if TYPE_CHECKING:
    from llm.tools.tool_manager import ToolManager
from sdk.plugin import PluginBase
from sdk.types import (
    ChatUIContribution,
    FrontendConfigContribution,
    FrontendPageContribution,
    OutputContractPatch,
    PluginDescriptor,
    SettingsUIContribution,
    ToolsTabContribution,
    WorkflowContribution,
)

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class _ClassEntry:
    cls: Type[PluginBase]
    enabled: bool = True


@dataclass(frozen=True)
class _ImportEntry:
    entry: str
    enabled: bool = True


class PluginDiscoveryRegistry:
    """
    Collect plugin classes or import entries; resolve lazily via :meth:`iter_enabled_classes`.
    """

    def __init__(self) -> None:
        self._class_entries: list[_ClassEntry] = []
        self._import_entries: list[_ImportEntry] = []

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
            try:
                cls = self._import_class(import_entry.entry)
            except Exception:
                logger.exception(
                    "Skipping plugin manifest entry %r (import failed)",
                    import_entry.entry,
                )
                continue
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


class PluginCapabilityRegistry:
    """
    Object passed to :meth:`PluginBase.initialize`; hosts read merged results via :class:`PluginManager`.

    **LLM tools:** prefer ``from sdk.tool_registry import tool`` and ``@tool`` on module-level functions;
    the host calls :func:`sdk.tool_registry.apply_registered_tools` before legacy
    :meth:`register_llm_tool` callbacks. You may still use :meth:`register_llm_tool` for imperative registration.
    """

    def __init__(self, hook_dispatcher: PluginHookDispatcher | None = None) -> None:
        self._llm_adapters: dict[str, Type[LLMAdapter]] = {}
        self._tts_adapters: dict[str, Type[TTSAdapter]] = {}
        self._asr_adapters: dict[str, Type[ASRAdapter]] = {}
        self._t2i_adapters: dict[str, Type[T2IAdapter]] = {}
        self._llm_tool_registrars: list[Callable[[ToolManager], None]] = []
        self._tts_handlers: list[MessageHandler] = []
        self._ui_handlers: list[UIOutputMessageHandler] = []
        self._user_input_triggers: list[Callable[[Callable[[str], None]], None]] = []
        self._user_input_processors: list[Callable[[str], str | None]] = []
        self._settings_contributions: list[SettingsUIContribution] = []
        self._settings_ui_plugin_ctx: tuple[str, str] | None = None
        self._tools_tab_contributions: list[ToolsTabContribution] = []
        self._frontend_config_contributions: list[FrontendConfigContribution] = []
        self._frontend_page_contributions: list[FrontendPageContribution] = []
        self._chat_ui_contributions: list[ChatUIContribution] = []
        self._workflow_contributions: list[WorkflowContribution] = []
        self._output_contract_patches: list[OutputContractPatch] = []
        # [MemorySystem] 精简前钩子存储列表
        self._hook_dispatcher = hook_dispatcher or PluginHookDispatcher()

    def register_llm_adapter(self, provider: str, adapter_cls: Type[LLMAdapter]) -> None:
        self._llm_adapters[provider] = adapter_cls

    def register_tts_adapter(self, provider: str, adapter_cls: Type[TTSAdapter]) -> None:
        self._tts_adapters[provider] = adapter_cls

    def register_asr_adapter(self, provider_slug: str, adapter_cls: Type[ASRAdapter]) -> None:
        """Register heavy / optional ASR backends (e.g. Whisper-family plugin)."""
        self._asr_adapters[provider_slug] = adapter_cls

    def register_t2i_adapter(self, provider: str, adapter_cls: Type[T2IAdapter]) -> None:
        """Register optional T2I backends (slug 建议小写，与 ``T2IAdapterFactory.create_adapter`` 查找一致)。"""
        self._t2i_adapters[provider.strip().lower()] = adapter_cls

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

    def set_settings_ui_plugin_context(self, plugin_id: str, plugin_version: str) -> None:
        """Host-only: while a plugin's ``initialize`` runs, attach id/version to settings contributions."""
        self._settings_ui_plugin_ctx = (plugin_id, plugin_version)

    def clear_settings_ui_plugin_context(self) -> None:
        self._settings_ui_plugin_ctx = None

    def register_settings_ui(self, contribution: SettingsUIContribution) -> None:
        ctx = self._settings_ui_plugin_ctx
        if ctx is not None:
            pid, ver = ctx
            contribution = replace(
                contribution,
                plugin_id=contribution.plugin_id or pid,
                plugin_version=contribution.plugin_version or ver,
            )
        self._settings_contributions.append(contribution)

    def register_tools_tab(self, contribution: ToolsTabContribution) -> None:
        ctx = self._settings_ui_plugin_ctx
        if ctx is not None:
            pid, ver = ctx
            contribution = replace(
                contribution,
                plugin_id=contribution.plugin_id or pid,
                plugin_version=contribution.plugin_version or ver,
            )
        self._tools_tab_contributions.append(contribution)

    def register_frontend_config_page(self, contribution: FrontendConfigContribution) -> None:
        ctx = self._settings_ui_plugin_ctx
        if ctx is not None:
            pid, ver = ctx
            contribution = replace(
                contribution,
                plugin_id=contribution.plugin_id or pid,
                plugin_version=contribution.plugin_version or ver,
            )
        self._frontend_config_contributions.append(contribution)

    def register_frontend_page(self, contribution: FrontendPageContribution) -> None:
        ctx = self._settings_ui_plugin_ctx
        if ctx is not None:
            pid, ver = ctx
            contribution = replace(
                contribution,
                plugin_id=contribution.plugin_id or pid,
                plugin_version=contribution.plugin_version or ver,
            )
        self._frontend_page_contributions.append(contribution)

    def register_chat_ui_widget(self, contribution: ChatUIContribution) -> None:
        ctx = self._settings_ui_plugin_ctx
        if ctx is not None:
            pid, ver = ctx
            contribution = replace(
                contribution,
                plugin_id=contribution.plugin_id or pid,
                plugin_version=contribution.plugin_version or ver,
            )
        self._chat_ui_contributions.append(contribution)

    def register_dag_yaml(self, path: str) -> None:
        """Register a workflow YAML path.

        .. note::
            Kept for compatibility. Prefer :meth:`register_workflow` when the
            workflow also owns an LLM output contract/schema.
        """
        cleaned = str(path).strip()
        if not cleaned:
            raise ValueError("Workflow YAML path cannot be empty")
        self.register_workflow(
            WorkflowContribution(
                id=cleaned,
                name=Path(cleaned).stem or cleaned,
                yaml_path=cleaned,
            )
        )

    def register_workflow(self, contribution: WorkflowContribution) -> None:
        """Register a selectable workflow and optional output contract/schema."""
        if not contribution.id.strip():
            raise ValueError("WorkflowContribution.id cannot be empty")
        if not contribution.yaml_path.strip():
            raise ValueError("WorkflowContribution.yaml_path cannot be empty")
        self._workflow_contributions.append(contribution)

    def register_output_contract_patch(self, patch: OutputContractPatch) -> None:
        """Patch a named output contract while reusing its workflow."""
        if not patch.id.strip():
            raise ValueError("OutputContractPatch.id cannot be empty")
        if not patch.target_contract.strip():
            raise ValueError("OutputContractPatch.target_contract cannot be empty")
        self._output_contract_patches.append(patch)

    # [MemorySystem] 注册精简前回调钩子
    @property
    def hook_dispatcher(self) -> PluginHookDispatcher:
        return self._hook_dispatcher

    def register_compact_hook(self, hook: Callable[[list], None]) -> None:
        """注册精简前回调。回调接收即将被精简的完整消息列表，在 compact_messages() 执行前调用。"""
        def _legacy_context_adapter(context: BeforeCompactContext) -> None:
            hook(context.messages)

        self._hook_dispatcher.register_before_compact(
            _legacy_context_adapter,
            label=getattr(hook, "__name__", "") or "legacy_compact_hook",
            legacy_hook=hook,
        )

    def register_before_compact_hook(
        self,
        hook: Callable[[BeforeCompactContext], None],
    ) -> None:
        self._hook_dispatcher.register_before_compact(hook)

    def register_message_added_hook(
        self,
        hook: Callable[[MessageAddedContext], None],
    ) -> None:
        self._hook_dispatcher.register_message_added(hook)

    def register_before_chat_hook(
        self,
        hook: Callable[[BeforeChatContext], None],
    ) -> None:
        self._hook_dispatcher.register_before_chat(hook)

    @property
    def llm_adapters(self) -> dict[str, Type[LLMAdapter]]:
        return dict(self._llm_adapters)

    @property
    def tts_adapters(self) -> dict[str, Type[TTSAdapter]]:
        return dict(self._tts_adapters)

    @property
    def asr_adapters(self) -> dict[str, Type[ASRAdapter]]:
        return dict(self._asr_adapters)

    @property
    def t2i_adapters(self) -> dict[str, Type[T2IAdapter]]:
        return dict(self._t2i_adapters)

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
    def frontend_config_contributions(self) -> list[FrontendConfigContribution]:
        return sorted(self._frontend_config_contributions, key=lambda c: c.order)

    @property
    def frontend_page_contributions(self) -> list[FrontendPageContribution]:
        return sorted(self._frontend_page_contributions, key=lambda c: c.order)

    @property
    def chat_ui_contributions(self) -> list[ChatUIContribution]:
        return sorted(self._chat_ui_contributions, key=lambda c: c.order)

    @property
    def dag_yaml_paths(self) -> list[str]:
        return [c.yaml_path for c in self._workflow_contributions]

    @property
    def workflow_contributions(self) -> list[WorkflowContribution]:
        return list(self._workflow_contributions)

    @property
    def output_contract_patches(self) -> list[OutputContractPatch]:
        return sorted(self._output_contract_patches, key=lambda p: p.priority)

    # [MemorySystem] 暴露已注册的精简前钩子列表
    @property
    def compact_hooks(self) -> list[Callable[[list], None]]:
        return list(self._hook_dispatcher.legacy_compact_hooks)

    def apply_llm_tools(self, tool_manager: ToolManager) -> None:
        for registrar in self._llm_tool_registrars:
            registrar(tool_manager)


# Backward-compatible name: plugins should type-hint this in ``initialize(register, ...)``.
PluginRegister = PluginCapabilityRegistry 
