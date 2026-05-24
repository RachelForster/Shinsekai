"""
DAG 流水线抽象 —— 插件可用 ``DagNode`` 注册自定义处理节点，宿主用 ``DagBuilder`` 组装。

无 PySide6 / queue.Queue 等依赖，只定义接口。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from typing import Self
except ImportError:
    from typing_extensions import Self


# ── Port ────────────────────────────────────────────────────────────────

@dataclass
class Port:
    """DAG 节点的输入/输出端口。

    不绑定具体队列类型；宿主在 ``DagBuilder.build()`` 时注入实际 ``Queue``。
    """

    name: str


@dataclass
class Edge:
    """一条有向边：src_node.outputs[src_port] → dst_node.inputs[dst_port]"""

    src_node: str
    src_port: str
    dst_node: str
    dst_port: str


# ── DagNode ──────────────────────────────────────────────────────────────

class DagNode:
    """DAG 中的一个处理节点。

    子类实现 ``inputs`` / ``outputs`` 声明端口，
    实现 ``start`` / ``stop`` 管理生命周期。
    宿主在 ``DagBuilder.build()`` 时通过
    ``bind_input`` / ``bind_output`` 注入实际 ``Queue``。
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._bound_inputs: dict[str, Any] = {}
        self._bound_outputs: dict[str, Any] = {}

    @property
    def name(self) -> str:
        return self._name

    # ── 子类实现 ──────────────────────────────────────────────────────

    def inputs(self) -> dict[str, Port]:
        """声明输入端口（子类必须覆写）。"""
        raise NotImplementedError(f"{type(self).__name__}.inputs()")

    def outputs(self) -> dict[str, Port]:
        """声明输出端口（子类必须覆写）。"""
        raise NotImplementedError(f"{type(self).__name__}.outputs()")

    def stop(self) -> None:
        """停止节点并等待退出（子类必须覆写）。"""
        raise NotImplementedError(f"{type(self).__name__}.stop()")

    # ── 宿主调用 ──────────────────────────────────────────────────────

    def bind_input(self, port_name: str, queue: Any) -> None:
        self._bound_inputs[port_name] = queue

    def bind_output(self, port_name: str, queue: Any) -> None:
        self._bound_outputs[port_name] = queue

    def inq(self, port_name: str) -> Any:
        """获取已绑定的输入队列。"""
        q = self._bound_inputs.get(port_name)
        if q is None:
            raise RuntimeError(
                f"DagNode '{self.name}' input port '{port_name}' not bound"
            )
        return q

    def outq(self, port_name: str) -> Any:
        """获取已绑定的输出队列。"""
        q = self._bound_outputs.get(port_name)
        if q is None:
            raise RuntimeError(
                f"DagNode '{self.name}' output port '{port_name}' not bound"
            )
        return q


# ── EdgeSpec ────────────────────────────────────────────────────────────


@dataclass
class EdgeSpec:
    """插件声明的一条连线（不依赖宿主的实际节点名是否存在）。"""

    src: str
    src_port: str
    dst: str
    dst_port: str


# ── DagBuilder ───────────────────────────────────────────────────────────

class DagBuilder:
    """声明式构建 DAG。"""

    def __init__(self) -> None:
        self._nodes: dict[str, DagNode] = {}
        self._edges: list[Edge] = []
        self._pending_edges: list[EdgeSpec] = []
        self._queue_factory: Callable[[], Any] | None = None
        self._exports: dict[str, dict[str, Any]] = {}

    def set_queue_factory(self, factory: Callable[[], Any]) -> Self:
        """设置 Queue 工厂（宿主传入 ``Queue`` 即可）。"""
        self._queue_factory = factory
        return self

    def add_node(self, node: DagNode) -> Self:
        if node.name in self._nodes:
            raise ValueError(f"Duplicate node name: {node.name}")
        self._nodes[node.name] = node
        return self

    def connect(
        self, src: str, src_port: str, dst: str, dst_port: str
    ) -> Self:
        """连接两个节点的端口（节点必须已添加）。"""
        if src not in self._nodes:
            raise ValueError(f"Unknown source node: {src}")
        if dst not in self._nodes:
            raise ValueError(f"Unknown destination node: {dst}")
        
        src_ports = self._nodes[src].outputs()
        dst_ports = self._nodes[dst].inputs()
        if src_port not in src_ports:
            raise ValueError(
                f"Node '{src}' has no output port '{src_port}'"
            )
        if dst_port not in dst_ports:
            raise ValueError(
                f"Node '{dst}' has no input port '{dst_port}'"
            )
        self._edges.append(
            Edge(src_node=src, src_port=src_port, dst_node=dst, dst_port=dst_port)
        )
        return self

    def add_edges(self, specs: list[EdgeSpec]) -> Self:
        """延迟连线：记录连线意图，build() 时再校验并落实。"""
        self._pending_edges.extend(specs)
        return self

    def build(self) -> list[DagNode]:
        """构建 DAG：落实延迟连线、创建队列、绑定端口、返回节点列表。

        ``set_queue_factory`` 必须先调用。
        """
        if self._queue_factory is None:
            raise RuntimeError("queue_factory not set")

        # 落实延迟连线（插件注册的 EdgeSpec）。复用 connect()，确保端口也被校验。
        pending_edges = self._pending_edges
        self._pending_edges = []
        for spec in pending_edges:
            self.connect(spec.src, spec.src_port, spec.dst, spec.dst_port)

        _queues: dict[tuple[str, str], Any] = {}
        for e in self._edges:
            key = (e.src_node, e.src_port)
            q = _queues.get(key)
            if q is None:
                q = self._queue_factory()
                _queues[key] = q
            self._nodes[e.src_node].bind_output(e.src_port, q)
            self._nodes[e.dst_node].bind_input(e.dst_port, q)

        # 为没有 incoming edge 的输入端口创建独立队列（管线起点 / 外部馈入）
        for node in self._nodes.values():
            for port_name in node.inputs():
                if port_name not in node._bound_inputs:
                    node.bind_input(port_name, self._queue_factory())
            for port_name in node.outputs():
                if port_name not in node._bound_outputs:
                    node.bind_output(port_name, self._queue_factory())

        # 只返回有连线的节点（注册但未连线的节点不启动，避免空转线程）
        connected: set[str] = set()
        for e in self._edges:
            connected.add(e.src_node)
            connected.add(e.dst_node)
        for spec in self._exports.values():
            node_name = spec.get("node")
            if node_name:
                connected.add(node_name)
        return [n for n in self._nodes.values() if n.name in connected]

    # ── 序列化 ────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """导出 DAG 结构为 dict（不含队列绑定，仅元数据）。"""
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
                {"src": e.src_node, "src_port": e.src_port,
                 "dst": e.dst_node, "dst_port": e.dst_port}
                for e in self._edges
            ],
            "exports": dict(self._exports),
        }

    @staticmethod
    def _import_class(dotted: str) -> type:
        """从 ``package.module.ClassName`` 字符串导入类。"""
        import importlib

        parts = dotted.rsplit(".", 1)
        if len(parts) != 2:
            raise ValueError(f"Cannot parse dotted class name: {dotted}")
        mod, cls_name = parts
        m = importlib.import_module(mod)
        return getattr(m, cls_name)

    def to_yaml(self, path: str | None = None) -> str:
        """导出 DAG 为 YAML 字符串；若提供 ``path`` 则写入文件。"""
        import yaml

        out = yaml.dump(self.to_dict(), allow_unicode=True, sort_keys=False)
        if path:
            Path(path).write_text(out, encoding="utf-8")
        return out

    def load_dict(self, data: dict) -> None:
        """从 dict 加载节点和边到当前 builder（用于组装多方工作流）。"""
        for nd in data.get("nodes") or []:
            dotted = nd.get("type", "")
            try:
                node_cls = self._import_class(dotted)
            except Exception as e:
                raise ValueError(f"Cannot import {dotted}: {e}") from e
            node_name = nd["name"]
            try:
                node = node_cls(name=node_name)
            except TypeError:
                try:
                    node = node_cls(node_name)
                except TypeError:
                    node = node_cls()
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
        """从 YAML 文件路径或 YAML 字符串加载节点和边到当前 builder。"""
        import yaml

        text = path_or_text
        p = Path(path_or_text)
        if p.is_file():
            text = p.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise ValueError("YAML must be a dict with 'nodes' and 'edges'")
        self.load_dict(data)

    @classmethod
    def from_dict(cls, data: dict, *, queue_factory=None) -> "DagBuilder":
        """从 dict 创建新 builder 并加载（用于测试/独立场景）。"""
        builder = cls()
        if queue_factory:
            builder.set_queue_factory(queue_factory)
        builder.load_dict(data)
        return builder

    @classmethod
    def from_yaml(cls, path_or_text: str, *, queue_factory=None) -> "DagBuilder":
        """从 YAML 文件路径或 YAML 字符串创建新 builder 并加载。"""
        builder = cls()
        if queue_factory:
            builder.set_queue_factory(queue_factory)
        builder.load_yaml(path_or_text)
        return builder


# ── Dag ─────────────────────────────────────────────────────────────────

class Dag:
    """DAG 全生命周期管理：构建、启动、关闭。

    用法::

        dag = Dag(queue_factory=Queue)
        dag.load_yaml("workflow/default.yaml")
        dag.add_node(my_node)
        dag.load_yaml("plugin/workflow.yaml")
        dag.start()
        # … 运行 …
        dag.stop()
    """

    def __init__(self, *, queue_factory=None):
        self._builder = DagBuilder()
        if queue_factory:
            self._builder.set_queue_factory(queue_factory)
        self._nodes: list[DagNode] = []
        self._started = False

    # ── 构建 ──────────────────────────────────────────────────────────

    def load_yaml(self, path_or_text: str) -> "Dag":
        self._builder.load_yaml(path_or_text)
        return self

    def add_node(self, node: DagNode) -> "Dag":
        self._builder.add_node(node)
        return self

    # ── 生命周期 ──────────────────────────────────────────────────────

    def build(self) -> list[DagNode]:
        """构造 DAG：创建队列、绑定端口（必须在 start 之前调用）。"""
        self._nodes = self._builder.build()
        return self._nodes

    def start(self) -> None:
        """启动所有节点线程（必须在 build 之后调用）。"""
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

    def inq(self, node_name: str, port_name: str) -> Any:
        """获取指定节点输入端口绑定的队列（供外部馈入数据）。"""
        return self.get_node(node_name).inq(port_name)

    def outq(self, node_name: str, port_name: str) -> Any:
        """获取指定节点输出端口绑定的队列。"""
        return self.get_node(node_name).outq(port_name)

    def get_node(self, node_name: str) -> DagNode:
        n = self._builder._nodes.get(node_name)
        if n is None:
            raise KeyError(f"Node '{node_name}' not found")
        return n

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
