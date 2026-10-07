"""Application-owned services shared by runtime composition roots."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from application.agent.execute_host_tool import AgentHostTool
    from application.agent.runtime import AgentRuntime
    from application.plugins.tools import PluginToolService


@dataclass
class ApplicationServices:
    agent: AgentRuntime | None = field(default=None, kw_only=True)
    plugin_tools: PluginToolService | None = field(default=None, kw_only=True)
    _closed: bool = field(default=False, init=False, repr=False)
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
            self.agent.start()

    def get_plugin_tools(self) -> PluginToolService:
        from application.plugins.tools import PluginToolService

        with self._lock:
            if self._closed:
                raise RuntimeError("Application services are closed")
            if self.plugin_tools is None:
                self.plugin_tools = PluginToolService()
            return self.plugin_tools

    def close(self) -> None:
        with self._lock:
            self._closed = True
            agent, plugin_tools = self.agent, self.plugin_tools
        # In-flight HTTP tools must be able to settle without this registry lock.
        if agent is not None:
            agent.close()
        if plugin_tools is not None:
            plugin_tools.close()
