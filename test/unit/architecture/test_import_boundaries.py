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

CORE_FORBIDDEN_APPLICATION_RUNTIME_NAMES = frozenset(
    {
        "AppRuntime",
        "BridgeState",
        "get_app_runtime",
        "set_app_runtime",
        "try_get_app_runtime",
    }
)

CORE_FORBIDDEN_APPLICATION_MANAGER_NAMES = frozenset(
    {
        "llm_manager",
        "ui_playback",
        "ui_update_manager",
        "ui_updates",
        "ui_worker",
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
    imported_roots.update(_literal_dynamic_imported_roots(tree))
    return imported_roots


def _literal_dynamic_imported_roots(tree: ast.AST) -> set[str]:
    """Return literal roots loaded through importlib or ``__import__``."""

    importlib_aliases = {"importlib"}
    import_module_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib":
                    importlib_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            for alias in node.names:
                if alias.name == "import_module":
                    import_module_aliases.add(alias.asname or alias.name)

    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        is_importlib_call = (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id in importlib_aliases
            and function.attr == "import_module"
        )
        is_import_module_call = (
            isinstance(function, ast.Name)
            and function.id in import_module_aliases
        )
        is_builtin_import = (
            isinstance(function, ast.Name) and function.id == "__import__"
        )
        if not node.args or not (
            is_importlib_call or is_import_module_call or is_builtin_import
        ):
            continue
        module = node.args[0]
        if isinstance(module, ast.Constant) and isinstance(module.value, str):
            imported_roots.add(module.value.partition(".")[0])
    return imported_roots


def _dynamic_imported_roots(source: Path) -> set[str]:
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    return _literal_dynamic_imported_roots(tree)


def _referenced_names(tree: ast.AST) -> set[str]:
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names.update(
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    )
    return names


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


def test_literal_dynamic_imports_are_dependency_edges(tmp_path: Path) -> None:
    source = tmp_path / "dynamic_imports.py"
    source.write_text(
        "\n".join(
            (
                "import importlib as loader",
                "from importlib import import_module as load",
                'loader.import_module("application.runtime")',
                'load("frontend_bridge_core.routes")',
                '__import__("ai.llm")',
                'load(variable_module)',
            )
        ),
        encoding="utf-8",
    )

    assert _dynamic_imported_roots(source) == {
        "ai",
        "application",
        "frontend_bridge_core",
    }
    assert _imported_roots(source) >= {
        "ai",
        "application",
        "frontend_bridge_core",
    }


def test_core_does_not_reference_application_runtime_owners() -> None:
    unexpected: list[str] = []
    core_root = REPO_ROOT / "core"
    for source in sorted(core_root.rglob("*.py")):
        relative = source.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(
            source.read_text(encoding="utf-8"), filename=str(source)
        )
        referenced_names = _referenced_names(tree)
        for name in sorted(
            referenced_names & CORE_FORBIDDEN_APPLICATION_RUNTIME_NAMES
        ):
            unexpected.append(f"{relative}: {name}")

    assert not unexpected, (
        "Application runtime/session ownership must not move into core; pass a "
        f"narrow protocol, callback, or value instead: {unexpected}"
    )


def test_core_does_not_receive_application_managers() -> None:
    unexpected: list[str] = []
    core_root = REPO_ROOT / "core"
    for source in sorted(core_root.rglob("*.py")):
        relative = source.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(
            source.read_text(encoding="utf-8"), filename=str(source)
        )
        for name in sorted(
            _referenced_names(tree) & CORE_FORBIDDEN_APPLICATION_MANAGER_NAMES
        ):
            unexpected.append(f"{relative}: {name}")

    assert not unexpected, (
        "Core capabilities must receive narrow callbacks/protocols instead of "
        f"application managers: {unexpected}"
    )


def test_application_owns_chat_composition_and_presentation() -> None:
    expected_application_modules = (
        REPO_ROOT / "application" / "chat" / "effects.py",
        REPO_ROOT / "application" / "chat" / "initial_sprite.py",
        REPO_ROOT / "application" / "chat" / "turn_wiring.py",
    )
    retired_core_modules = (
        REPO_ROOT / "core" / "messaging" / "chat_turn_wiring.py",
        REPO_ROOT / "core" / "sprite" / "initial_sprite.py",
    )

    assert all(path.is_file() for path in expected_application_modules)
    assert not any(path.exists() for path in retired_core_modules)
    assert not list((REPO_ROOT / "core").rglob("*wiring.py")), (
        "Composition roots and manager wiring belong to application."
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


def test_effect_bridge_remains_a_transport_adapter() -> None:
    """O8 PR 1 keeps effect resource/config ownership in application."""

    adapter = REPO_ROOT / "frontend_bridge_core" / "effects.py"
    use_case = REPO_ROOT / "application" / "effects" / "management.py"
    retired_use_case = REPO_ROOT / "application" / "media" / "effects.py"
    forbidden_modules = {
        "config",
        "os",
        "pathlib",
        "shutil",
        "tempfile",
        "tools",
        "yaml",
        "zipfile",
    }
    route_source = (
        REPO_ROOT / "frontend_bridge_core" / "routes" / "api.py"
    ).read_text(encoding="utf-8")
    retired_entries = {
        "_delete_all_effect_audio",
        "_delete_effect_audio",
        "_effect_dir",
        "_import_effect_paths",
        "_save_effect_audio_tags",
        "_upload_effect_audio",
        "file_util.export_effect",
        "file_util.import_effect",
    }

    assert use_case.is_file()
    assert not retired_use_case.exists()
    assert not (_imported_roots(adapter) & forbidden_modules), (
        "Effect bridge code may parse/serialize requests but must not own file, "
        "archive, or config implementations."
    )
    assert not {entry for entry in retired_entries if entry in route_source}, (
        "Effect routes must use EffectUseCase.execute as their single entry point."
    )


def test_main_delegates_conversation_branch_management() -> None:
    """Keep branch use cases testable outside the process entry point."""

    entrypoint = REPO_ROOT / "main.py"
    use_case = REPO_ROOT / "application" / "chat" / "manage_branches.py"
    session_runtime = REPO_ROOT / "application" / "chat" / "session_runtime.py"
    streaming_wiring = REPO_ROOT / "application" / "chat" / "wire_streaming_session.py"
    source = entrypoint.read_text(encoding="utf-8")
    session_source = session_runtime.read_text(encoding="utf-8")
    wiring_source = streaming_wiring.read_text(encoding="utf-8")
    retired_implementations = {
        "def _active_branch_id",
        "def _branch_tree_payload",
        "def _branches",
        "def _default_branch_state",
        "def _fork_history_branch",
        "def _load_initial_branch_state",
        "def _persist_branch_state",
        "def _rename_history_branch",
        "def _switch_history_branch",
        "load_branch_state(",
        "save_branch_state(",
    }

    assert use_case.is_file()
    assert "ConversationBranchManager(" in wiring_source
    assert not {
        item
        for item in retired_implementations
        if item in source or item in session_source or item in wiring_source
    }, "main.py must delegate branch state and operations to manage_branches.py."


def test_main_delegates_realtime_chat_commands() -> None:
    """Keep command behavior in application and envelopes in transport."""

    entrypoint = REPO_ROOT / "main.py"
    use_case = REPO_ROOT / "application" / "chat" / "commands.py"
    transport = REPO_ROOT / "frontend_bridge_core" / "transport" / "chat_commands.py"
    session_runtime = REPO_ROOT / "application" / "chat" / "session_runtime.py"
    streaming_wiring = REPO_ROOT / "application" / "chat" / "wire_streaming_session.py"
    session_transport = (
        REPO_ROOT / "frontend_bridge_core" / "transport" / "chat_session.py"
    )
    source = entrypoint.read_text(encoding="utf-8")
    use_case_source = use_case.read_text(encoding="utf-8")
    transport_source = transport.read_text(encoding="utf-8")
    session_source = session_runtime.read_text(encoding="utf-8")
    wiring_source = streaming_wiring.read_text(encoding="utf-8")
    session_transport_source = session_transport.read_text(encoding="utf-8")
    retired_implementations = {
        'command_type == "send-message"',
        'command_type == "clear-history"',
        'command_type == "reroll"',
        'command_type == "pause-asr"',
        'command_type == "fork-history"',
        'command_type == "switch-branch"',
        'command_type == "rename-branch"',
        '"type": "cmd.ack"',
    }

    assert use_case.is_file()
    assert transport.is_file()
    assert "wire_streaming_session(" in session_source
    assert "ChatCommandDispatcher(" in wiring_source
    assert "request = parse_chat_command(raw_command)" in session_transport_source
    assert "result = dispatcher.execute(request)" in session_transport_source
    assert "send_chat_command_ack(" in session_transport_source
    assert not {
        item
        for item in retired_implementations
        if item in source or item in session_source or item in wiring_source
    }, "main.py must only compose the realtime command application use case."
    assert "cmdId" not in use_case_source
    assert "cmd.ack" not in use_case_source
    assert "cmdId" not in session_source
    assert "cmd.ack" not in session_source
    assert "cmdId" not in wiring_source
    assert "cmd.ack" not in wiring_source
    assert '"type": "cmd.ack"' in transport_source


def test_main_delegates_chat_startup_assembly() -> None:
    """Keep providers, templates, hooks, and fallback policy out of main.py."""

    entrypoint = REPO_ROOT / "main.py"
    startup = REPO_ROOT / "application" / "chat" / "startup.py"
    session_runtime = REPO_ROOT / "application" / "chat" / "session_runtime.py"
    source = entrypoint.read_text(encoding="utf-8")
    startup_source = startup.read_text(encoding="utf-8")
    session_source = session_runtime.read_text(encoding="utf-8")
    retired_implementations = {
        "ensure_plugins_loaded(",
        "LLMAdapterFactory.create_adapter(",
        "TTSAdapterFactory.create_adapter(",
        "T2IAdapterFactory.create_adapter(",
        "install_memory_hooks(",
        "get_llm_api_config(",
        "get_gpt_sovits_config(",
        "data/character_templates",
    }

    assert startup.is_file()
    assert "class ChatStartupContext:" in startup_source
    for field in (
        "config:",
        "llm_manager:",
        "tts_manager:",
        "t2i_manager:",
        "plugin_manager:",
        "messages:",
    ):
        assert field in startup_source
    assert "startup = create_chat_startup_context(" in session_source
    assert not {
        item
        for item in retired_implementations
        if item in source or item in session_source
    }, "main.py must consume ChatStartupContext instead of assembling providers."


def test_main_delegates_chat_session_lifecycle() -> None:
    """Keep workflow, runtime, presentation, and shutdown outside main.py."""

    entrypoint = REPO_ROOT / "main.py"
    session_runtime = REPO_ROOT / "application" / "chat" / "session_runtime.py"
    presentation = REPO_ROOT / "application" / "chat" / "presentation.py"
    source = entrypoint.read_text(encoding="utf-8")
    session_source = session_runtime.read_text(encoding="utf-8")
    presentation_source = presentation.read_text(encoding="utf-8")
    retired_lifecycle = {
        "AppRuntime(",
        "build_runtime_workflow(",
        "shutdown_chat_runtime(",
        "StreamingUIUpdateManager(",
        "HeadlessUIUpdateManager(",
        "restore_session_presentation(",
        "display_initial_sprite(",
        "ConversationBranchManager(",
        "ChatCommandDispatcher(",
    }

    assert len(source.splitlines()) <= 150
    assert "class StreamingChatSession(" in session_source
    assert "class HeadlessChatSession(" in session_source
    assert "session = create_chat_session(options, transport)" in source
    assert "session.run()" in source
    assert "prepare_initial_presentation(" in session_source
    assert "restore_session_presentation(" in presentation_source
    assert not {item for item in retired_lifecycle if item in source}


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
