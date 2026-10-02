from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def imports(path):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    result = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            result.append(node.module or "")
        elif isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
    return result


def test_generic_chat_composition_does_not_import_concrete_story_or_transport():
    for path in (
        "application/chat/build_snapshot.py", "application/chat/snapshot_contributions.py",
        "application/chat/dispatch_commands.py", "application/chat/command_handlers.py",
        "application/chat/history_commands.py", "application/chat/lifecycle.py",
    ):
        assert not any(name.startswith(("application.story", "frontend_bridge_core")) for name in imports(path))


def test_runtime_process_cannot_reacquire_history_command_or_snapshot_responsibilities():
    path = "application/chat/runtime_process.py"
    assert not any(name.startswith((
        "application.story", "application.chat.read_history", "application.chat.dispatch_commands",
        "application.chat.build_snapshot", "application.bootstrap",
    )) for name in imports(path))
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert functions.isdisjoint({
        "_chat_snapshot", "_handle_chat_command", "_chat_history", "_chat_theme_payload",
        "_record_story_choice_history", "build_chat_snapshot", "dispatch_chat_command",
    })
