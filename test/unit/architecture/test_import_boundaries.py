from __future__ import annotations

import ast
import hashlib
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
    "core": frozenset(
        {
            "ai",
            "application",
            "asr",
            "frontend_bridge_core",
            "llm",
            "t2i",
            "tts",
            "ui",
        }
    ),
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
        {
            "ai",
            "application",
            "asr",
            "frontend_bridge_core",
            "llm",
            "t2i",
            "tts",
            "ui",
        }
    ),
    "application": frozenset({"frontend_bridge_core", "ui"}),
    "frontend_bridge_core": frozenset(
        {
            "ai",
            "asr",
            "core",
            "llm",
            "plugin_system",
            "t2i",
            "tts",
            "ui",
        }
    ),
}

DECLARED_LAYER_ROOTS = frozenset(
    {
        "sdk",
        "config",
        "core",
        "ai",
        "plugin_system",
        "application",
        "frontend_bridge_core",
    }
)


@dataclass(frozen=True, order=True)
class ImportViolation:
    source: str
    imported_root: str


# Immutable O1 baseline. Never append to or replace this set after O1; later
# migrations may only remove entries from ALLOWED_VIOLATIONS.
LOCKED_BASELINE_VIOLATIONS = frozenset(
    {
        ImportViolation("ai/memory/extraction.py", "llm"),
        ImportViolation("ai/vision/service.py", "llm"),
        ImportViolation("config/character_manager.py", "llm"),
        ImportViolation("config/config_manager.py", "core"),
        ImportViolation("config/config_manager.py", "llm"),
        ImportViolation("config/config_manager.py", "t2i"),
        ImportViolation("config/config_manager.py", "tts"),
        ImportViolation("core/handlers/ui_message_handler.py", "asr"),
        ImportViolation("core/media/auto_annotation.py", "ai"),
        ImportViolation("core/plugins/plugin_host.py", "ai"),
        ImportViolation("core/plugins/plugin_host.py", "asr"),
        ImportViolation("core/plugins/plugin_host.py", "llm"),
        ImportViolation("core/plugins/plugin_host.py", "t2i"),
        ImportViolation("core/plugins/plugin_host.py", "tts"),
        ImportViolation("core/plugins/plugin_host.py", "ui"),
        ImportViolation("core/plugins/publisher/metadata.py", "frontend_bridge_core"),
        ImportViolation("core/runtime/ui_update_manager.py", "asr"),
        ImportViolation("core/runtime/workers.py", "ai"),
        ImportViolation("core/sprite/chat_history.py", "llm"),
        ImportViolation("core/sprite/chat_ui_service.py", "llm"),
        ImportViolation("frontend_bridge_core/backgrounds.py", "ui"),
        ImportViolation("frontend_bridge_core/characters.py", "ui"),
        ImportViolation("frontend_bridge_core/chat.py", "core"),
        ImportViolation("frontend_bridge_core/chat.py", "llm"),
        ImportViolation("frontend_bridge_core/chat_stream.py", "core"),
        ImportViolation("frontend_bridge_core/config.py", "asr"),
        ImportViolation("frontend_bridge_core/config.py", "llm"),
        ImportViolation("frontend_bridge_core/config.py", "t2i"),
        ImportViolation("frontend_bridge_core/config.py", "tts"),
        ImportViolation("frontend_bridge_core/handler.py", "core"),
        ImportViolation("frontend_bridge_core/handler.py", "llm"),
        ImportViolation("frontend_bridge_core/image_annotations.py", "core"),
        ImportViolation("frontend_bridge_core/logs.py", "core"),
        ImportViolation("frontend_bridge_core/mcp.py", "llm"),
        ImportViolation("frontend_bridge_core/memory.py", "ai"),
        ImportViolation("frontend_bridge_core/model_assets.py", "ai"),
        ImportViolation("frontend_bridge_core/model_assets.py", "core"),
        ImportViolation("frontend_bridge_core/plugin_catalog.py", "core"),
        ImportViolation("frontend_bridge_core/plugin_publisher.py", "core"),
        ImportViolation("frontend_bridge_core/plugin_ui.py", "core"),
        ImportViolation("frontend_bridge_core/plugin_updates.py", "core"),
        ImportViolation("frontend_bridge_core/runtime_dependencies.py", "core"),
        ImportViolation("frontend_bridge_core/templates.py", "core"),
        ImportViolation("frontend_bridge_core/templates.py", "llm"),
        ImportViolation("frontend_bridge_core/templates.py", "ui"),
        ImportViolation("frontend_bridge_core/tts.py", "ui"),
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
LOCKED_BASELINE_SHA256 = "c83d2b5ca262fcfa819c41ba308004f789647ac6368d78df5099635c5b6a3816"

# This is the only set later Objective PRs may shrink. The locked baseline above
# makes a newly invented exception fail even if it is added here.
ALLOWED_VIOLATIONS = LOCKED_BASELINE_VIOLATIONS - frozenset(
    {
        ImportViolation("core/plugins/plugin_host.py", "ai"),
        ImportViolation("core/plugins/plugin_host.py", "asr"),
        ImportViolation("core/plugins/plugin_host.py", "llm"),
        ImportViolation("core/plugins/plugin_host.py", "t2i"),
        ImportViolation("core/plugins/plugin_host.py", "tts"),
        ImportViolation("core/plugins/plugin_host.py", "ui"),
        ImportViolation(
            "core/plugins/publisher/metadata.py",
            "frontend_bridge_core",
        ),
        ImportViolation("core/media/auto_annotation.py", "ai"),
        ImportViolation("frontend_bridge_core/chat.py", "core"),
        ImportViolation("frontend_bridge_core/chat.py", "llm"),
        ImportViolation("frontend_bridge_core/chat_stream.py", "core"),
        ImportViolation("frontend_bridge_core/handler.py", "core"),
        ImportViolation("frontend_bridge_core/handler.py", "llm"),
        ImportViolation("frontend_bridge_core/image_annotations.py", "core"),
        ImportViolation("frontend_bridge_core/logs.py", "core"),
        ImportViolation("frontend_bridge_core/model_assets.py", "ai"),
        ImportViolation("frontend_bridge_core/model_assets.py", "core"),
        ImportViolation("frontend_bridge_core/plugin_catalog.py", "core"),
        ImportViolation("frontend_bridge_core/plugin_updates.py", "core"),
        ImportViolation("frontend_bridge_core/runtime_dependencies.py", "core"),
        ImportViolation("frontend_bridge_core/templates.py", "core"),
        ImportViolation("frontend_bridge_core/templates.py", "llm"),
        ImportViolation("frontend_bridge_core/templates.py", "ui"),
        ImportViolation("frontend_bridge_core/tts.py", "ui"),
        ImportViolation("sdk/cli/registry_ops.py", "core"),
        ImportViolation("sdk/logging/configure.py", "core"),
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


def test_declared_dependency_matrix_has_an_explicit_rule() -> None:
    assert frozenset(FORBIDDEN_IMPORTS) == DECLARED_LAYER_ROOTS


def test_migration_allowlist_never_exceeds_locked_o1_baseline() -> None:
    serialized_baseline = "\n".join(
        f"{violation.source}\0{violation.imported_root}"
        for violation in sorted(LOCKED_BASELINE_VIOLATIONS)
    )
    assert len(LOCKED_BASELINE_VIOLATIONS) == 56
    assert (
        hashlib.sha256(serialized_baseline.encode()).hexdigest()
        == LOCKED_BASELINE_SHA256
    ), "The locked O1 baseline is immutable; restore it instead of editing it."

    added = sorted(ALLOWED_VIOLATIONS - LOCKED_BASELINE_VIOLATIONS)
    assert not added, (
        "New import-boundary exceptions are forbidden. "
        f"Remove the dependency instead of extending the O1 baseline: {added}"
    )


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
