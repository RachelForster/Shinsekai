"""Keep conversation policy independent of provider types and global settings."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_conversation_policy_does_not_select_concrete_providers_or_global_config():
    forbidden = {"ClaudeAdapter", "DeepSeekAdapter", "GeminiAdapter", "OpenAIAdapter", "ConfigManager"}
    for name in ("llm_manager.py", "chat_loop.py", "request_runner.py", "tool_session.py", "conversation_history.py"):
        path = ROOT / "ai" / "llm" / name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        references = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert not references & forbidden, f"{name} couples conversation policy to {references & forbidden}"


def test_response_contracts_do_not_import_host_or_vendor_sdk_implementations():
    path = ROOT / "sdk" / "llm_response.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            imports.add(node.module.partition(".")[0])
    assert not imports & {"ai", "application", "config", "core", "openai", "anthropic", "genai"}
