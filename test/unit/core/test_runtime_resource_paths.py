from queue import Queue

from core.runtime.workflow import build_runtime_workflow
from sdk.graph import DagNode


class _ResourcePathNode(DagNode):
    def inputs(self):
        return {}

    def outputs(self):
        return {}


def test_runtime_workflow_resolves_relative_resource_from_source_root(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    project_root = tmp_path / "project"
    workflow_path = source_root / "assets" / "system" / "workflow" / "default.yaml"
    workflow_path.parent.mkdir(parents=True)
    project_root.mkdir()
    workflow_path.write_text(
        """
nodes:
  - name: selected
    type: test.unit.core.test_runtime_resource_paths._ResourcePathNode
edges: []
exports:
  selected:
    node: selected
    direction: node
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("SHINSEKAI_SOURCE_ROOT", str(source_root))
    monkeypatch.chdir(project_root)

    workflow = build_runtime_workflow(
        workflow_path="assets/system/workflow/default.yaml",
        queue_factory=Queue,
    )

    assert workflow.workflow_path == str(workflow_path.resolve())
    assert workflow.require_export("selected").name == "selected"
