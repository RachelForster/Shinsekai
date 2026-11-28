"""Authorize declared model dependencies and current or historical states."""

from itertools import chain
from pathlib import Path

from config.sprite_files import sprite_field
from core.media.avatar.registry import adapter_for
from core.media.avatar.state_dependencies import indexed_state_files
from sdk.path_utils import is_portable_relative_path, safe_child_path, safe_existing_file_path


def owned_model_file(project_root: Path, sprite_prefix: str, kind: str, model_path: str) -> Path:
    owned_root = safe_child_path(project_root, f"data/sprite/{sprite_prefix}/avatars/{kind}")
    return safe_existing_file_path(model_path, roots=[owned_root])


def model_file(state, model_path: str, relative_path: str) -> Path:
    if not is_portable_relative_path(relative_path) or any(c in relative_path for c in ":?#%"):
        raise PermissionError("Invalid model dependency path")
    root = Path(state.project_root_dir)
    for character in state.config_manager.config.characters:
        for kind, bank in character.avatars.items():
            if bank.model_path != model_path:
                continue
            # Only application-owned imported packages may be served.
            model = owned_model_file(root, character.sprite_prefix, kind, model_path)
            target = safe_child_path(model.parent, relative_path)
            adapter = adapter_for(kind)
            if target in adapter.inspect(model).files:
                return target
            paths = chain(
                (sprite_field(sprite, "path", "") for sprite in bank.sprites),
                character.avatar_state_history.get(model_path, ()),
            )
            for path in paths:
                try:
                    saved = safe_existing_file_path(path, roots=[model.parent])
                    dependencies = indexed_state_files(model, saved, kind)
                except (ValueError, OSError, KeyError):
                    # Invalid legacy entries must not block declared model dependencies.
                    continue
                if target == saved or target in dependencies:
                    return target
            raise PermissionError("File is not a configured model dependency")
    raise PermissionError("Model is not configured")
