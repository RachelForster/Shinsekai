"""End-to-end DAG graph test: build, bind ports, pump messages, YAML round-trip."""

import tempfile
import threading
import time
from pathlib import Path
from queue import Queue

import pytest

from sdk.graph import DagBuilder, DagNode, EdgeSpec, Port


class EchoNode(DagNode):
    """Echo input text to output, prefixed with node name."""

    def __init__(self, name: str):
        super().__init__(name)
        self._running = False
        self._thread = None

    def inputs(self):
        return {"in": Port("in")}

    def outputs(self):
        return {"out": Port("out")}

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while self._running:
            msg = self.inq("in").get()
            if msg is None:
                break
            self.outq("out").put(f"[{self.name}]{msg}")

    def stop(self):
        self._running = False
        self.inq("in").put(None)
        if self._thread:
            self._thread.join(timeout=3)


class SinkNode(DagNode):
    """Collect all received messages into a list."""

    def __init__(self, name: str):
        super().__init__(name)
        self.received: list = []
        self._running = False
        self._thread = None

    def inputs(self):
        return {"in": Port("in")}

    def outputs(self):
        return {}

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while self._running:
            msg = self.inq("in").get()
            if msg is None:
                break
            self.received.append(msg)

    def stop(self):
        self._running = False
        self.inq("in").put(None)
        if self._thread:
            self._thread.join(timeout=3)


class TestDagBuilder:
    def test_two_node_pipeline(self):
        """A -> B: message flows through."""
        a = EchoNode("a")
        b = SinkNode("b")

        builder = DagBuilder()
        builder.set_queue_factory(Queue)
        builder.add_node(a)
        builder.add_node(b)
        builder.connect("a", "out", "b", "in")
        nodes = builder.build()

        # Verify ports bound
        assert a._bound_outputs.get("out") is not None
        assert b._bound_inputs.get("in") is not None

        # Start, pump, stop
        for n in nodes:
            n.start()

        # Feed input through the unconnected "in" port of node A
        a.inq("in").put("hello")
        time.sleep(0.2)

        for n in nodes:
            n.stop()

        assert len(b.received) == 1
        assert b.received[0] == "[a]hello"

    def test_unconnected_node_not_returned(self):
        """An orphan node (no edges) is excluded from build()."""
        a = EchoNode("a")
        builder = DagBuilder()
        builder.set_queue_factory(Queue)
        builder.add_node(a)
        nodes = builder.build()
        assert nodes == []

    def test_external_edges(self):
        """Plugin-provided EdgeSpecs are resolved at build time."""
        a = EchoNode("src")
        b = SinkNode("dst")

        builder = DagBuilder()
        builder.set_queue_factory(Queue)
        builder.add_node(a)
        builder.add_node(b)
        # Use add_edges with EdgeSpec (simulating plugin registration)
        builder.add_edges([EdgeSpec("src", "out", "dst", "in")])
        nodes = builder.build()

        assert a._bound_outputs.get("out") is not None
        assert b._bound_inputs.get("in") is not None

    def test_edge_spec_unknown_node_raises(self):
        """EdgeSpec referencing non-existent node raises ValueError."""
        a = EchoNode("a")
        builder = DagBuilder()
        builder.set_queue_factory(Queue)
        builder.add_node(a)
        builder.add_edges([EdgeSpec("a", "out", "ghost", "in")])

        with pytest.raises(ValueError, match="ghost"):
            builder.build()

    def test_edge_spec_unknown_port_raises(self):
        """EdgeSpec is validated with the same port checks as connect()."""
        a = EchoNode("a")
        b = SinkNode("b")
        builder = DagBuilder()
        builder.set_queue_factory(Queue)
        builder.add_node(a).add_node(b)
        builder.add_edges([EdgeSpec("a", "missing", "b", "in")])

        with pytest.raises(ValueError, match="missing"):
            builder.build()

    def test_three_node_chain(self):
        a = EchoNode("A")
        b = EchoNode("B")
        c = SinkNode("C")

        builder = DagBuilder()
        builder.set_queue_factory(Queue)
        builder.add_node(a).add_node(b).add_node(c)
        builder.connect("A", "out", "B", "in")
        builder.connect("B", "out", "C", "in")
        nodes = builder.build()

        for n in nodes:
            n.start()

        a.inq("in").put("data")
        time.sleep(0.3)

        for n in nodes:
            n.stop()

        assert c.received == ["[B][A]data"]


class TestDagSerialization:
    def test_to_dict_round_trip(self):
        """to_dict produces valid structure that from_dict can reload."""
        a = EchoNode("A")
        b = SinkNode("B")
        builder = DagBuilder()
        builder.set_queue_factory(Queue)
        builder.add_node(a).add_node(b)
        builder.connect("A", "out", "B", "in")
        builder.build()

        data = builder.to_dict()
        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1
        assert data["edges"][0]["src"] == "A"
        assert data["edges"][0]["src_port"] == "out"

    def test_to_yaml_writes_file(self, tmp_path):
        """to_yaml writes a YAML file with full dotted type paths."""
        a = EchoNode("A")
        b = SinkNode("B")
        builder = DagBuilder()
        builder.set_queue_factory(Queue)
        builder.add_node(a).add_node(b)
        builder.connect("A", "out", "B", "in")
        builder.build()

        out = tmp_path / "graph.yaml"
        builder.to_yaml(str(out))
        assert out.is_file()
        content = out.read_text()
        assert "A" in content
        assert "EchoNode" in content

    def test_from_yaml_round_trip(self, tmp_path):
        """Export to YAML, re-import, verify nodes exist."""
        a = EchoNode("src")
        b = SinkNode("dst")
        builder1 = DagBuilder()
        builder1.set_queue_factory(Queue)
        builder1.add_node(a).add_node(b)
        builder1.connect("src", "out", "dst", "in")
        builder1.build()

        yaml_path = tmp_path / "wf.yaml"
        builder1.to_yaml(str(yaml_path))

        # Re-import from YAML
        builder2 = DagBuilder.from_yaml(str(yaml_path), queue_factory=Queue)
        assert "src" in builder2._nodes
        assert "dst" in builder2._nodes
        assert len(builder2._edges) == 1

    def test_yaml_exports_resolve_handles(self):
        """Named exports resolve to queues or nodes after build."""
        dag_yaml = """
nodes:
  - name: src
    type: test.unit.tools.test_dag_graph.EchoNode
edges: []
exports:
  chat.input:
    node: src
    port: in
    direction: input
  chat.node:
    node: src
    direction: node
"""
        from sdk.graph import Dag

        dag = Dag(queue_factory=Queue)
        dag.load_yaml(dag_yaml)
        nodes = dag.build()

        assert [node.name for node in nodes] == ["src"]
        assert dag.resolve_export("chat.input") is dag.inq("src", "in")
        assert dag.resolve_export("chat.node").name == "src"
