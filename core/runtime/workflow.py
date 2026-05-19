from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
from queue import Queue
from typing import Any

from sdk.graph import Dag

DEFAULT_WORKFLOW_PATH = "assets/system/workflow/default.yaml"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _project_root() -> Path:
    env_root = os.environ.get("EASYAI_PROJECT_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return PROJECT_ROOT


def resolve_workflow_path(workflow_path: str | None = None) -> str:
    selected = (workflow_path or "").strip()
    if not selected:
        default_path = _project_root() / DEFAULT_WORKFLOW_PATH
        if default_path.is_file():
            return default_path.as_posix()
        selected = DEFAULT_WORKFLOW_PATH

    p = Path(selected).expanduser()
    if p.is_absolute():
        if not p.is_file():
            raise FileNotFoundError(f"Workflow file not found: {p}")
        return p.as_posix()

    cwd_path = p.resolve()
    if cwd_path.is_file():
        return cwd_path.as_posix()

    project_path = (_project_root() / p).resolve()
    if project_path.is_file():
        return project_path.as_posix()

    raise FileNotFoundError(f"Workflow file not found: {selected}")


@dataclass
class RuntimeWorkflow:
    """Runtime DAG plus named exports declared by the workflow."""

    dag: Dag
    exports: dict[str, Any]
    workflow_path: str

    def start(self) -> None:
        self.dag.start()

    def stop(self) -> None:
        self.dag.stop()

    def get_export(self, name: str) -> Any | None:
        return self.exports.get(name)

    def require_export(self, name: str) -> Any:
        value = self.get_export(name)
        if value is None:
            raise RuntimeError(f"Workflow export not found: {name}")
        return value


@dataclass
class ChatWorkflowHandles:
    """Optional handles used by the desktop chat surface."""

    input_queue: Any | None = None
    tts_queue: Any | None = None
    audio_queue: Any | None = None
    ui_worker: Any | None = None


def _resolve_exports(dag: Dag) -> dict[str, Any]:
    exports: dict[str, Any] = {}
    for name in dag.export_specs():
        exports[name] = dag.resolve_export(name)
    return exports


def build_runtime_workflow(
    *,
    workflow_path: str | None = None,
    queue_factory: Callable[[], Any] = Queue,
) -> RuntimeWorkflow:
    """Build the host runtime DAG and resolve its named exports."""

    dag = Dag(queue_factory=queue_factory)
    selected_workflow = resolve_workflow_path(workflow_path)
    dag.load_yaml(selected_workflow)

    dag.build()

    return RuntimeWorkflow(
        dag=dag,
        exports=_resolve_exports(dag),
        workflow_path=selected_workflow,
    )


def get_chat_workflow_handles(workflow: RuntimeWorkflow) -> ChatWorkflowHandles:
    return ChatWorkflowHandles(
        input_queue=workflow.get_export("chat.input"),
        tts_queue=workflow.get_export("chat.tts_input"),
        audio_queue=workflow.get_export("chat.audio_output"),
        ui_worker=workflow.get_export("chat.ui_worker"),
    )
