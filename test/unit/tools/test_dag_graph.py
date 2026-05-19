"""End-to-end DAG graph test: build, bind ports, pump messages, YAML round-trip."""

import asyncio
import tempfile
import threading
import time
from pathlib import Path
from queue import Queue
from typing import Any

import pytest

from core.runtime.workflow import build_runtime_workflow
from sdk.graph import (
    DagBuilder,
    DagNode,
    EdgeSpec,
    Port,
)


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


class PassiveNoPortsNode(DagNode):
    def inputs(self):
        return {}

    def outputs(self):
        return {}


class RuleNode(PassiveNoPortsNode):
    def __init__(self, name: str, accepted: str = "yes"):
        super().__init__(name)
        self.accepted = accepted

    def accepts(self, value: str) -> bool:
        return value == self.accepted

    def to_config(self):
        return {"accepted": self.accepted}

    @classmethod
    def from_config(cls, name: str, params: dict[str, Any]) -> "RuleNode":
        return cls(name=name, **params)


class RuleRouterNode(DagNode):
    def __init__(self, name: str, rule_node: str):
        super().__init__(name)
        self.rule_node_name = rule_node
        self.rule: RuleNode | None = None

    def inputs(self):
        return {"in": Port("in")}

    def outputs(self):
        return {"accepted": Port("accepted"), "rejected": Port("rejected")}

    def to_config(self):
        return {"rule_node": self.rule_node_name}

    @classmethod
    def from_config(cls, name: str, params: dict[str, Any]) -> "RuleRouterNode":
        return cls(name=name, **params)

    def configure(self, nodes):
        rule = nodes.get(self.rule_node_name)
        if not isinstance(rule, RuleNode):
            raise ValueError(f"Unknown rule node: {self.rule_node_name}")
        self.rule = rule

    def start(self):
        item = self.inq("in").get()
        assert self.rule is not None
        if self.rule.accepts(item):
            self.outq("accepted").put(item)
        else:
            self.outq("rejected").put(item)
        self.inq("in").task_done()


class AsyncLifecycleNode(PassiveNoPortsNode):
    def __init__(self, name: str):
        super().__init__(name)
        self.events: list[str] = []

    async def astart(self):
        await asyncio.sleep(0)
        self.events.append("start")

    async def astop(self):
        await asyncio.sleep(0)
        self.events.append("stop")


class StopOrderNode(PassiveNoPortsNode):
    events: list[str] = []

    def stop(self):
        self.events.append(self.name)


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

    def test_passive_node_lifecycle_is_noop(self):
        """Passive nodes can participate as exports without owning a thread."""
        node = PassiveNoPortsNode("passive")
        builder = DagBuilder()
        builder.set_queue_factory(Queue)
        builder.add_node(node)
        builder._exports["passive"] = {"node": "passive", "direction": "node"}
        nodes = builder.build()

        assert nodes == [node]
        node.start()
        node.stop()

    def test_async_lifecycle_hooks(self):
        node = AsyncLifecycleNode("async_node")
        builder = DagBuilder()
        builder.set_queue_factory(Queue)
        builder.add_node(node)
        builder._exports["async_node"] = {"node": "async_node", "direction": "node"}
        nodes = builder.build()

        from sdk.graph import Dag

        dag = Dag(queue_factory=Queue)
        dag.add_node(node)
        dag._builder._exports["async_node"] = {"node": "async_node", "direction": "node"}
        dag.build()
        asyncio.run(dag.astart())
        asyncio.run(dag.astop())

        assert nodes == [node]
        assert node.events == ["start", "stop"]

    def test_stop_order_matches_start_order(self):
        StopOrderNode.events = []
        src = StopOrderNode("src")
        dst = StopOrderNode("dst")

        builder = DagBuilder()
        builder.set_queue_factory(Queue)
        builder.add_node(src).add_node(dst)
        builder._exports["src"] = {"node": "src", "direction": "node"}
        builder._exports["dst"] = {"node": "dst", "direction": "node"}

        from sdk.graph import Dag

        dag = Dag(queue_factory=Queue)
        dag.add_node(src).add_node(dst)
        dag._builder._exports["src"] = {"node": "src", "direction": "node"}
        dag._builder._exports["dst"] = {"node": "dst", "direction": "node"}
        dag.build()
        dag.stop()

        assert StopOrderNode.events == ["src", "dst"]

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
        """to_dict produces valid structure with params field."""
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
        for node in data["nodes"]:
            assert "params" in node
            assert isinstance(node["params"], dict)

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

    def test_yaml_node_reference_via_configure(self):
        dag_yaml = """
nodes:
  - name: rule
    type: test.unit.tools.test_dag_graph.RuleNode
    params:
      accepted: "yes"
  - name: router
    type: test.unit.tools.test_dag_graph.RuleRouterNode
    params:
      rule_node: rule
edges: []
exports:
  input:
    node: router
    port: in
    direction: input
  accepted:
    node: router
    port: accepted
    direction: output
"""
        from sdk.graph import Dag

        dag = Dag(queue_factory=Queue)
        dag.load_yaml(dag_yaml)
        nodes = dag.build()

        dag.resolve_export("input").put("yes")
        dag.start()

        assert [node.name for node in nodes] == ["router"]
        assert dag.resolve_export("accepted").get(timeout=0.2) == "yes"

    def test_params_round_trip_via_to_dict(self):
        """to_dict preserves constructor params, from_dict restores them."""
        rule = RuleNode("rule", accepted="no")
        router = RuleRouterNode("router", rule_node="rule")
        builder = DagBuilder()
        builder.set_queue_factory(Queue)
        builder.add_node(rule).add_node(router)
        builder._exports["router_in"] = {"node": "router", "port": "in", "direction": "input"}
        builder._exports["rule_node_ref"] = {"node": "rule", "direction": "node"}
        builder.build()

        data = builder.to_dict()
        rule_data = next(n for n in data["nodes"] if n["name"] == "rule")
        router_data = next(n for n in data["nodes"] if n["name"] == "router")

        assert rule_data["params"] == {"accepted": "no"}
        assert router_data["params"] == {"rule_node": "rule"}

        builder2 = DagBuilder.from_dict(data, queue_factory=Queue)
        rule2 = builder2._nodes["rule"]
        router2 = builder2._nodes["router"]
        assert isinstance(rule2, RuleNode)
        assert isinstance(router2, RuleRouterNode)
        assert rule2.accepted == "no"
        assert router2.rule_node_name == "rule"

    def test_make_node_propagates_internal_typeerror(self):
        """Constructor-internal TypeError must surface, not be silently retried."""

        class BuggyNode(DagNode):
            def __init__(self, name: str, fail_on: str = ""):
                super().__init__(name)
                if fail_on:
                    raise TypeError(f"internal bug: {fail_on}")

            def inputs(self):
                return {}

            def outputs(self):
                return {}

        from sdk.graph import DagBuilder

        with pytest.raises(TypeError, match="internal bug: boom"):
            DagBuilder._make_node(BuggyNode, "bomb", {"fail_on": "boom"})

class TestRuntimeWorkflow:
    def test_build_runtime_workflow_uses_only_selected_yaml(self, tmp_path):
        first = tmp_path / "first.yaml"
        second = tmp_path / "second.yaml"
        first.write_text(
            """
nodes:
  - name: first
    type: test.unit.tools.test_dag_graph.EchoNode
edges: []
exports:
  selected:
    node: first
    direction: node
""",
            encoding="utf-8",
        )
        second.write_text(
            """
nodes:
  - name: second
    type: test.unit.tools.test_dag_graph.EchoNode
edges: []
exports:
  selected:
    node: second
    direction: node
""",
            encoding="utf-8",
        )

        workflow = build_runtime_workflow(
            workflow_path=str(second),
            queue_factory=Queue,
        )

        assert workflow.workflow_path == str(second)
        assert workflow.require_export("selected").name == "second"
        with pytest.raises(KeyError):
            workflow.dag.get_node("first")
