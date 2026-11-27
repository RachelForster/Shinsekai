"""Pass-through character package (``.char`` / ``.cha``) export and staged import."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

import yaml

from config.models import Character
from i18n import tr
from core.packaging.zip_io import (
    format_restored_path,
    resolve_name_conflict,
    resolve_sprite_prefix_conflict,
    rollback_staged_assets,
    safe_extract_zip,
    safe_package_basename,
    safe_package_basename_or_legacy_absolute,
    safe_package_name,
    safe_package_relpath,
    write_directory_zip,
)
from core.sprite.transitions import field as transition_field, valid_transitions
from sdk.path_utils import safe_existing_file_path

RESERVED_CHARACTER_PACKAGE_FIELDS = frozenset(
    {"id", "display_name", "is_builtin", "pinned", "undeletable"}
)


def _character_to_export_dict(character_or_config: Any) -> dict[str, Any]:
    """Serialize any Character or compatibility wrapper via Pass-Through model_dump."""
    if isinstance(character_or_config, Character):
        dumped = character_or_config.model_dump(
            mode="json",
            exclude=set(RESERVED_CHARACTER_PACKAGE_FIELDS),
        )
    elif hasattr(character_or_config, "to_character"):
        dumped = character_or_config.to_character().model_dump(
            mode="json",
            exclude=set(RESERVED_CHARACTER_PACKAGE_FIELDS),
        )
    elif hasattr(character_or_config, "model_dump"):
        dumped = character_or_config.model_dump(
            mode="json",
            exclude=set(RESERVED_CHARACTER_PACKAGE_FIELDS),
        )
    else:
        raw = (
            dict(character_or_config)
            if isinstance(character_or_config, Mapping)
            else dict(getattr(character_or_config, "__dict__", {}))
        )
        for reserved in RESERVED_CHARACTER_PACKAGE_FIELDS:
            raw.pop(reserved, None)
        dumped = deepcopy(raw)

    # Preserve legacy empty relation_graph representation & reset transitions for validated export.
    rel = dumped.get("relation_graph")
    if isinstance(rel, dict) and not rel.get("nodes") and not rel.get("edges"):
        dumped["relation_graph"] = {}
    dumped["sprite_transitions"] = []
    return dumped


def export_character_package(
    characters: Sequence[Any],
    output_path: str | os.PathLike[str],
    *,
    sprite_dir: Path,
    speech_dir: Path,
    model_dir: Path,
) -> Path:
    """Export one or more characters and bundled media into a ``.char`` / ``.cha`` archive."""
    del model_dir  # Model weights live at configured paths collected from each character.
    from core.media.asset_import import ignore_pending_batches
    from core.media.avatar.registry import adapter_for, is_registered_format
    from core.sprite.mouth.manifest import valid_mouth_sync

    with tempfile.TemporaryDirectory(prefix="shinsekai-char-export-") as raw_temp:
        temp_dir = Path(raw_temp)
        manifest_data: dict[str, Any] = {"original_paths": {}}
        character_data_list: list[dict[str, Any]] = []

        for config in characters:
            char_data = _character_to_export_dict(config)
            prefix = safe_package_name(char_data.get("sprite_prefix", ""), "sprite_prefix")

            # 1) Voice model weights & reference audio.
            for key in ("gpt_model_path", "sovits_model_path", "refer_audio_path"):
                abs_path = char_data.get(key)
                if abs_path and os.path.exists(abs_path):
                    file_path = Path(abs_path)
                    new_relative_path = Path("models") / file_path.name
                    manifest_data["original_paths"][file_path.name] = str(file_path)
                    destination_path = temp_dir / new_relative_path
                    destination_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file_path, destination_path)
                    char_data[key] = str(new_relative_path)
                else:
                    char_data[key] = None

            if not char_data.get("default_voice_name"):
                char_data.pop("default_voice_name", None)
            if not char_data.get("voice_profiles"):
                char_data.pop("voice_profiles", None)
            for index, voice in enumerate((char_data.get("voice_profiles") or {}).values()):
                voice_dir = Path("models") / prefix / "voice_profiles" / str(index)
                for key in ("gpt_model_path", "sovits_model_path", "refer_audio_path"):
                    abs_path = voice.get(key)
                    if abs_path and os.path.exists(abs_path):
                        file_path = Path(abs_path)
                        new_relative_path = voice_dir / key / file_path.name
                        manifest_data["original_paths"][new_relative_path.as_posix()] = str(file_path)
                        destination_path = temp_dir / new_relative_path
                        destination_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(file_path, destination_path)
                        voice[key] = new_relative_path.as_posix()
                    else:
                        voice[key] = None

            # 2) Static sprites directory & path rewriting.
            if prefix:
                sprite_source_dir = sprite_dir / prefix
                if sprite_source_dir.is_dir():
                    shutil.copytree(
                        sprite_source_dir,
                        temp_dir / "sprites" / prefix,
                        dirs_exist_ok=True,
                        ignore=ignore_pending_batches,
                    )

            sprites = char_data.get("sprites") or []
            normalized_sprites: list[dict[str, Any]] = []
            for sprite in sprites if isinstance(sprites, list) else []:
                sprite_data = (
                    sprite.model_dump(mode="json")
                    if hasattr(sprite, "model_dump")
                    else (dict(sprite) if isinstance(sprite, dict) else {"path": str(getattr(sprite, "path", ""))})
                )
                if sprite_data.get("path"):
                    sprite_data["path"] = safe_package_basename_or_legacy_absolute(
                        sprite_data["path"], "sprite path"
                    )
                else:
                    sprite_data["path"] = ""
                if sprite_data.get("voice_path"):
                    sprite_data["voice_path"] = safe_package_basename_or_legacy_absolute(
                        sprite_data["voice_path"], "voice_path"
                    )
                if sprite_data.get("mouth_sync"):
                    mouth = valid_mouth_sync(sprite)
                    if mouth:
                        base = (sprite_dir / prefix).resolve()
                        checked = safe_existing_file_path(mouth, roots=[base])
                        sprite_data["mouth_sync"] = checked.relative_to(base).as_posix()
                    else:
                        sprite_data.pop("mouth_sync", None)
                if sprite_data.get("voice_type") is None and "voice_type" in sprite_data:
                    del sprite_data["voice_type"]
                if not sprite_data.get("voice_profile_id"):
                    sprite_data.pop("voice_profile_id", None)
                if "group" in sprite_data and not sprite_data["group"]:
                    del sprite_data["group"]
                normalized_sprites.append(sprite_data)
            if isinstance(sprites, list):
                char_data["sprites"] = normalized_sprites

            # 3) Verified sprite transition clips.
            for edge in valid_transitions(config):
                clip = safe_existing_file_path(
                    transition_field(edge, "path"),
                    roots=[sprite_dir / prefix],
                )
                relative = Path("transitions") / clip.name
                destination = temp_dir / "sprites" / prefix / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(clip, destination)
                char_data["sprite_transitions"].append(
                    {
                        **dict(edge),
                        "path": relative.as_posix(),
                        "from_path": safe_package_basename_or_legacy_absolute(
                            transition_field(edge, "from_path"), "transition source"
                        ),
                        "to_path": safe_package_basename_or_legacy_absolute(
                            transition_field(edge, "to_path"), "transition target"
                        ),
                    }
                )

            # 4) Dynamic avatar banks & dependency closure.
            source_root = sprite_dir / prefix
            speech_root = speech_dir / prefix
            for kind, bank in (char_data.get("avatars") or {}).items():
                if not isinstance(bank, dict) or not bank.get("model_path") or not is_registered_format(kind):
                    continue
                if not Path(bank["model_path"]).is_file():
                    continue
                model = safe_existing_file_path(bank["model_path"], roots=[source_root])
                adapter = adapter_for(kind)
                files = set(adapter.inspect(model).files)
                for sprite in bank.get("sprites", []):
                    state_file = safe_existing_file_path(sprite["path"], roots=[model.parent])
                    state = adapter.parse_state(
                        model, json.loads(state_file.read_text(encoding="utf-8"))
                    )
                    files.add(state_file)
                    files.update(adapter.state_files(model, state))
                    if sprite.get("voice_path"):
                        voice = safe_existing_file_path(
                            sprite["voice_path"],
                            roots=[
                                speech_root,
                                model.parent,
                                source_root / "avatar-voices" / kind,
                            ],
                        )
                        relative_voice = Path("avatar-voices") / kind / voice.name
                        destination = temp_dir / "sprites" / prefix / relative_voice
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(voice, destination)
                        sprite["voice_path"] = relative_voice.as_posix()
                    sprite["path"] = state_file.relative_to(source_root.resolve()).as_posix()
                for dep_file in files:
                    checked = safe_existing_file_path(dep_file, roots=[source_root])
                    destination = (
                        temp_dir
                        / "sprites"
                        / prefix
                        / checked.relative_to(source_root.resolve())
                    )
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(checked, destination)
                bank["model_path"] = model.relative_to(source_root.resolve()).as_posix()

            # 5) Voice audio directory.
            if prefix:
                voice_src_dir = speech_dir / prefix
                if voice_src_dir.is_dir():
                    shutil.copytree(
                        voice_src_dir,
                        temp_dir / "speech" / prefix,
                        dirs_exist_ok=True,
                    )

            character_data_list.append(char_data)

        (temp_dir / "character.yaml").write_text(
            yaml.safe_dump(character_data_list, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        (temp_dir / "manifest.json").write_text(
            json.dumps(manifest_data, indent=4, ensure_ascii=False),
            encoding="utf-8",
        )
        return write_directory_zip(temp_dir, output_path)
