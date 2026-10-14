"""Keep extracted chat policy independent from its compatibility composition root."""

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "module",
    [
        "runtime_ports",
        "process_supervisor",
        "launch_preparation",
        "runtime_history",
        "runtime_projection",
        "runtime_story",
        "runtime_commands",
    ],
)
def test_chat_services_do_not_import_facade_transport_or_plugin_host(module):
    path = ROOT / "application" / "chat" / f"{module}.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
            imports.extend(f"{node.module}.{alias.name}" for alias in node.names)
    forbidden = (
        "application.chat.runtime_process",
        "frontend_bridge_core",
        "plugin_system",
        "ui",
    )
    assert not any(
        name == prefix or name.startswith(prefix + ".")
        for name in imports
        for prefix in forbidden
    )
