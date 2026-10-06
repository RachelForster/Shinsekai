"""Application-owned services shared by runtime composition roots."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from application.agent.execute_host_tool import AgentHostTool
    from application.agent.runtime import AgentRuntime


@dataclass
class ApplicationServices:
    agent: AgentRuntime | None = field(default=None, kw_only=True)
    _lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )

    def start_agent(
        self, config_manager, root: str | Path, *, tools: tuple[AgentHostTool, ...] = ()
    ) -> None:
        from application.agent.runtime import AgentRuntime

        with self._lock:
            if self.agent is None:
                self.agent = AgentRuntime(config_manager, root, tools=tools)
            self.agent.start()

    def close(self) -> None:
        with self._lock:
            if self.agent is not None:
                self.agent.close()
