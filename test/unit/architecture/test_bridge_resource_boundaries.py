from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def _imported_roots(source: Path) -> set[str]:
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.partition(".")[0])
    return roots


def _called_attributes(tree: ast.AST) -> set[str]:
    return {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def test_background_bridge_delegates_resource_mutations_to_one_use_case_entry() -> None:
    source = REPO_ROOT / "frontend_bridge_core" / "backgrounds.py"
    text = source.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(source))
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    migrated_manager_calls = {
        "add_background",
        "delete_all_bgms",
        "delete_all_sprites",
        "delete_background",
        "delete_single_bgm",
        "delete_single_sprite",
        "upload_bgms",
        "upload_sprites",
    }

    assert "_execute_background_request" in functions
    assert not (_called_attributes(tree) & migrated_manager_calls)
    assert not (_imported_roots(source) & {"os", "shutil", "tempfile", "tools", "yaml", "zipfile"})
    assert "BackgroundUseCase(state, file_access_roots=roots).execute(request)" in text

    routes = (REPO_ROOT / "frontend_bridge_core" / "routes" / "api.py").read_text(encoding="utf-8")
    assert "_import_background_paths" not in routes
    assert "file_util.import_background" not in routes
    assert "file_util.export_background" not in routes
    assert "background_manager.delete_background" not in routes


def test_character_bridge_delegates_resource_mutations_to_one_use_case_entry() -> None:
    source = REPO_ROOT / "frontend_bridge_core" / "characters.py"
    text = source.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(source))
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    migrated_manager_calls = {
        "add_character",
        "delete_all_sprites",
        "delete_character",
        "delete_single_sprite",
        "delete_sprite_voice",
        "save_sprite_voice_text",
        "save_sprite_voice_type",
        "upload_sprites",
        "upload_voice",
    }

    assert "_execute_character_request" in functions
    assert not (_called_attributes(tree) & migrated_manager_calls)
    assert not (_imported_roots(source) & {"os", "shutil", "tempfile", "tools", "yaml", "zipfile"})
    assert "CharacterUseCase(state, file_access_roots=roots).execute(request)" in text

    routes = (REPO_ROOT / "frontend_bridge_core" / "routes" / "api.py").read_text(encoding="utf-8")
    assert "file_util.import_character" not in routes
    assert "file_util.export_character" not in routes
    assert "character_manager.delete_character" not in routes
