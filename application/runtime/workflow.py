"""Build and expose the configured application runtime workflow."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from queue import Queue
from pathlib import Path
from typing import Any

from core.paths import resource_path
from sdk.graph import Dag

DEFAULT_WORKFLOW_PATH = "assets/system/workflow/default.yaml"


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
    dialog_queue: Any | None = None
    presentation_queue: Any | None = None
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
    selected_workflow = (workflow_path or "").strip()

    selected_workflow = selected_workflow or DEFAULT_WORKFLOW_PATH
    selected_workflow = _resolve_workflow_path(selected_workflow)
    dag.load_yaml(selected_workflow)

    dag.build()

    return RuntimeWorkflow(
        dag=dag,
        exports=_resolve_exports(dag),
        workflow_path=selected_workflow,
    )


def _resolve_workflow_path(workflow_path: str) -> str:
    if "\n" in workflow_path or "\r" in workflow_path:
        return workflow_path
    path = Path(workflow_path).expanduser()
    if path.is_absolute() or path.is_file():
        return str(path)
    return str(resource_path(path))


def _get_first_export(workflow: RuntimeWorkflow, *names: str) -> Any | None:
    for name in names:
        value = workflow.get_export(name)
        if value is not None:
            return value
    return None


def get_chat_workflow_handles(workflow: RuntimeWorkflow) -> ChatWorkflowHandles:
    return ChatWorkflowHandles(
        input_queue=workflow.get_export("chat.input"),
        dialog_queue=_get_first_export(
            workflow,
            "chat.dialog_input",
            "chat.tts_input",
        ),
        presentation_queue=_get_first_export(
            workflow,
            "chat.presentation_input",
            "chat.audio_output",
        ),
        ui_worker=workflow.get_export("chat.ui_worker"),
    )
