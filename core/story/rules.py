"""Deterministic evaluation of conditions and compiled unlock rules."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping
from typing import Any

from .models import ConditionSpec, StoryProgram


class ConditionEvaluator:
    def evaluate(
        self,
        condition: ConditionSpec,
        *,
        variables: Mapping[str, Any],
        completed_node_ids: frozenset[str],
    ) -> bool:
        op = condition.op
        if op == "true":
            return True
        if op == "false":
            return False
        if op == "all":
            return all(
                self.evaluate(
                    child,
                    variables=variables,
                    completed_node_ids=completed_node_ids,
                )
                for child in condition.args
            )
        if op == "any":
            return any(
                self.evaluate(
                    child,
                    variables=variables,
                    completed_node_ids=completed_node_ids,
                )
                for child in condition.args
            )
        if op == "not":
            return not self.evaluate(
                condition.args[0],
                variables=variables,
                completed_node_ids=completed_node_ids,
            )
        if op == "completed":
            return str(condition.args[0]) in completed_node_ids
        if op == "flag":
            return bool(variables.get(str(condition.args[0]), False))
        if op == "equals":
            return variables.get(str(condition.args[0])) == condition.args[1]
        if op == "gte":
            return int(variables.get(str(condition.args[0]), 0)) >= int(
                condition.args[1]
            )
        if op == "lte":
            return int(variables.get(str(condition.args[0]), 0)) <= int(
                condition.args[1]
            )
        if op == "contains":
            return condition.args[1] in variables.get(str(condition.args[0]), ())
        raise ValueError(f"unsupported runtime condition operator: {op}")


class RuleEvaluator:
    """Evaluate the pure subset of RuleGraph that produces node unlocks."""

    def evaluate_unlocks(
        self,
        program: StoryProgram,
        variables: Mapping[str, Any],
    ) -> frozenset[str]:
        graph = program.rule_graph
        nodes = graph.by_id
        incoming: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
        outgoing: dict[str, set[str]] = defaultdict(set)
        indegree = {node.id: 0 for node in graph.nodes}
        for edge in graph.edges:
            incoming[(edge.target.node_id, edge.target.port)].append(
                (edge.source.node_id, edge.source.port)
            )
            if edge.target.node_id not in outgoing[edge.source.node_id]:
                outgoing[edge.source.node_id].add(edge.target.node_id)
                indegree[edge.target.node_id] += 1
        ready = deque(
            sorted(node_id for node_id, degree in indegree.items() if degree == 0)
        )
        outputs: dict[tuple[str, str], Any] = {}
        unlocked: set[str] = set()
        while ready:
            node_id = ready.popleft()
            node = nodes[node_id]
            values = {
                port: [outputs[source] for source in sources if source in outputs]
                for (target_id, port), sources in incoming.items()
                if target_id == node_id
            }
            self._evaluate_node(
                node.type,
                node.config,
                values,
                outputs,
                node_id,
                unlocked,
                variables,
            )
            for target in sorted(outgoing.get(node_id, ())):
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)
        return frozenset(unlocked)

    @staticmethod
    def _evaluate_node(
        node_type: str,
        config: Mapping[str, Any],
        values: Mapping[str, list[Any]],
        outputs: dict[tuple[str, str], Any],
        node_id: str,
        unlocked: set[str],
        variables: Mapping[str, Any],
    ) -> None:
        def first(port: str, default: Any = None) -> Any:
            items = values.get(port, ())
            return items[0] if items else default

        if node_type == "metric-ref":
            outputs[(node_id, "value")] = variables.get(str(config.get("variable")))
            return
        if node_type == "flag-ref":
            outputs[(node_id, "value")] = variables.get(str(config.get("variable")))
            return
        if node_type == "condition.gte":
            outputs[(node_id, "result")] = first("input", 0) >= config.get("value", 0)
            return
        if node_type == "condition.lte":
            outputs[(node_id, "result")] = first("input", 0) <= config.get("value", 0)
            return
        if node_type == "condition.equals":
            outputs[(node_id, "result")] = first("input") == config.get("value")
            return
        if node_type == "compare":
            operator = config.get("operator", "gte")
            left = first("input")
            right = config.get("value")
            if operator == "gte":
                result = left >= right
            elif operator == "lte":
                result = left <= right
            elif operator == "equals":
                result = left == right
            else:
                raise ValueError(f"unsupported compare operator: {operator}")
            outputs[(node_id, "result")] = result
            return
        if node_type == "all":
            outputs[(node_id, "result")] = all(values.get("input", ()))
            return
        if node_type == "any":
            outputs[(node_id, "result")] = any(values.get("input", ()))
            return
        if node_type == "not":
            outputs[(node_id, "result")] = not bool(first("input"))
            return
        if node_type == "unlock" and bool(first("when")):
            target = config.get("storyNodeId")
            if isinstance(target, str):
                unlocked.add(target)
