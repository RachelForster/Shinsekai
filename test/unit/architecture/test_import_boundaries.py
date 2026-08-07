from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]

SOURCE_DIRECTORIES = (
    "ai",
    "application",
    "config",
    "core",
    "frontend_bridge_core",
    "i18n",
    "live",
    "plugin_system",
    "sdk",
    "tools",
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
_PRE_O5_MIGRATED_VIOLATIONS = frozenset(
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
        ImportViolation("core/handlers/ui_message_handler.py", "asr"),
        ImportViolation("core/media/auto_annotation.py", "ai"),
        ImportViolation("core/runtime/workers.py", "ai"),
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
        ImportViolation("ai/memory/extraction.py", "llm"),
        ImportViolation("ai/vision/service.py", "llm"),
        ImportViolation("config/character_manager.py", "llm"),
        ImportViolation("config/config_manager.py", "core"),
        ImportViolation("config/config_manager.py", "llm"),
        ImportViolation("config/config_manager.py", "t2i"),
        ImportViolation("config/config_manager.py", "tts"),
        ImportViolation("core/sprite/chat_history.py", "llm"),
        ImportViolation("frontend_bridge_core/config.py", "asr"),
        ImportViolation("frontend_bridge_core/config.py", "llm"),
        ImportViolation("frontend_bridge_core/config.py", "t2i"),
        ImportViolation("frontend_bridge_core/config.py", "tts"),
        ImportViolation("frontend_bridge_core/mcp.py", "llm"),
        ImportViolation("sdk/manager.py", "config"),
        ImportViolation("sdk/manager.py", "llm"),
        ImportViolation("sdk/register.py", "llm"),
        ImportViolation("sdk/tool_registry.py", "llm"),
    }
)

# O5 retires the final compatibility paths. The immutable set above remains as
# an audit baseline, but no active dependency violation is accepted.
ALLOWED_VIOLATIONS = frozenset()


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


def _dynamic_imported_roots(source: Path) -> set[str]:
    """Return literal roots passed to ``importlib.import_module``."""

    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if not (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id == "importlib"
            and function.attr == "import_module"
            and node.args
        ):
            continue
        module = node.args[0]
        if isinstance(module, ast.Constant) and isinstance(module.value, str):
            imported_roots.add(module.value.partition(".")[0])
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


def test_legacy_ai_namespaces_do_not_depend_on_application() -> None:
    """O4 may migrate legacy AI code into ``ai`` but must not invert the DAG."""

    unexpected: list[ImportViolation] = []
    for source in _python_sources():
        relative = source.relative_to(REPO_ROOT).as_posix()
        source_root = relative.partition("/")[0]
        if source_root not in {"asr", "llm", "t2i", "tts"}:
            continue
        if "application" in _imported_roots(source):
            unexpected.append(ImportViolation(relative, "application"))

    assert not unexpected, (
        "Legacy AI implementations must use sdk/core contracts instead of "
        f"depending on application: {sorted(unexpected)}"
    )


def test_application_does_not_own_concrete_network_transport() -> None:
    """Concrete HTTP/WebSocket adapters belong to frontend_bridge_core."""

    forbidden_transport_roots = {"http", "socket", "websocket", "websockets"}
    unexpected: list[ImportViolation] = []
    application_root = REPO_ROOT / "application"
    for source in sorted(application_root.rglob("*.py")):
        relative = source.relative_to(REPO_ROOT).as_posix()
        for imported_root in sorted(
            _imported_roots(source) & forbidden_transport_roots
        ):
            unexpected.append(ImportViolation(relative, imported_root))

    assert not unexpected, (
        "Move concrete network transports to frontend_bridge_core/transport: "
        f"{unexpected}"
    )


def test_core_story_remains_resource_io_free() -> None:
    """Story filesystem and YAML orchestration belongs to application/story."""

    forbidden_imports = {"os", "shutil", "subprocess", "tempfile", "yaml"}
    forbidden_names = {"open"}
    forbidden_attributes = {
        "glob",
        "is_dir",
        "is_file",
        "iterdir",
        "mkdir",
        "read_bytes",
        "read_text",
        "rename",
        "rglob",
        "unlink",
        "write_bytes",
        "write_text",
    }
    unexpected: list[str] = []
    story_root = REPO_ROOT / "core" / "story"
    for source in sorted(story_root.rglob("*.py")):
        relative = source.relative_to(REPO_ROOT).as_posix()
        imported = _imported_roots(source) & forbidden_imports
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        for name in sorted(
            imported
            | (names & forbidden_names)
            | (attributes & forbidden_attributes)
        ):
            unexpected.append(f"{relative}: {name}")

    assert not unexpected, (
        "Move story file/YAML/resource orchestration to application/story: "
        f"{unexpected}"
    )


def test_core_story_unit_tests_do_not_import_application() -> None:
    story_tests = REPO_ROOT / "test" / "unit" / "core" / "story"
    unexpected = [
        source.relative_to(REPO_ROOT).as_posix()
        for source in sorted(story_tests.rglob("*.py"))
        if "application" in _imported_roots(source)
    ]

    assert (
        not unexpected
    ), f"Keep core/story unit tests isolated from application: {unexpected}"


def test_config_does_not_hide_forbidden_dynamic_imports() -> None:
    """Dynamic imports must not bypass the declared config dependency rule."""

    unexpected: list[ImportViolation] = []
    config_root = REPO_ROOT / "config"
    forbidden = FORBIDDEN_IMPORTS["config"]
    for source in sorted(config_root.rglob("*.py")):
        relative = source.relative_to(REPO_ROOT).as_posix()
        for imported_root in sorted(
            _dynamic_imported_roots(source) & forbidden
        ):
            unexpected.append(ImportViolation(relative, imported_root))

    assert not unexpected, (
        "Config must not hide forbidden dependencies behind importlib: "
        f"{unexpected}"
    )


def test_application_does_not_own_desktop_open_actions() -> None:
    """Opening desktop files belongs to a bridge/platform adapter."""

    unexpected: list[str] = []
    application_root = REPO_ROOT / "application"
    for source in sorted(application_root.rglob("*.py")):
        if "webbrowser" in _imported_roots(source):
            unexpected.append(source.relative_to(REPO_ROOT).as_posix())

    assert not unexpected, (
        "Move desktop open actions to frontend_bridge_core: "
        f"{unexpected}"
    )


def test_file_tool_wrappers_do_not_implement_filesystem_operations() -> None:
    """The LLM-facing file tools must delegate to the core media service."""

    source = REPO_ROOT / "ai" / "tools" / "file_tools.py"
    implementation_roots = {
        "mimetypes",
        "os",
        "platform",
        "shutil",
        "subprocess",
        "tarfile",
        "zipfile",
    }

    assert not (_imported_roots(source) & implementation_roots), (
        "Move filesystem implementations to core/media/file_operations.py"
    )


def test_frontend_bridge_does_not_own_runtime_implementations() -> None:
    bridge_root = REPO_ROOT / "frontend_bridge_core"
    forbidden_modules = {"subprocess", "tarfile", "zipfile"}
    offenders: list[tuple[str, str]] = []
    for source in sorted(bridge_root.rglob("*.py")):
        relative = source.relative_to(REPO_ROOT).as_posix()
        for imported_root in _imported_roots(source) & forbidden_modules:
            offenders.append((relative, imported_root))

    assert not (bridge_root / "handler.py").exists()
    assert (bridge_root / "routes" / "api.py").is_file()
    assert not offenders, (
        "Transport adapters must call application use cases instead of owning "
        f"process/archive implementations: {offenders}"
    )


def test_mobile_access_respects_application_and_transport_boundaries() -> None:
    """Keep lifecycle in application and concrete listeners in the bridge."""

    core_implementation = REPO_ROOT / "core" / "mobile_access"
    application_use_case = (
        REPO_ROOT / "application" / "chat" / "mobile_access.py"
    )
    bridge_transport = (
        REPO_ROOT
        / "frontend_bridge_core"
        / "transport"
        / "mobile_access.py"
    )
    route_source = (
        REPO_ROOT / "frontend_bridge_core" / "routes" / "api.py"
    ).read_text(encoding="utf-8")

    assert not list(core_implementation.rglob("*.py")), (
        "Mobile chat access is not a framework-neutral core capability."
    )
    assert application_use_case.is_file()
    assert bridge_transport.is_file()
    assert "mobile_access_service" not in route_source, (
        "Routes must call the application mobile-access use case instead of "
        "reaching through BridgeState to the transport adapter."
    )


def test_active_host_code_does_not_import_legacy_ai_namespaces() -> None:
    legacy_roots = {"asr", "llm", "t2i", "tts"}
    source_roots = (
        "ai",
        "application",
        "config",
        "core",
        "frontend_bridge_core",
        "main.py",
        "plugin_system",
        "sdk",
        "tools",
    )
    offenders: list[tuple[str, str]] = []
    for relative_root in source_roots:
        root = REPO_ROOT / relative_root
        sources = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for source in sources:
            relative = source.relative_to(REPO_ROOT).as_posix()
            for imported_root in _imported_roots(source) & legacy_roots:
                offenders.append((relative, imported_root))

    assert not offenders, f"Active host code must use ai.*: {offenders}"
