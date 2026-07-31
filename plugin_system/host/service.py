"""
Host integration for :mod:`sdk` plugins: load manifest, merge factories/tools/handlers,
and expose contributions for Settings / Tools / Chat UI.

Call :func:`ensure_plugins_loaded` once per process after :class:`~config.config_manager.ConfigManager`
is available (``main`` entry and/or Settings UI). Safe to call multiple times (idempotent).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from threading import RLock
from typing import TYPE_CHECKING, Any, Callable, List, Optional

import yaml

from config.config_manager import ConfigManager
from sdk.messages import UserInputMessage
from sdk.file_transactions import atomic_write_text, read_text_without_links
from sdk.path_contract import (
    managed_project_directory,
    managed_project_storage,
    project_root,
    resolve_managed_project_path,
    resolve_project_path,
    resolve_project_read_path,
)
from plugin_system.requirements.install import (
    ensure_plugin_site_packages_on_syspath,
    ensure_plugins_namespace_on_syspath,
)
from sdk.manager import PluginManager

if TYPE_CHECKING:
    from sdk.hooks import PluginHookDispatcher
    from sdk.handlers import MessageHandler, UIOutputMessageHandler
    from sdk.types import (
        ChatUIContribution,
        FrontendConfigContribution,
        FrontendChatUIContribution,
        FrontendPageContribution,
        OutputContractPatch,
        SettingsUIContribution,
        ToolsTabContribution,
        WorkflowContribution,
    )

logger = logging.getLogger(__name__)

_MANIFEST = Path("data/config/plugins.yaml")
_loaded: bool = False
_loaded_project_root: Path | None = None
_plugin_manager: PluginManager | None = None
_plugin_tts_handlers: List["MessageHandler"] = []
_plugin_ui_handlers: List["UIOutputMessageHandler"] = []
_plugin_dag_yaml_paths: list[str] = []
_plugin_workflow_contributions: list["WorkflowContribution"] = []
_plugin_output_contract_patches: list["OutputContractPatch"] = []
_PLUGIN_MANIFEST_LOCK = RLock()


def _exact_manifest_entry(entry: str) -> str:
    """Validate a plugin import entry without changing its identity."""

    raw = str(entry or "")
    if not raw:
        return ""
    if raw != raw.strip() or any(
        ord(character) < 32
        or ord(character) == 127
        or 0xD800 <= ord(character) <= 0xDFFF
        for character in raw
    ):
        raise ValueError(
            "plugin manifest entry must not contain surrounding whitespace "
            "or control characters"
        )
    return raw


def _plugin_manifest_path(
    path: Path | None = None,
    *,
    root: str | Path | None = None,
) -> Path:
    configured = path if path is not None else _MANIFEST
    active_root = (
        project_root()
        if root is None
        else resolve_project_path(".", root=root)
    )
    raw = os.fspath(configured)
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        try:
            candidate.relative_to(active_root)
        except ValueError:
            return resolve_project_read_path(raw, root=active_root)
        return resolve_managed_project_path(raw, root=active_root)
    return resolve_managed_project_path(raw, root=active_root)


@dataclass(frozen=True)
class PluginRuntimeBindings:
    """Concrete host capabilities supplied by an application composition root."""

    llm_adapters: dict[str, Any]
    tts_adapters: dict[str, Any]
    asr_adapters: dict[str, Any]
    t2i_adapters: dict[str, Any]
    create_tool_manager: Callable[[], Any]
    configure_vision_fallbacks: Callable[[list[Any]], None]
    register_mcp_tools: Callable[[Any], None] | None = None


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


def get_plugin_tts_handlers() -> List["MessageHandler"]:
    return list(_plugin_tts_handlers)


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
                str(getattr(contribution, "plugin_id", "") or "").strip()
                == plugin_id
                and str(getattr(contribution, "page_id", "") or "").strip()
                == page_id
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


def ensure_plugins_loaded(
    config: ConfigManager | None = None,
    *,
    runtime_bindings: PluginRuntimeBindings | None = None,
    root: str | Path | None = None,
) -> PluginManager | None:
    """
    Load ``data/config/plugins.yaml`` if present, instantiate plugins, merge adapter
    providers and vision fallbacks, register tools on the global ToolManager, and
    cache message handlers for :mod:`application.chat.handlers.registry`.
    """
    global _loaded, _loaded_project_root, _plugin_manager
    global _plugin_tts_handlers, _plugin_ui_handlers
    global _plugin_dag_yaml_paths
    global _plugin_workflow_contributions, _plugin_output_contract_patches
    configured_root = root
    if configured_root is None and config is not None:
        configured_root = getattr(config, "_project_root", None)
    active_root = (
        project_root()
        if configured_root is None
        else resolve_project_path(".", root=configured_root)
    )
    if _loaded:
        if (
            _loaded_project_root is not None
            and _loaded_project_root != active_root
        ):
            raise RuntimeError(
                "plugins are already loaded for a different project root"
            )
        return _plugin_manager

    ensure_plugins_namespace_on_syspath(root=active_root)
    ensure_plugin_site_packages_on_syspath(root=active_root)

    manifest = _plugin_manifest_path(root=active_root)
    mgr = PluginManager(
        plugin_data_root=managed_project_storage(
            "data/plugins",
            root=active_root,
        ),
        root=active_root,
    )
    if manifest.is_file():
        try:
            mgr.load_manifest_file(manifest)
        except Exception:
            logger.exception("Failed to load plugin manifest %s", manifest)
    mgr.instantiate_all()
    cfg = config if config is not None else ConfigManager()
    mgr.load_own_config_all(app_config=cfg)
    if runtime_bindings is not None:
        try:
            mgr.apply_llm_providers(runtime_bindings.llm_adapters)
        except Exception:
            logger.exception("apply_llm_providers failed")
        try:
            mgr.apply_tts_providers(runtime_bindings.tts_adapters)
        except Exception:
            logger.exception("apply_tts_providers failed")
        try:
            mgr.apply_asr_providers(runtime_bindings.asr_adapters)
        except Exception:
            logger.exception("apply_asr_providers failed")
        try:
            mgr.apply_t2i_providers(runtime_bindings.t2i_adapters)
        except Exception:
            logger.exception("apply_t2i_providers failed")
        try:
            runtime_bindings.configure_vision_fallbacks(
                mgr.collect_vision_fallbacks()
            )
        except Exception:
            logger.exception("collect_vision_fallbacks failed")
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
        tts, ui = mgr.collect_message_handlers()
        _plugin_tts_handlers = tts
        _plugin_ui_handlers = ui
    except Exception:
        logger.exception("collect_message_handlers failed")
        _plugin_tts_handlers = []
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
    _loaded_project_root = active_root
    _loaded = True
    return _plugin_manager


def wire_user_input_plugins(
    user_input_queue: Queue,
    *,
    sink: Callable[..., None] | None = None,
) -> Callable[..., bool]:
    """
    Build the user-input pipeline (plugin processors) and return ``emit_user_text``
    for code that registers hooks via :meth:`sdk.register.PluginCapabilityRegistry.register_user_input_trigger`
    or :meth:`~sdk.register.PluginCapabilityRegistry.register_user_input_processor` inside
    :meth:`sdk.plugin.PluginBase.initialize`.

    The returned callable runs processors and delegates the processed text to
    ``sink``.  Without a custom sink it preserves the historical behavior of
    enqueuing :class:`~sdk.messages.UserInputMessage` directly.
    """
    mgr = _plugin_manager
    processors: list[Callable[[str], str | None]] = []

    def emit_user_text(text: str, *, attachments: list[dict[str, Any]] | None = None) -> bool:
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
            user_input_queue.put(UserInputMessage(text=t, attachments=attachment_payloads))
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


def read_plugin_manifest_items(
    path: Path | None = None,
    *,
    root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """
    Return manifest rows as mutable dicts (shallow copy each), preserving list order.
    Only includes dict items with a non-empty string ``entry``.
    """
    with _PLUGIN_MANIFEST_LOCK:
        p = _plugin_manifest_path(path, root=root)
        if not p.is_file():
            return []
        try:
            raw = yaml.safe_load(read_text_without_links(p))
        except Exception:
            logger.exception("Failed to parse plugin manifest %s", p)
            return []
    if raw is None:
        return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        entry = item.get("entry")
        if not isinstance(entry, str):
            continue
        try:
            if not _exact_manifest_entry(entry):
                continue
        except ValueError:
            logger.warning("Ignoring invalid plugin manifest entry %r", entry)
            continue
        out.append(dict(item))
    return out


def write_plugin_manifest_items(
    items: list[dict[str, Any]],
    path: Path | None = None,
    *,
    root: str | Path | None = None,
) -> None:
    """Overwrite manifest with ``items`` (YAML list of mappings)."""
    with _PLUGIN_MANIFEST_LOCK:
        for item in items:
            entry = item.get("entry") if isinstance(item, dict) else None
            if not isinstance(entry, str) or not _exact_manifest_entry(entry):
                raise ValueError("plugin manifest items require an exact entry")
        p = _plugin_manifest_path(path, root=root)
        p.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(
            items,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
        atomic_write_text(p, text)


def set_plugin_manifest_enabled(
    entry: str,
    enabled: bool,
    path: Path | None = None,
    *,
    root: str | Path | None = None,
) -> bool:
    """
    Set ``enabled`` on the manifest row whose ``entry`` matches (strip-wise).
    Returns True if a row was updated and the file was written.
    """
    with _PLUGIN_MANIFEST_LOCK:
        items = read_plugin_manifest_items(path, root=root)
        norm = _exact_manifest_entry(entry)
        if not norm:
            return False
        changed = False
        for item in items:
            e = item.get("entry")
            if isinstance(e, str) and e == norm:
                item["enabled"] = bool(enabled)
                changed = True
                break
        if changed:
            write_plugin_manifest_items(items, path, root=root)
        return changed


def normalize_manifest_entry(entry: str) -> str:
    """
    Registry rows often omit the repo-local package root; downloaded plugins live under
    ``plugins/``, so ensure ``entry`` uses the ``plugins.`` module prefix when absent.
    """
    norm = _exact_manifest_entry(entry)
    if not norm:
        return norm
    if norm.startswith("plugins."):
        return norm
    return f"plugins.{norm}"


def remove_plugin_manifest_entry(
    entry: str,
    path: Path | None = None,
    *,
    root: str | Path | None = None,
) -> bool:
    """
    Remove the manifest row whose ``entry`` matches (strip-wise).
    Returns True if a row was removed and the file was written.
    """
    with _PLUGIN_MANIFEST_LOCK:
        norm = _exact_manifest_entry(entry)
        if not norm:
            return False
        items = read_plugin_manifest_items(path, root=root)
        kept: list[dict[str, Any]] = []
        removed = False
        for item in items:
            e = item.get("entry")
            if isinstance(e, str) and e == norm:
                removed = True
                continue
            kept.append(item)
        if not removed:
            return False
        write_plugin_manifest_items(kept, path, root=root)
        return True


def infer_plugin_package_directory(
    entry: str,
    *,
    root: str | Path | None = None,
) -> Path | None:
    """
    Map manifest ``entry`` module path to ``plugins/<top-level-package>/``.

    Example: ``plugins.whisper_asr.plugin:WhisperAsrPlugin`` → ``plugins/whisper_asr``.
    """
    try:
        return managed_plugin_package_directory(entry, root=root)
    except (OSError, PermissionError, ValueError):
        return None


def managed_plugin_package_directory(
    entry: str,
    *,
    root: str | Path | None = None,
) -> Path | None:
    """Return the strict managed package directory for a manifest entry."""

    raw = _exact_manifest_entry(entry)
    if not raw:
        return None
    mod = raw.split(":", 1)[0]
    if not mod or mod != mod.strip():
        raise ValueError("plugin module entry is not exact")
    if not mod.startswith("plugins."):
        mod = normalize_manifest_entry(mod)
    if not mod.startswith("plugins."):
        return None
    rest = mod[len("plugins.") :]
    if not rest:
        return None
    top = rest.split(".", 1)[0]
    if not top:
        return None
    return managed_project_directory(
        "plugins",
        top,
        root=project_root() if root is None else root,
    )


def append_plugin_manifest_entry_if_missing(
    entry: str,
    *,
    enabled: bool = True,
    path: Path | None = None,
    root: str | Path | None = None,
) -> str:
    """
    Append ``- entry: …`` row if not already present (strip-wise match on entry).

    ``entry`` is normalized with :func:`normalize_manifest_entry` (``plugins.`` prefix).

    Returns ``"added"`` | ``"exists"`` | ``"empty"``.
    """
    norm = normalize_manifest_entry(entry)
    if not norm:
        return "empty"
    with _PLUGIN_MANIFEST_LOCK:
        items = read_plugin_manifest_items(path, root=root)
        for item in items:
            e = item.get("entry")
            if isinstance(e, str) and e == norm:
                return "exists"
        items.append({"entry": norm, "enabled": bool(enabled)})
        write_plugin_manifest_items(items, path, root=root)
        return "added"
