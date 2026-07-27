from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]

SOURCE_DIRECTORIES = (
    "ai",
    "application",
    "asr",
    "config",
    "core",
    "frontend_bridge_core",
    "i18n",
    "live",
    "llm",
    "plugin_system",
    "sdk",
    "t2i",
    "tools",
    "tts",
)

FORBIDDEN_IMPORTS = {
    "sdk": frozenset(
        {
            "ai",
            "application",
            "asr",
            "config",
            "core",
            "frontend_bridge_core",
            "llm",
            "plugin_system",
            "t2i",
            "tts",
            "ui",
        }
    ),
    "config": frozenset(
        {
            "ai",
            "application",
            "asr",
            "core",
            "frontend_bridge_core",
            "llm",
            "plugin_system",
            "t2i",
            "tts",
            "ui",
        }
    ),
    "core": frozenset({"ai", "application", "frontend_bridge_core", "ui"}),
    "ai": frozenset(
        {
            "asr",
            "frontend_bridge_core",
            "llm",
            "t2i",
            "tts",
            "ui",
        }
    ),
    "plugin_system": frozenset(
        {"ai", "application", "frontend_bridge_core", "ui"}
    ),
}


@dataclass(frozen=True, order=True)
class ImportViolation:
    source: str
    imported_root: str


# Historical exceptions are removed by O2-O5. This allowlist is deliberately
# path-specific so a new violation in the same package still fails the test.
ALLOWED_VIOLATIONS = frozenset(
    {
        ImportViolation("ai/memory/extraction.py", "llm"),
        ImportViolation("ai/vision/service.py", "llm"),
        ImportViolation("config/character_manager.py", "llm"),
        ImportViolation("config/config_manager.py", "core"),
        ImportViolation("config/config_manager.py", "llm"),
        ImportViolation("config/config_manager.py", "t2i"),
        ImportViolation("config/config_manager.py", "tts"),
        ImportViolation("core/media/auto_annotation.py", "ai"),
        ImportViolation("core/plugins/plugin_host.py", "ai"),
        ImportViolation("core/plugins/plugin_host.py", "ui"),
        ImportViolation("core/plugins/publisher/metadata.py", "frontend_bridge_core"),
        ImportViolation("core/runtime/workers.py", "ai"),
        ImportViolation("sdk/chat_ui_context.py", "ui"),
        ImportViolation("sdk/cli/registry_ops.py", "core"),
        ImportViolation("sdk/logging/configure.py", "core"),
        ImportViolation("sdk/logging/environment.py", "ui"),
        ImportViolation("sdk/manager.py", "config"),
        ImportViolation("sdk/manager.py", "llm"),
        ImportViolation("sdk/plugin_host_context.py", "config"),
        ImportViolation("sdk/plugin_host_context.py", "ui"),
        ImportViolation("sdk/register.py", "llm"),
        ImportViolation("sdk/tool_registry.py", "llm"),
    }
)


def _python_sources() -> list[Path]:
    sources: list[Path] = []
    for directory in SOURCE_DIRECTORIES:
        root = REPO_ROOT / directory
        if root.is_dir():
            sources.extend(root.rglob("*.py"))
    return sorted(sources)


def _imported_roots(source: Path) -> set[str]:
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported_roots.add(node.module.partition(".")[0])
    return imported_roots


def _violations() -> frozenset[ImportViolation]:
    violations: set[ImportViolation] = set()
    for source in _python_sources():
        relative = source.relative_to(REPO_ROOT).as_posix()
        source_root = relative.partition("/")[0]
        forbidden = FORBIDDEN_IMPORTS.get(source_root, frozenset())
        for imported_root in _imported_roots(source) & forbidden:
            violations.add(ImportViolation(relative, imported_root))
    return frozenset(violations)


def test_import_boundaries_match_migration_allowlist() -> None:
    actual = _violations()
    unexpected = sorted(actual - ALLOWED_VIOLATIONS)
    stale_allowlist = sorted(ALLOWED_VIOLATIONS - actual)

    assert not unexpected and not stale_allowlist, (
        "Import boundary allowlist mismatch.\n"
        f"Unexpected violations: {unexpected}\n"
        f"Stale allowlist entries: {stale_allowlist}\n"
        "Do not add a new exception. Remove stale entries when a migration fixes them."
    )
