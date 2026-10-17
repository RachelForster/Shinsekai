"""Keep extracted chat policy independent from its composition root."""

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "module",
    [
        "host/ports",
        "host/process_supervisor",
        "host/launch_preparation",
        "host/history",
        "host/projection",
        "host/story",
        "host/commands",
        "host/events",
        "host/session_lifecycle",
        "host/diagnostics",
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
        "application.chat.composition",
        "frontend_bridge_core",
        "plugin_system",
        "ui",
    )
    assert not any(
        name == prefix or name.startswith(prefix + ".")
        for name in imports
        for prefix in forbidden
    )
