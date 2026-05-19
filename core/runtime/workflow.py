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


DESKTOP_CHAT_REQUIRED_EXPORTS = (
    "chat.input",
    "chat.tts_input",
    "chat.audio_output",
    "chat.ui_worker",
)

DESKTOP_WORKFLOW_ALLOWED_NODE_TYPES = {
    "core.runtime.workers.LLMWorker",
    "core.runtime.workers.TTSWorker",
    "core.runtime.workers.UIWorker",
}


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

    dag = Dag(
        queue_factory=queue_factory,
        allowed_node_types=set(DESKTOP_WORKFLOW_ALLOWED_NODE_TYPES),
    )
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


def require_desktop_chat_workflow(workflow: RuntimeWorkflow) -> None:
    missing = [
        name
        for name in DESKTOP_CHAT_REQUIRED_EXPORTS
        if workflow.get_export(name) is None
    ]
    if missing:
        raise RuntimeError(
            f"Desktop workflow {workflow.workflow_path!r} is missing required "
            f"exports: {', '.join(missing)}"
        )
    _require_desktop_chat_contract(workflow)


def _require_export_binding(
    workflow: RuntimeWorkflow,
    name: str,
    *,
    direction: str,
    node_type: type,
    port: str | None = None,
) -> Any:
    spec = workflow.dag.export_specs().get(name)
    if not isinstance(spec, dict):
        raise RuntimeError(f"Desktop workflow export {name!r} is not declared")
    node_name = str(spec.get("node") or "")
    if not node_name:
        raise RuntimeError(f"Desktop workflow export {name!r} missing node")
    node = workflow.dag.get_node(node_name)
    if not isinstance(node, node_type):
        raise RuntimeError(
            f"Desktop workflow export {name!r} must reference "
            f"{node_type.__name__}, got {type(node).__name__}"
        )
    actual_direction = str(spec.get("direction") or ("node" if not spec.get("port") else "input"))
    if actual_direction != direction:
        raise RuntimeError(
            f"Desktop workflow export {name!r} must use direction "
            f"{direction!r}, got {actual_direction!r}"
        )
    if direction == "node":
        value = workflow.get_export(name)
        if value is not node:
            raise RuntimeError(f"Desktop workflow export {name!r} resolves to wrong node")
        return node
    actual_port = str(spec.get("port") or "")
    if actual_port != port:
        raise RuntimeError(
            f"Desktop workflow export {name!r} must use port {port!r}, got {actual_port!r}"
        )
    expected = (
        workflow.dag.inq(node_name, actual_port)
        if direction == "input"
        else workflow.dag.outq(node_name, actual_port)
    )
    if workflow.get_export(name) is not expected:
        raise RuntimeError(f"Desktop workflow export {name!r} resolves to wrong queue")
    return expected


def _export_node(workflow: RuntimeWorkflow, name: str) -> Any:
    spec = workflow.dag.export_specs().get(name)
    if not isinstance(spec, dict):
        raise RuntimeError(f"Desktop workflow export {name!r} is not declared")
    return workflow.dag.get_node(str(spec.get("node") or ""))


def _require_desktop_chat_contract(workflow: RuntimeWorkflow) -> None:
    from core.runtime.workers import LLMWorker, TTSWorker, UIWorker

    _require_export_binding(
        workflow,
        "chat.input",
        direction="input",
        node_type=LLMWorker,
        port=LLMWorker.PORT_USER_INPUT,
    )
    _require_export_binding(
        workflow,
        "chat.tts_input",
        direction="input",
        node_type=TTSWorker,
        port=TTSWorker.PORT_LLM_OUTPUT,
    )
    _require_export_binding(
        workflow,
        "chat.audio_output",
        direction="output",
        node_type=TTSWorker,
        port=TTSWorker.PORT_TTS_OUTPUT,
    )
    _require_export_binding(
        workflow,
        "chat.ui_worker",
        direction="node",
        node_type=UIWorker,
    )

    llm = _export_node(workflow, "chat.input")
    tts = _export_node(workflow, "chat.tts_input")
    audio_tts = _export_node(workflow, "chat.audio_output")
    ui = _export_node(workflow, "chat.ui_worker")
    if not isinstance(llm, LLMWorker) or not isinstance(tts, TTSWorker) or not isinstance(ui, UIWorker):
        raise RuntimeError("Desktop workflow exports must reference LLMWorker, TTSWorker, and UIWorker")
    if audio_tts is not tts:
        raise RuntimeError("Desktop workflow chat.audio_output must export the same TTSWorker as chat.tts_input")
    if llm.outq(LLMWorker.PORT_LLM_OUTPUT) is not tts.inq(TTSWorker.PORT_LLM_OUTPUT):
        raise RuntimeError("Desktop workflow must connect LLMWorker.llm_output to TTSWorker.llm_output")
    if tts.outq(TTSWorker.PORT_TTS_OUTPUT) is not ui.inq(UIWorker.PORT_TTS_OUTPUT):
        raise RuntimeError("Desktop workflow must connect TTSWorker.tts_output to UIWorker.tts_output")
