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


@pytest.mark.parametrize(
    "relative_path",
    [
        "application/chat/runtime/session.py",
        "application/chat/runtime/startup.py",
        "application/chat/runtime/commands.py",
        "application/chat/runtime/stream_wiring.py",
        "application/runtime/workers/llm_worker.py",
    ],
)
def test_chat_session_and_llm_worker_decouple_domain_capabilities(
    relative_path: str,
) -> None:
    path = ROOT / relative_path
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
            imports.extend(f"{node.module}.{alias.name}" for alias in node.names)

    forbidden_imports = (
        "ai.memory.hooks",
        "application.knowledge",
        "application.perception",
        "ai.perception",
        "ai.llm.template.dialog.sections.relation",
        "plugin_system.host.bind_perception_runtime",
    )
    assert not any(
        name == prefix or name.startswith(prefix + ".")
        for name in imports
        for prefix in forbidden_imports
    ), f"{relative_path} must delegate domain capabilities via application.chat.capabilities"

    if relative_path.endswith("llm_worker.py"):
        assert "application.chat.runtime.background_prompt" not in imports
        assert "is_perception_turn" not in source
        assert "prepare_perception_turn" not in source

