"""Structural and compatibility checks for decomposed ``ai.memory`` packages."""

from __future__ import annotations

import ast
from pathlib import Path

from ai.memory import config, migration, onnx_validation, operations

MEMORY_ROOT = Path(__file__).resolve().parents[4] / "ai" / "memory"


def _imported_memory_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("ai.memory"):
                    imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("ai.memory"):
            imported.add(node.module)
    return imported


def test_onnx_validation_stays_independent_of_config() -> None:
    validation_file = MEMORY_ROOT / "onnx_validation.py"
    assert validation_file.is_file()
    assert "ai.memory.config" not in _imported_memory_modules(validation_file)
    assert config.resolve_safe_snapshot_file is onnx_validation.resolve_safe_snapshot_file
    assert config.validate_onnx_model_file is onnx_validation.validate_onnx_model_file


def test_migration_subpackage_dag_and_facade_exports() -> None:
    migration_dir = MEMORY_ROOT / "migration"
    assert migration_dir.is_dir()
    for name in (
        "errors.py",
        "unpickler.py",
        "qdrant_reader.py",
        "memory_runner.py",
        "knowledge_runner.py",
        "__init__.py",
    ):
        assert (migration_dir / name).is_file(), name

    assert not _imported_memory_modules(migration_dir / "errors.py")
    assert _imported_memory_modules(migration_dir / "unpickler.py") <= {
        "ai.memory.migration.errors",
    }
    assert _imported_memory_modules(migration_dir / "qdrant_reader.py") <= {
        "ai.memory.migration.errors",
        "ai.memory.migration.unpickler",
    }
    for exported in migration.__all__:
        assert hasattr(migration, exported), exported


def test_operations_subpackage_dag_and_facade_exports() -> None:
    ops_dir = MEMORY_ROOT / "operations"
    assert ops_dir.is_dir()
    for name in (
        "context.py",
        "service_client.py",
        "queries.py",
        "mutations.py",
        "rollback.py",
        "__init__.py",
    ):
        assert (ops_dir / name).is_file(), name

    assert not _imported_memory_modules(ops_dir / "context.py")
    for leaf in ("service_client.py", "queries.py", "mutations.py", "rollback.py"):
        sibling_imports = {
            mod
            for mod in _imported_memory_modules(ops_dir / leaf)
            if mod.startswith("ai.memory.operations.")
        }
        assert sibling_imports <= {"ai.memory.operations.context"}, (leaf, sibling_imports)

    for exported in operations.__all__:
        assert hasattr(operations, exported), exported
