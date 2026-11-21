"""Application-owned services shared by runtime composition roots."""

from __future__ import annotations

import contextlib
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from application.agent.execute_host_tool import AgentHostTool
    from application.agent.runtime import AgentRuntime
    from application.plugins.tools import PluginToolService
    from application.runtime.stores import AppStores


@dataclass
class ApplicationServices:
    agent: AgentRuntime | None = field(default=None, kw_only=True)
    plugin_tools: PluginToolService | None = field(default=None, kw_only=True)
    stores: AppStores | None = field(default=None, kw_only=True)
    _closed: bool = field(default=False, init=False, repr=False)
    _runtimes_closed: bool = field(default=False, init=False, repr=False)
    _lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )

    def start_agent(
        self, config_manager, root: str | Path, *, tools: tuple[AgentHostTool, ...] = ()
    ) -> None:
        from application.agent.runtime import AgentRuntime

        with self._lock:
            if self._closed:
                raise RuntimeError("Application services are closed")
            if self.agent is None:
                self.agent = AgentRuntime(config_manager, root, tools=tools)
            if self.stores is not None:
                bind_hub = getattr(self.agent, "bind_storage_hub", None)
                if callable(bind_hub):
                    bind_hub(self.stores.hub)
            self.agent.start()

    def get_plugin_tools(self) -> PluginToolService:
        from application.plugins.tools import PluginToolService

        with self._lock:
            if self._closed:
                raise RuntimeError("Application services are closed")
            if self.plugin_tools is None:
                self.plugin_tools = PluginToolService()
            return self.plugin_tools

    def close_runtimes(self) -> None:
        """Close active worker runtimes while keeping ``AppStores`` open for bridge drain."""
        with self._lock:
            self._closed = True
            if self._runtimes_closed:
                return
            self._runtimes_closed = True
            agent, plugin_tools = self.agent, self.plugin_tools
        # In-flight HTTP tools must be able to settle without this registry lock.
        if agent is not None:
            agent.close()
        if plugin_tools is not None:
            plugin_tools.close()

    def close(self) -> None:
        self.close_runtimes()
        with self._lock:
            stores = self.stores
            self.stores = None
        if stores is not None:
            with contextlib.suppress(Exception):
                from application.memory.manage_memories import shutdown_memory_runtime

                shutdown_memory_runtime()
            with contextlib.suppress(Exception):
                from application.knowledge.runtime import shutdown_knowledge_runtime

                shutdown_knowledge_runtime()
            with contextlib.suppress(Exception):
                from core.chat_history.sqlite_session_store import close_all_session_stores

                close_all_session_stores()
            stores.close()
