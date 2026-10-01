"""Shared model import/state operations; formats only interpret files."""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from pathlib import Path

from config.schema import ModelSprites, Sprite
from core.media.avatar.registry import adapter_for
from sdk.path_utils import safe_child_path


def import_model_states(use_case, body: dict) -> dict:
    """Stage an entire batch, then publish it with one rollback-safe config write."""
    name, kind = str(body["name"]), str(body["avatar_type"]).strip().lower()
    paths = body["source_paths"]
    if not isinstance(paths, list) or not 1 <= len(paths) <= 100:
        raise ValueError("Select between 1 and 100 preset files")
    character = use_case._character(name)
    expected = character.model_dump(mode="json")
    bank = character.avatars[kind].model_copy(deep=True)
    bank.sprites = [Sprite.model_validate(sprite) for sprite in bank.sprites]
    if bank.model_path != body["model_path"]:
        raise ValueError("Model changed; refresh and retry")
    model = use_case._file(bank.model_path, field="model")
    sources = [use_case._file(path, field="preset") for path in paths]
    adapter = adapter_for(kind)
    batch = f"states/{uuid.uuid4().hex}"
    final = safe_child_path(model.parent, batch)
    tags_to_add: list[str] = []
    with tempfile.TemporaryDirectory(prefix=".import-", dir=model.parent) as directory:
        staged = Path(directory)
        for index, source in enumerate(sources):
            # Managed names avoid URL-unsafe exporter filenames and collisions.
            relative = f"{index}/preset{source.suffix.lower()}"
            target = safe_child_path(staged, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                adapter.import_state(model, source, f"{batch}/{relative}", body["state"])
                shutil.copy2(source, target)
                value = adapter.import_state(model, target, f"{batch}/{relative}", body["state"])
            except ValueError as error:
                raise ValueError(f"{source.name}: {error}") from error
            target.with_name("state.json").write_text(
                json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8"
            )
            tags_to_add.append(" ".join(source.stem.splitlines()))
        with use_case._mutation_lock:
            if use_case._character(name).model_dump(mode="json") != expected:
                raise ValueError("Character changed during preset import; refresh and retry")
            try:
                shutil.copytree(staged, final)
                for index in range(len(sources)):
                    path = final / str(index) / "state.json"
                    adapter.parse_state(model, json.loads(path.read_text(encoding="utf-8")))
                    bank.sprites.append(Sprite(path=path))
                from core.media.asset_tags import numbered_tags, tag_contents
                old_count = len(bank.sprites) - len(sources)
                tags = tag_contents(bank.emotion_tags, old_count)
                bank.emotion_tags = numbered_tags("立绘", [*tags, *tags_to_add])
                use_case._state.character_manager.save_avatar_bank(name, kind, bank)
            except Exception:
                if final.exists():
                    shutil.rmtree(final)
                raise
    return use_case._after_reload(name)


def import_model(use_case, body: dict) -> dict:
    name, kind = str(body["name"]), str(body["avatar_type"]).strip().lower()
    character = use_case._character(name)
    expected = character.model_dump(mode="json")
    source = use_case._file(body["source_path"], field="model entry")
    adapter = adapter_for(kind)
    files = adapter.inspect(source)
    # Each dependency is separately checked against the input grant.
    for file in files.files:
        use_case._file(str(file), field="model dependency")
    root = safe_child_path(use_case._resource_paths.project_root, "data/sprite")
    parent = safe_child_path(root, f"{character.sprite_prefix}/avatars/{kind}")
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".import-", dir=parent) as directory:
        staged = Path(directory)
        for file in files.files:
            target = safe_child_path(staged, file.relative_to(files.entry.parent).as_posix())
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, target)
        adapter.inspect(staged / files.entry.name)
        final = parent / uuid.uuid4().hex
        with use_case._mutation_lock:
            current = use_case._character(name)
            if current.model_dump(mode="json") != expected:
                raise ValueError("Character changed during model import; refresh and retry")
            # Old files remain recoverable, but are not validated for this model.
            # Publish no old states/tags until the user saves states for the new model.
            bank = ModelSprites(model_path=str(final / files.entry.name))
            try:
                shutil.copytree(staged, final)
                use_case._state.character_manager.save_avatar_bank(name, kind, bank, activate=True)
            except Exception:
                if final.exists():
                    shutil.rmtree(final)
                raise
    return use_case._after_reload(name)


def save_model_state(use_case, body: dict) -> dict:
    name, kind = str(body["name"]), str(body["avatar_type"]).strip().lower()
    index = body["sprite_index"]
    if isinstance(index, bool) or not isinstance(index, int) or index < -1:
        raise ValueError("Invalid sprite_index")
    with use_case._mutation_lock:
        character = use_case._character(name)
        bank = character.avatars[kind].model_copy(deep=True)
        bank.sprites = [Sprite.model_validate(sprite) for sprite in bank.sprites]
        if bank.model_path != body["model_path"]:
            raise ValueError("Model changed; refresh and retry")
        if index == -1:
            if body["path"]:
                raise ValueError("Append requires an empty path")
        elif index >= len(bank.sprites) or str(bank.sprites[index].path) != body["path"]:
            raise ValueError("State changed; refresh and retry")
        model = use_case._file(bank.model_path, field="model")
        state = adapter_for(kind).parse_state(model, body["state"])
        # New immutable file first; config persistence is the commit point.
        target = safe_child_path(model.parent, f"states/{uuid.uuid4().hex}.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_text(json.dumps(state, ensure_ascii=False, allow_nan=False), encoding="utf-8")
            from core.media.asset_tags import numbered_tags, tag_contents
            tags = tag_contents(bank.emotion_tags, len(bank.sprites))
            sprite = Sprite(path=target) if index == -1 else bank.sprites[index].model_copy(update={"path": target})
            if index == -1:
                bank.sprites.append(sprite)
                tags.append(str(body["tags"]))
            else:
                bank.sprites[index] = sprite
                tags[index] = str(body["tags"])
            bank.emotion_tags = numbered_tags("立绘", tags)
            use_case._state.character_manager.save_avatar_bank(name, kind, bank)
        except Exception:
            target.unlink(missing_ok=True)
            raise
    return use_case._after_reload(name)
