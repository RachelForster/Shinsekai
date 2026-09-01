"""Bridge adapter for plugin installation progress."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from application.runtime.state import BridgeState
from application.runtime.tasks import _append_task_log, _update_task


@dataclass(slots=True)
class BridgePluginInstallProgress:
    state: BridgeState
    task_id: str

    def update(self, **changes: Any) -> None:
        _update_task(self.state, self.task_id, **changes)

    def append_log(self, line: str) -> None:
        _append_task_log(self.state, self.task_id, line)
