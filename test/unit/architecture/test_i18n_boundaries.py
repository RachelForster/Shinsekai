"""Ratchet guardrails preventing new hardcoded CJK UI literals in bridge code."""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BRIDGE_ROOT = REPO_ROOT / "frontend_bridge_core"
_CJK_RE = re.compile(r"[\u3400-\u9fff\u3040-\u30ff]")

# LLM-facing host tool descriptions stay inline by design (matching @tool descriptions).
EXEMPT_BRIDGE_FILES = frozenset(
    {
        "frontend_bridge_core/transport/agent_http_tools.py",
    }
)

# Ratchet baseline of existing frontend_bridge_core files containing CJK string
# literals in non-docstring code. Never add new files here; remove each entry
# once migrated to structured error/task codes.
LOCKED_BRIDGE_CJK_FILES: frozenset[str] = frozenset()


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                ids.add(id(node.body[0].value))
    return ids


def _bridge_cjk_files() -> frozenset[str]:
    found: set[str] = set()
    for source in sorted(BRIDGE_ROOT.rglob("*.py")):
        rel_path = source.relative_to(REPO_ROOT).as_posix()
        if rel_path in EXEMPT_BRIDGE_FILES:
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        doc_ids = _docstring_node_ids(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in doc_ids
                and _CJK_RE.search(node.value)
            ):
                found.add(rel_path)
                break
    return frozenset(found)


def test_bridge_cjk_literals_follow_shrinking_ratchet() -> None:
    actual = _bridge_cjk_files()
    unexpected = sorted(actual - LOCKED_BRIDGE_CJK_FILES)
    stale = sorted(LOCKED_BRIDGE_CJK_FILES - actual)
    assert not unexpected and not stale, (
        "frontend_bridge_core CJK hardcode ratchet mismatch.\n"
        f"Unexpected new files: {unexpected}\n"
        f"Stale allowlist entries to remove: {stale}"
    )


def test_bridge_does_not_branch_on_localized_chinese_message_prefixes() -> None:
    forbidden_patterns = ('.startswith("找不到")', '.startswith("请")')
    offenders: list[str] = []
    for source in sorted(BRIDGE_ROOT.rglob("*.py")):
        text = source.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            if pattern in text:
                offenders.append(f"{source.relative_to(REPO_ROOT).as_posix()}: {pattern}")
    assert not offenders, (
        "Bridge adapters must rely on structured exceptions/codes, not Chinese prefixes: "
        f"{offenders}"
    )
