"""
Abstract plugin base for Easy AI Desktop Assistant.

Subclass :class:`ShinsekaiPlugin`, implement **every** abstract method, then register
the class with :class:`sdk.manager.PluginManager` or load it from a manifest.

**Lifecycle (typical host integration)**

1. Construct :class:`~sdk.manager.PluginManager` and call ``load_from_descriptors``
   or ``register_plugin_class``.
2. Call :meth:`load_own_config` on each plugin (after app ``ConfigManager`` exists
   if you need it).
3. Merge :meth:`customize_llm_adapter` / :meth:`customize_tts_adapter` dicts into
   your factories **before** creating adapters.
4. Call :meth:`add_llm_tools` with the shared :class:`~llm.tools.tool_manager.ToolManager`.
5. Extend handler lists with :meth:`add_message_handler`, then build dispatchers.
6. Call :meth:`trigger_user_input` and :meth:`handle_user_input` with the host’s
   callables so plugins can inject or preprocess chat input.
7. Append contributions from :meth:`add_settings_ui_widgets`, :meth:`add_tools_tab`,
   :meth:`add_desktop_ui_widgets` into your UI shell.

If a capability does not apply, implement the method as a no-op (e.g. do not
mutate the passed lists / mappings).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, MutableMapping
from pathlib import Path
from typing import TYPE_CHECKING, Type

from core.handler_registry import MessageHandler, UIOutputMessageHandler
from llm.llm_adapter import LLMAdapter
from llm.tools.tool_manager import ToolManager
from tts.tts_adapter import TTSAdapter

from sdk.types import (
    DesktopUIContribution,
    SettingsUIContribution,
    ToolsTabContribution,
)

if TYPE_CHECKING:
    from config.config_manager import ConfigManager


class ShinsekaiPlugin(ABC):
    """
    Base class for third-party or in-tree extensions.

    **Naming:** Override :meth:`plugin_id` and :meth:`plugin_version` for logs
    and conflict detection. ``plugin_id`` should be stable (reverse-DNS style
    recommended), not the display name.
    """

    # --- metadata ---

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Unique stable id, e.g. ``com.example.myplugin``."""

    @property
    def plugin_version(self) -> str:
        """Semantic version string; override if you ship a real plugin."""
        return "0.0.0"

    # --- config ---

    @abstractmethod
    def load_own_config(
        self,
        plugin_root: Path,
        app_config: ConfigManager | None = None,
    ) -> None:
        """
        Load YAML/JSON or other files stored under the plugin directory.

        **Parameters**

        - ``plugin_root``: Directory reserved for this plugin (e.g.
          ``customize/plugins/<plugin_id>/``). Create it on first run if missing.
        - ``app_config``: The app singleton :class:`~config.config_manager.ConfigManager`
          if the host passes it; use read-only access unless your integration
          documents writes.

        **Typical pattern**

        .. code-block:: python

            def load_own_config(self, plugin_root, app_config=None):
                cfg_path = plugin_root / "plugin.yaml"
                if cfg_path.exists():
                    # parse and cache on self
                    ...
        """

    # --- LLM / TTS adapters ---

    @abstractmethod
    def customize_llm_adapter(
        self,
        providers: MutableMapping[str, Type[LLMAdapter]],
    ) -> None:
        """
        Register extra LLM provider names mapped to adapter **classes**
        (not instances), matching :class:`~llm.llm_manager.LLMAdapterFactory`.

        **How to use**

        - Keys are the strings users select as “provider” (same namespace as
          built-in ``Deepseek``, ``ChatGPT``, …).
        - Values must be subclasses of :class:`~llm.llm_adapter.LLMAdapter` with
          a constructor compatible with how your host builds kwargs (API key,
          base URL, model name).

        **Example**

        .. code-block:: python

            def customize_llm_adapter(self, providers):
                providers["MyHostLLM"] = MyHostLLMAdapter
        """

    @abstractmethod
    def customize_tts_adapter(
        self,
        providers: MutableMapping[str, Type[TTSAdapter]],
    ) -> None:
        """
        Register TTS backends the same way as :class:`~tts.tts_manager.TTSAdapterFactory`
        (lowercase keys are conventional).

        Subclasses must implement :meth:`~tts.tts_adapter.TTSAdapter.generate_speech`
        and :meth:`~tts.tts_adapter.TTSAdapter.switch_model`.
        """

    # --- LLM tools (function calling) ---

    @abstractmethod
    def add_llm_tools(self, tool_manager: ToolManager) -> None:
        """
        Register tools on the process-wide :class:`~llm.tools.tool_manager.ToolManager`.

        Prefer the ``@tool_manager.tool`` decorator on module-level functions,
        or call ``tool_manager.tool(fn)`` manually. Names must be unique across
        the whole app.

        **Note:** Tool definitions are collected when the LLM stack starts;
        register tools before :class:`~llm.llm_manager.LLMManager` reads
        ``get_definitions()``.
        """

    # --- Message pipeline (TTS + UI) ---

    @abstractmethod
    def add_message_handler(
        self,
        tts_handlers: list[MessageHandler],
        ui_handlers: list[UIOutputMessageHandler],
    ) -> None:
        """
        Append handlers for the two dispatcher chains in ``core.handler_registry``.

        **TTS chain** (``TtsMessageDispatcher``): consumes
        :class:`~core.message.LLMDialogMessage`. Implement
        :class:`~core.handler_registry.MessageHandler` — at minimum
        ``can_handle`` plus ``handle`` / ``pre_process`` / ``post_process``.

        **UI chain** (``UiOutputMessageDispatcher``): consumes
        :class:`~core.message.TTSOutputMessage`. Implement
        :class:`~core.handler_registry.UIOutputMessageHandler``.

        Append **in priority order** (first match wins). The host should keep a
        default catch-all handler last.

        **Example**

        .. code-block:: python

            def add_message_handler(self, tts_handlers, ui_handlers):
                tts_handlers.append(MyDialogFilter())
                ui_handlers.append(MySubtitleOverlay())
        """

    # --- User input: inject + preprocess ---

    @abstractmethod
    def trigger_user_input(self, emit_user_text: Callable[[str], None]) -> None:
        """
        Called once during startup so the plugin can **inject** user messages.

        Store ``emit_user_text`` and call it whenever the plugin wants to push
        text into the same pipeline as the chat input box (e.g. hotkey, external
        API, automation). The host should enqueue :class:`~core.message.UserInputMessage`
        or equivalent.

        If you do not inject text, implement with ``pass``.

        **Threading:** Only call ``emit_user_text`` from the thread the host
        documents (usually Qt main thread).
        """

    @abstractmethod
    def handle_user_input(
        self,
        processors: list[Callable[[str], str | None]],
    ) -> None:
        """
        Register **preprocessors** for raw user chat text before it reaches the LLM.

        Append callables ``(text: str) -> str | None``:

        - Return ``str`` to replace the message (middleware chain; host defines
          whether all processors run or short-circuits).
        - Return ``None`` to drop the message (host may show a toast).

        This is separate from :meth:`add_message_handler`, which runs on **LLM/TTS
        structured messages**, not the initial user string.

        **Example**

        .. code-block:: python

            def handle_user_input(self, processors):
                def strip_commands(t: str):
                    return t.removeprefix("/echo ").strip() or t
                processors.append(strip_commands)
        """

    # --- Settings / Tools / Desktop UI ---

    @abstractmethod
    def add_settings_ui_widgets(
        self,
        contributions: list[SettingsUIContribution],
    ) -> None:
        """
        Declare extra settings pages.

        Append :class:`~sdk.types.SettingsUIContribution` objects. The host
        should add ``nav_label`` to the settings sidebar and show ``build(ctx)``
        in the stacked widget when selected.
        """

    @abstractmethod
    def add_tools_tab(self, contributions: list[ToolsTabContribution]) -> None:
        """
        Declare extra tabs in the tools area (typically under Settings → Tools).

        Use :class:`~sdk.types.ToolsTabContribution` with a unique ``tab_id``.
        """

    @abstractmethod
    def add_desktop_ui_widgets(
        self,
        contributions: list[DesktopUIContribution],
    ) -> None:
        """
        Declare widgets to embed in :class:`~ui.desktop_ui.DesktopAssistantWindow`.

        Use ``placement`` hints understood by your host (documented per app
        build). ``build`` receives the live window for signal connections.
        """
