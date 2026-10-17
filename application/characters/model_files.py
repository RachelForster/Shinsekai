"""Authorize only declared model dependencies and saved states, never a directory."""

from pathlib import Path

from core.media.avatar.registry import adapter_for
from core.media.avatar.state_dependencies import indexed_state_files
from sdk.path_utils import is_portable_relative_path, safe_child_path, safe_existing_file_path


def model_file(state, model_path: str, relative_path: str) -> Path:
    if not is_portable_relative_path(relative_path) or any(c in relative_path for c in ":?#%"):
        raise PermissionError("Invalid model dependency path")
    root = Path(state.project_root_dir)
    for character in state.config_manager.config.characters:
        for kind, bank in character.avatars.items():
            if bank.model_path != model_path:
                continue
            # Only application-owned imported packages may be served.
            owned_root = safe_child_path(root, f"data/sprite/{character.sprite_prefix}/avatars/{kind}")
            model = safe_existing_file_path(model_path, roots=[owned_root])
            target = safe_child_path(model.parent, relative_path)
            adapter = adapter_for(kind)
            allowed = set(adapter.inspect(model).files)
            if target in allowed:
                return target
            for sprite in bank.sprites:
                try:
                    sprite_path = sprite.get("path", "") if isinstance(sprite, dict) else sprite.path
                    saved = safe_existing_file_path(sprite_path, roots=[model.parent])
                    dependencies = indexed_state_files(model, saved, kind)
                    allowed.add(saved)
                    allowed.update(dependencies)
                except (ValueError, OSError, KeyError):
                    # Invalid legacy entries must not block declared model dependencies.
                    continue
                if target in allowed:
                    return target
            raise PermissionError("File is not a configured model dependency")
    raise PermissionError("Model is not configured")
