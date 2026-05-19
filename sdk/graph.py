"""Queue-based DAG primitives for host and plugin workflows.

Nodes declare ports. The builder binds queues to edges and exports. Nodes are
passive by default: ``start`` / ``stop`` and ``astart`` / ``astop`` are no-ops
unless a subclass chooses to own execution.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from typing import Self
except ImportError:
    from typing_extensions import Self


@dataclass
class Port:
    name: str


@dataclass
class Edge:
    src_node: str
    src_port: str
    dst_node: str
    dst_port: str


class DagNode:
    """Base DAG node.

    Passive nodes only declare ports and expose methods for other nodes or the
    host to call. Active nodes can override sync ``start`` / ``stop`` or async
    ``astart`` / ``astop``.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._bound_inputs: dict[str, Any] = {}
        self._bound_outputs: dict[str, Any] = {}

    @property
    def name(self) -> str:
        return self._name

    def inputs(self) -> dict[str, Port]:
        raise NotImplementedError(f"{type(self).__name__}.inputs()")

    def outputs(self) -> dict[str, Port]:
        raise NotImplementedError(f"{type(self).__name__}.outputs()")

    def configure(self, nodes: dict[str, "DagNode"]) -> None:
        """Resolve references to other workflow nodes after YAML load."""
        pass

    def start(self) -> None:
        """Start node work if it owns execution. Passive nodes do nothing."""
        pass

    def stop(self) -> None:
        """Stop node work if it owns execution. Passive nodes do nothing."""
        pass

    async def astart(self) -> None:
        """Async start hook. By default it delegates to ``start``."""
        self.start()

    async def astop(self) -> None:
        """Async stop hook. By default it delegates to ``stop``."""
        self.stop()

    def bind_input(self, port_name: str, queue: Any) -> None:
        self._bound_inputs[port_name] = queue

    def bind_output(self, port_name: str, queue: Any) -> None:
        self._bound_outputs[port_name] = queue

    def inq(self, port_name: str) -> Any:
        q = self._bound_inputs.get(port_name)
        if q is None:
            raise RuntimeError(
                f"DagNode '{self.name}' input port '{port_name}' not bound"
            )
        return q

    def outq(self, port_name: str) -> Any:
        q = self._bound_outputs.get(port_name)
        if q is None:
            raise RuntimeError(
                f"DagNode '{self.name}' output port '{port_name}' not bound"
            )
        return q


@dataclass
class EdgeSpec:
    src: str
    src_port: str
    dst: str
    dst_port: str


class DagBuilder:
    def __init__(self) -> None:
        self._nodes: dict[str, DagNode] = {}
        self._edges: list[Edge] = []
        self._pending_edges: list[EdgeSpec] = []
        self._queue_factory: Callable[[], Any] | None = None
        self._exports: dict[str, dict[str, Any]] = {}

    def set_queue_factory(self, factory: Callable[[], Any]) -> Self:
        self._queue_factory = factory
        return self

    def add_node(self, node: DagNode) -> Self:
        if node.name in self._nodes:
            raise ValueError(f"Duplicate node name: {node.name}")
        self._nodes[node.name] = node
        return self

    def connect(self, src: str, src_port: str, dst: str, dst_port: str) -> Self:
        if src not in self._nodes:
            raise ValueError(f"Unknown source node: {src}")
        if dst not in self._nodes:
            raise ValueError(f"Unknown destination node: {dst}")

        src_ports = self._nodes[src].outputs()
        dst_ports = self._nodes[dst].inputs()
        if src_port not in src_ports:
            raise ValueError(f"Node '{src}' has no output port '{src_port}'")
        if dst_port not in dst_ports:
            raise ValueError(f"Node '{dst}' has no input port '{dst_port}'")
        self._edges.append(
            Edge(src_node=src, src_port=src_port, dst_node=dst, dst_port=dst_port)
        )
        return self

    def add_edges(self, specs: list[EdgeSpec]) -> Self:
        self._pending_edges.extend(specs)
        return self

    def build(self) -> list[DagNode]:
        if self._queue_factory is None:
            raise RuntimeError("queue_factory not set")

        for node in self._nodes.values():
            node.configure(self._nodes)

        pending_edges = self._pending_edges
        self._pending_edges = []
        for spec in pending_edges:
            self.connect(spec.src, spec.src_port, spec.dst, spec.dst_port)

        fanout: dict[tuple[str, str], int] = {}
        for e in self._edges:
            key = (e.src_node, e.src_port)
            fanout[key] = fanout.get(key, 0) + 1
        for (node_name, port_name), count in fanout.items():
            if count > 1:
                raise ValueError(
                    f"Node '{node_name}' output port '{port_name}' fan-out is not supported; "
                    "insert an explicit broadcast node instead"
                )

        queues: dict[tuple[str, str], Any] = {}
        for e in self._edges:
            key = (e.src_node, e.src_port)
            q = queues.get(key)
            if q is None:
                q = self._queue_factory()
                queues[key] = q
            self._nodes[e.src_node].bind_output(e.src_port, q)
            self._nodes[e.dst_node].bind_input(e.dst_port, q)

        for node in self._nodes.values():
            for port_name in node.inputs():
                if port_name not in node._bound_inputs:
                    node.bind_input(port_name, self._queue_factory())
            for port_name in node.outputs():
                if port_name not in node._bound_outputs:
                    node.bind_output(port_name, self._queue_factory())

        connected: set[str] = set()
        for e in self._edges:
            connected.add(e.src_node)
            connected.add(e.dst_node)
        for spec in self._exports.values():
            node_name = spec.get("node")
            if node_name:
                connected.add(node_name)
        return [n for n in self._nodes.values() if n.name in connected]

    def to_dict(self) -> dict:
        return {
            "nodes": [
                {
                    "name": n.name,
                    "type": type(n).__module__ + "." + type(n).__qualname__,
                    "inputs": list(n.inputs().keys()),
                    "outputs": list(n.outputs().keys()),
                }
                for n in self._nodes.values()
            ],
            "edges": [
                {
                    "src": e.src_node,
                    "src_port": e.src_port,
                    "dst": e.dst_node,
                    "dst_port": e.dst_port,
                }
                for e in self._edges
            ],
            "exports": dict(self._exports),
        }

    @staticmethod
    def _import_class(dotted: str) -> type:
        parts = dotted.rsplit(".", 1)
        if len(parts) != 2:
            raise ValueError(f"Cannot parse dotted class name: {dotted}")
        mod, cls_name = parts
        module = importlib.import_module(mod)
        return getattr(module, cls_name)

    @staticmethod
    def _make_node(node_cls: type, name: str, params: dict[str, Any]) -> DagNode:
        def _accepts(args: tuple[Any, ...], kwargs: dict[str, Any]) -> bool:
            try:
                inspect.signature(node_cls).bind(*args, **kwargs)
            except (TypeError, ValueError):
                return False
            return True

        if params:
            candidates = (
                ((), {"name": name, **params}),
                ((name,), params),
                ((), params),
            )
        else:
            candidates = (
                ((), {"name": name}),
                ((name,), {}),
                ((), {}),
            )

        for args, kwargs in candidates:
            if not _accepts(args, kwargs):
                continue
            node = node_cls(*args, **kwargs)
            if isinstance(node, DagNode):
                return node
            raise TypeError(f"{node_cls!r} did not create a DagNode")
        raise TypeError(
            f"{node_cls!r} cannot be constructed from workflow node "
            f"{name!r} with params {sorted(params)}"
        )

    def to_yaml(self, path: str | None = None) -> str:
        import yaml

        out = yaml.dump(self.to_dict(), allow_unicode=True, sort_keys=False)
        if path:
            Path(path).write_text(out, encoding="utf-8")
        return out

    def load_dict(self, data: dict) -> None:
        for nd in data.get("nodes") or []:
            dotted = nd.get("type", "")
            try:
                node_cls = self._import_class(dotted)
            except Exception as e:
                raise ValueError(f"Cannot import {dotted}: {e}") from e
            node_name = nd["name"]
            params = {
                k: v
                for k, v in nd.items()
                if k not in {"name", "type", "inputs", "outputs"}
            }
            try:
                node = self._make_node(node_cls, node_name, params)
            except Exception as e:
                raise ValueError(f"Cannot instantiate {dotted}: {e}") from e
            self.add_node(node)

        for e in data.get("edges") or []:
            self.connect(e["src"], e["src_port"], e["dst"], e["dst_port"])

        exports = data.get("exports") or {}
        if not isinstance(exports, dict):
            raise ValueError("exports must be a dict")
        for name, spec in exports.items():
            if not isinstance(spec, dict):
                raise ValueError(f"Workflow export '{name}' must be a dict")
            self._exports[name] = dict(spec)

    def load_yaml(self, path_or_text: str) -> None:
        import yaml

        text = path_or_text
        if "\n" not in path_or_text and "\r" not in path_or_text:
            p = Path(path_or_text)
            if p.is_file():
                text = p.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise ValueError("YAML must be a dict with 'nodes' and 'edges'")
        self.load_dict(data)

    @classmethod
    def from_dict(cls, data: dict, *, queue_factory=None) -> "DagBuilder":
        builder = cls()
        if queue_factory:
            builder.set_queue_factory(queue_factory)
        builder.load_dict(data)
        return builder

    @classmethod
    def from_yaml(cls, path_or_text: str, *, queue_factory=None) -> "DagBuilder":
        builder = cls()
        if queue_factory:
            builder.set_queue_factory(queue_factory)
        builder.load_yaml(path_or_text)
        return builder


class Dag:
    def __init__(self, *, queue_factory=None):
        self._builder = DagBuilder()
        if queue_factory:
            self._builder.set_queue_factory(queue_factory)
        self._nodes: list[DagNode] = []
        self._started = False

    def load_yaml(self, path_or_text: str) -> "Dag":
        self._builder.load_yaml(path_or_text)
        return self

    def add_node(self, node: DagNode) -> "Dag":
        self._builder.add_node(node)
        return self

    def build(self) -> list[DagNode]:
        self._nodes = self._builder.build()
        return self._nodes

    def start(self) -> None:
        for node in self._nodes:
            node.start()
        self._started = True

    def stop(self) -> None:
        for node in self._nodes:
            try:
                node.stop()
            except Exception:
                pass
        self._started = False

    async def astart(self) -> None:
        for node in self._nodes:
            await node.astart()
        self._started = True

    async def astop(self) -> None:
        for node in self._nodes:
            try:
                await node.astop()
            except Exception:
                pass
        self._started = False

    def inq(self, node_name: str, port_name: str) -> Any:
        return self.get_node(node_name).inq(port_name)

    def outq(self, node_name: str, port_name: str) -> Any:
        return self.get_node(node_name).outq(port_name)

    def get_node(self, node_name: str) -> DagNode:
        node = self._builder._nodes.get(node_name)
        if node is None:
            raise KeyError(f"Node '{node_name}' not found")
        return node

    def export_specs(self) -> dict[str, dict[str, Any]]:
        return dict(self._builder._exports)

    def resolve_export(self, name: str) -> Any:
        spec = self._builder._exports.get(name)
        if spec is None:
            raise KeyError(f"Workflow export '{name}' not found")
        node_name = spec.get("node")
        if not node_name:
            raise ValueError(f"Workflow export '{name}' missing node")
        direction = spec.get("direction")
        port = spec.get("port")
        if direction is None:
            direction = "node" if not port else "input"
        if direction == "node":
            return self.get_node(node_name)
        if not port:
            raise ValueError(f"Workflow export '{name}' missing port")
        if direction == "input":
            return self.inq(node_name, port)
        if direction == "output":
            return self.outq(node_name, port)
        raise ValueError(f"Workflow export '{name}' has unknown direction: {direction}")

    @property
    def nodes(self) -> list[DagNode]:
        return list(self._nodes)
