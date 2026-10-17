"""Recover preset transactions before the bridge accepts requests."""

from pathlib import Path

from application.characters.management import CharacterUseCase
from core.media.asset_import import PENDING_MARKER, recover_asset_batches
from core.media.avatar.registry import adapter_for
from core.media.avatar.state_dependencies import indexed_state_files
from sdk.path_utils import safe_child_path, safe_existing_path


def recover_model_imports(state) -> None:
    root = Path(state.project_root_dir)
    with CharacterUseCase._mutation_lock:
        sprite_root = safe_child_path(root, "data/sprite")
        parents = set()
        # Include replaced/deleted banks: an interrupted batch may no longer
        # live beneath the current model. Only the reserved managed tree is scanned.
        for owned in sprite_root.glob("*/avatars/*"):
            try:
                checked = safe_child_path(sprite_root, owned.relative_to(sprite_root))
                for marker in checked.rglob(PENDING_MARKER):
                    bounded = safe_child_path(checked, marker.relative_to(checked))
                    if bounded == marker and marker.parent.parent.name == "states":
                        parents.add(marker.parent.parent)
            except (OSError, ValueError):
                continue

        def is_referenced(batch):
            # Read the durable commit after acquiring this batch's OS lease.
            # Another process may have committed since startup loaded config.
            state.config_manager.reload()
            for character in state.config_manager.config.characters:
                for kind, bank in character.avatars.items():
                    if not bank.model_path:
                        continue
                    owned = safe_child_path(root, f"data/sprite/{character.sprite_prefix}/avatars/{kind}")
                    model = safe_existing_path(bank.model_path, roots=[owned])
                    references = {model}
                    if model.parent == batch.parent.parent:
                        # Also preserve a model's declared texture dependencies.
                        references.update(adapter_for(kind).inspect(model).files)
                        for sprite in bank.sprites:
                            raw = sprite.get("path", "") if isinstance(sprite, dict) else sprite.path
                            saved = safe_existing_path(raw, roots=[model.parent])
                            references.add(saved)
                            if batch in saved.parents:
                                return True
                            references.update(indexed_state_files(model, saved, kind))
                    if any(path == batch or batch in path.parents for path in references):
                        return True
            return False

        for parent in parents:
            recover_asset_batches(parent, is_referenced)
