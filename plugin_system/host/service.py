"""Host integration for :mod:`sdk` plugins: lifecycle, runtime bindings, and contributions.

Call :func:`ensure_plugins_loaded` once per process after :class:`~config.config_manager.ConfigManager`
is available (``main`` entry and/or Settings UI). Safe to call multiple times (idempotent).
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
import logging
from pathlib import Path
from queue import Queue
from typing import TYPE_CHECKING, Any, Callable, List

from config.config_manager import ConfigManager
from plugin_system.host import manifest as _manifest
from plugin_system.host.builtin_plugins import register_builtin_plugins
from plugin_system.requirements.install import (
    ensure_plugin_site_packages_on_syspath,
    ensure_plugins_namespace_on_syspath,
)
from sdk.manager import PluginManager
from sdk.messages import UserInputMessage

if TYPE_CHECKING:
    from sdk.handlers import MessageHandler, UIOutputMessageHandler
    from sdk.hooks import PluginHookDispatcher
    from sdk.types import (
        ChatUIContribution,
        FrontendChatUIContribution,
        FrontendConfigContribution,
        FrontendPageContribution,
        OutputContractPatch,
        SettingsUIContribution,
        ToolsTabContribution,
        WorkflowContribution,
    )

logger = logging.getLogger(__name__)

_MANIFEST = Path("data/config/plugins.yaml")
_loaded: bool = False
_plugin_manager: PluginManager | None = None
_plugin_dialog_media_handlers: List["MessageHandler"] = []
_plugin_ui_handlers: List["UIOutputMessageHandler"] = []
_plugin_dag_yaml_paths: list[str] = []
_plugin_workflow_contributions: list["WorkflowContribution"] = []
_plugin_output_contract_patches: list["OutputContractPatch"] = []


@dataclass(frozen=True)
class PluginRuntimeBindings:
    """Concrete host capabilities supplied by an application composition root."""

    create_tool_manager: Callable[[], Any]
    configure_vision_fallbacks: Callable[[list[Any]], None]
    configure_avatar_formats: Callable[[list[Any]], None]
    configure_llm_adapters: Callable[[Mapping[str, Any]], None] | None = None
    configure_tts_adapters: Callable[[Mapping[str, Any]], None] | None = None
    configure_asr_adapters: Callable[[Mapping[str, Any]], None] | None = None
    configure_t2i_adapters: Callable[[Mapping[str, Any]], None] | None = None
    llm_adapters: MutableMapping[str, Any] | None = None
    tts_adapters: MutableMapping[str, Any] | None = None
    asr_adapters: MutableMapping[str, Any] | None = None
    t2i_adapters: MutableMapping[str, Any] | None = None
    register_mcp_tools: Callable[[Any], None] | None = None
    configure_model_assets: Callable[[list[Any]], None] | None = None
    configure_dialog_formats: Callable[[list[Any]], None] | None = None
    builtin_plugins: tuple[type[Any], ...] = ()


def get_plugin_manager() -> PluginManager | None:
    return _plugin_manager


def get_plugin_registry():
    """返回加载插件时使用的真实 PluginCapabilityRegistry 实例。"""
    mgr = _plugin_manager
    if mgr is None:
        return None
    return mgr.capabilities


def get_plugin_hook_dispatcher() -> "PluginHookDispatcher | None":
    mgr = _plugin_manager
    if mgr is None:
        return None
    return mgr.hook_dispatcher


def get_plugin_dialog_media_handlers() -> List["MessageHandler"]:
    return list(_plugin_dialog_media_handlers)


def get_plugin_tts_handlers() -> List["MessageHandler"]:
    """Compatibility alias for the former dialog-media extension name."""
    return get_plugin_dialog_media_handlers()


def get_plugin_ui_handlers() -> List["UIOutputMessageHandler"]:
    return list(_plugin_ui_handlers)


def get_plugin_dag_yaml_paths() -> list[str]:
    """Return plugin-registered workflow YAML paths (reserved; not yet wired into UX)."""
    return list(_plugin_dag_yaml_paths)


def get_plugin_workflow_contributions() -> list["WorkflowContribution"]:
    """Return plugin-registered workflow descriptors."""
    return list(_plugin_workflow_contributions)


def get_plugin_output_contract_patches(
    target_contract: str | None = None,
) -> list["OutputContractPatch"]:
    """Return plugin patches for LLM output contracts."""
    patches = list(_plugin_output_contract_patches)
    if target_contract is not None:
        patches = [p for p in patches if p.target_contract == target_contract]
    return patches


def bind_frontend_ui_runtime(
    emit_event: Callable[[dict[str, Any]], None] | None,
) -> None:
    """Bind plugin-scoped page presentation requests to the active Chat stream."""
    from sdk.frontend_ui import _bind_frontend_ui_dispatcher

    if emit_event is None:
        _bind_frontend_ui_dispatcher(None)
        return

    def dispatch(event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "").strip()
        plugin_id = str(event.get("pluginId") or "").strip()
        if event_type == "plugin.page.present":
            page_id = str(event.get("pageId") or "").strip()
            registered = any(
                str(getattr(contribution, "plugin_id", "") or "").strip() == plugin_id
                and str(getattr(contribution, "page_id", "") or "").strip() == page_id
                for contribution in collect_frontend_page_contributions()
            )
            if not registered:
                raise ValueError(
                    f"Plugin page is not registered by {plugin_id}: {page_id}"
                )
        elif event_type != "plugin.page.dismiss":
            raise ValueError(f"Unsupported plugin frontend event: {event_type}")
        emit_event(dict(event))

    _bind_frontend_ui_dispatcher(dispatch)


def bind_frontend_user_input_runtime(
    emit_event: Callable[[dict[str, Any]], None] | None,
) -> None:
    """Bind plugin frontend-action input requests to the active Chat transport."""
    from sdk.frontend_user_input import _bind_frontend_user_input_dispatcher

    if emit_event is None:
        _bind_frontend_user_input_dispatcher(None)
        return

    def dispatch(event: dict[str, Any]) -> None:
        if str(event.get("type") or "").strip() != "plugin.user-input.submit":
            raise ValueError("Unsupported plugin frontend user-input event")
        plugin_id = str(event.get("pluginId") or "").strip()
        text = str(event.get("text") or "").strip()
        if not plugin_id or not text:
            raise ValueError("Plugin frontend user input requires pluginId and text")
        emit_event(dict(event))

    _bind_frontend_user_input_dispatcher(dispatch)


def bind_perception_runtime(
    ingest_payload: Callable[[dict[str, Any]], Any] | None,
) -> None:
    """Bind plugin game-state/frame perception pushes to the active runtime."""
    from sdk.perception import _bind_perception_dispatcher

    if ingest_payload is None:
        _bind_perception_dispatcher(None)
        return

    def dispatch(payload: dict[str, Any]) -> bool:
        result = ingest_payload(dict(payload))
        return True if result is None else bool(result)

    _bind_perception_dispatcher(dispatch)


def bind_model_assets_runtime(
    dispatch_command: Callable[[dict[str, Any]], dict[str, Any]] | None,
) -> None:
    """Bind plugin model-asset status and download calls to the host service."""
    from sdk.model_assets import _bind_model_assets_dispatcher

    if dispatch_command is None:
        _bind_model_assets_dispatcher(None)
        return

    def dispatch(command: dict[str, Any]) -> dict[str, Any]:
        return dict(dispatch_command(dict(command)))

    _bind_model_assets_dispatcher(dispatch)


def _apply_plugin_adapters(
    apply_fn: Callable[[MutableMapping[str, Any]], None],
    *,
    configure: Callable[[Mapping[str, Any]], None] | None,
    legacy_target: MutableMapping[str, Any] | None,
    label: str,
) -> None:
    try:
        if configure is not None:
            collected: dict[str, Any] = {}
            apply_fn(collected)
            configure(collected)
        elif legacy_target is not None:
            apply_fn(legacy_target)
    except Exception:
        logger.exception("%s failed", label)


def ensure_plugins_loaded(
    config: ConfigManager | None = None,
    *,
    runtime_bindings: PluginRuntimeBindings | None = None,
) -> PluginManager | None:
    """Load ``data/config/plugins.yaml``, instantiate plugins, and apply runtime bindings."""
    global _loaded, _plugin_manager
    global _plugin_dialog_media_handlers, _plugin_ui_handlers
    global _plugin_dag_yaml_paths
    global _plugin_workflow_contributions, _plugin_output_contract_patches
    if _loaded:
        return _plugin_manager

    ensure_plugins_namespace_on_syspath()
    ensure_plugin_site_packages_on_syspath()

    mgr = PluginManager()
    register_builtin_plugins(
        mgr,
        extra_plugins=(
            runtime_bindings.builtin_plugins
            if runtime_bindings is not None
            else ()
        ),
    )
    if _MANIFEST.is_file():
        try:
            mgr.load_manifest_file(_MANIFEST)
        except Exception:
            logger.exception("Failed to load plugin manifest %s", _MANIFEST)
    mgr.instantiate_all()
    cfg = config if config is not None else ConfigManager()
    mgr.load_own_config_all(app_config=cfg)
    if runtime_bindings is not None:
        _apply_plugin_adapters(
            mgr.apply_llm_providers,
            configure=runtime_bindings.configure_llm_adapters,
            legacy_target=runtime_bindings.llm_adapters,
            label="apply_llm_providers",
        )
        _apply_plugin_adapters(
            mgr.apply_tts_providers,
            configure=runtime_bindings.configure_tts_adapters,
            legacy_target=runtime_bindings.tts_adapters,
            label="apply_tts_providers",
        )
        _apply_plugin_adapters(
            mgr.apply_asr_providers,
            configure=runtime_bindings.configure_asr_adapters,
            legacy_target=runtime_bindings.asr_adapters,
            label="apply_asr_providers",
        )
        _apply_plugin_adapters(
            mgr.apply_t2i_providers,
            configure=runtime_bindings.configure_t2i_adapters,
            legacy_target=runtime_bindings.t2i_adapters,
            label="apply_t2i_providers",
        )
        try:
            runtime_bindings.configure_vision_fallbacks(
                mgr.collect_vision_fallbacks()
            )
        except Exception:
            logger.exception("collect_vision_fallbacks failed")
        try:
            runtime_bindings.configure_avatar_formats(mgr.collect_avatar_formats())
        except Exception:
            logger.exception("collect_avatar_formats failed")
        if runtime_bindings.configure_dialog_formats is not None:
            try:
                runtime_bindings.configure_dialog_formats(mgr.collect_dialog_formats())
            except Exception:
                logger.exception("collect_dialog_formats failed")
        if runtime_bindings.configure_model_assets is not None:
            try:
                runtime_bindings.configure_model_assets(mgr.collect_model_assets())
            except Exception:
                logger.exception("collect_model_assets failed")
        try:
            from sdk.tool_registry import apply_registered_tools

            tool_manager = runtime_bindings.create_tool_manager()
            apply_registered_tools(tool_manager)
            mgr.apply_llm_tools(tool_manager)
            if runtime_bindings.register_mcp_tools is not None:
                runtime_bindings.register_mcp_tools(tool_manager)
        except ImportError:
            logger.info(
                "MCP tools skipped: install optional dependency 'mcp' to enable "
                "data/config/mcp.yaml"
            )
        except Exception:
            logger.exception("apply_llm_tools failed")

    try:
        dialog_media, ui = mgr.collect_message_handlers()
        _plugin_dialog_media_handlers = dialog_media
        _plugin_ui_handlers = ui
    except Exception:
        logger.exception("collect_message_handlers failed")
        _plugin_dialog_media_handlers = []
        _plugin_ui_handlers = []
    try:
        _plugin_dag_yaml_paths = mgr.collect_dag_yaml_paths()
    except Exception:
        logger.exception("collect_dag_yaml_paths failed")
        _plugin_dag_yaml_paths = []
    try:
        _plugin_workflow_contributions = mgr.collect_workflow_contributions()
    except Exception:
        logger.exception("collect_workflow_contributions failed")
        _plugin_workflow_contributions = []
    try:
        _plugin_output_contract_patches = mgr.collect_output_contract_patches()
    except Exception:
        logger.exception("collect_output_contract_patches failed")
        _plugin_output_contract_patches = []

    _plugin_manager = mgr
    _loaded = True
    return _plugin_manager


def wire_user_input_plugins(
    user_input_queue: Queue,
    *,
    sink: Callable[..., None] | None = None,
) -> Callable[..., bool]:
    """Build the user-input pipeline and return ``emit_user_text``."""
    mgr = _plugin_manager
    processors: list[Callable[[str], str | None]] = []

    def emit_user_text(
        text: str, *, attachments: list[dict[str, Any]] | None = None
    ) -> bool:
        t = text
        for proc in processors:
            try:
                out = proc(t)
            except Exception:
                logger.exception("user_input processor failed")
                return False
            if out is None:
                return False
            t = out
        attachment_payloads = list(attachments or [])
        if sink is not None:
            sink(t, attachments=attachment_payloads)
        else:
            user_input_queue.put(
                UserInputMessage(text=t, attachments=attachment_payloads)
            )
        return True

    if mgr is not None:
        try:
            mgr.wire_user_input(emit_user_text, processors)
        except Exception:
            logger.exception("wire_user_input failed")
    return emit_user_text


def collect_settings_contributions() -> List["SettingsUIContribution"]:
    """Deprecated compatibility endpoint; the host never loads Qt settings UI."""
    return []


def collect_tools_tab_contributions() -> List["ToolsTabContribution"]:
    """Deprecated compatibility endpoint; the host never loads Qt tools UI."""
    return []


def collect_frontend_config_contributions() -> List["FrontendConfigContribution"]:
    mgr = _plugin_manager
    if mgr is None:
        return []
    try:
        return mgr.collect_frontend_config_contributions()
    except Exception:
        logger.exception("collect_frontend_config_contributions failed")
        return []


def collect_frontend_page_contributions() -> List["FrontendPageContribution"]:
    mgr = _plugin_manager
    if mgr is None:
        return []
    try:
        return mgr.collect_frontend_page_contributions()
    except Exception:
        logger.exception("collect_frontend_page_contributions failed")
        return []


def collect_frontend_chat_ui_contributions() -> List["FrontendChatUIContribution"]:
    mgr = _plugin_manager
    if mgr is None:
        return []
    try:
        return mgr.collect_frontend_chat_ui_contributions()
    except Exception:
        logger.exception("collect_frontend_chat_ui_contributions failed")
        return []


def collect_chat_ui_contributions() -> List["ChatUIContribution"]:
    """Deprecated compatibility endpoint; the host never loads Qt chat UI."""
    return []


def read_plugin_manifest_items(path: Path | None = None) -> list[dict[str, Any]]:
    return _manifest.read_plugin_manifest_items(path if path is not None else _MANIFEST)


def write_plugin_manifest_items(
    items: list[dict[str, Any]], path: Path | None = None
) -> None:
    _manifest.write_plugin_manifest_items(items, path if path is not None else _MANIFEST)


def set_plugin_manifest_enabled(
    entry: str, enabled: bool, path: Path | None = None
) -> bool:
    return _manifest.set_plugin_manifest_enabled(
        entry, enabled, path if path is not None else _MANIFEST
    )


def normalize_manifest_entry(entry: str) -> str:
    return _manifest.normalize_manifest_entry(entry)


def remove_plugin_manifest_entry(entry: str, path: Path | None = None) -> bool:
    return _manifest.remove_plugin_manifest_entry(
        entry, path if path is not None else _MANIFEST
    )


def infer_plugin_package_directory(entry: str) -> Path | None:
    return _manifest.infer_plugin_package_directory(entry)


def append_plugin_manifest_entry_if_missing(
    entry: str,
    *,
    enabled: bool = True,
    path: Path | None = None,
) -> str:
    return _manifest.append_plugin_manifest_entry_if_missing(
        entry,
        enabled=enabled,
        path=path if path is not None else _MANIFEST,
    )
