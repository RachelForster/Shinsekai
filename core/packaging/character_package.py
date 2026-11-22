"""Pass-through character package (``.char`` / ``.cha``) export and staged import."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any
from uuid import uuid4
import zipfile

import yaml

from config.models import (
    Character,
    RelationGraph,
    SELF_PERSONA_NAME,
    SELF_PERSONA_SPRITE_PREFIX,
)
from config.sprite_voice import normalize_sprite_voice_types
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


@dataclass(slots=True)
class StagedCharacterImport:
    """Staged character entities and newly created media dirs awaiting DB commit."""

    characters: list[Character] = field(default_factory=list)
    raw_dicts: list[dict[str, Any]] = field(default_factory=list)
    created_dirs: list[Path] = field(default_factory=list)


def _rename_relation_graph_owner(
    graph_data: Any,
    old_name: str,
    new_name: str,
) -> dict[str, Any]:
    graph = (
        graph_data
        if isinstance(graph_data, RelationGraph)
        else RelationGraph.model_validate(deepcopy(graph_data) if graph_data is not None else {})
    )
    value = graph.model_dump(mode="json")
    for node in value["nodes"]:
        if node["key"] == old_name:
            node["key"] = new_name
    for edge in value["edges"]:
        for endpoint in ("source", "target"):
            if edge[endpoint] == old_name:
                edge[endpoint] = new_name
    validated = RelationGraph.model_validate(value)
    return validated.model_dump(mode="json", exclude_none=True)


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


def stage_character_package_import(
    input_path: str | os.PathLike[str],
    *,
    existing_names: Iterable[str],
    existing_prefixes: Iterable[str],
    sprite_dir: Path,
    speech_dir: Path,
    model_dir: Path,
    cwd_base: Path | None = None,
) -> StagedCharacterImport:
    """Validate an archive, copy media into destination folders, and build Character models."""
    archive_path = Path(input_path)
    if not archive_path.exists():
        raise FileNotFoundError(tr("crud.common.archive_not_found", path=input_path))

    staged = StagedCharacterImport()
    try:
        with tempfile.TemporaryDirectory(prefix="shinsekai-char-import-") as raw_temp:
            temp_dir = Path(raw_temp)
            with zipfile.ZipFile(archive_path, "r") as zf:
                safe_extract_zip(zf, temp_dir)

            yaml_path = temp_dir / "character.yaml"
            yaml_data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if not yaml_data:
                raise ValueError(tr("crud.common.char_yaml_empty"))
            if not isinstance(yaml_data, list) or not all(
                isinstance(char_data, dict) for char_data in yaml_data
            ):
                raise ValueError(tr("crud.common.char_yaml_not_list"))

            # Validate every entry schema and all bundled dependencies before publishing assets.
            from core.media.alpha_video import verify_alpha_video
            from core.media.asset_import import PENDING_MARKER
            from core.media.avatar.registry import adapter_for, is_registered_format
            from core.media.avatar.state_dependencies import write_state_index
            from core.sprite.mouth.manifest import read_manifest

            for raw_entry in yaml_data:
                Character.model_validate(normalize_sprite_voice_types(dict(raw_entry)))

            for char_data in yaml_data:
                prefix = safe_package_name(char_data.get("sprite_prefix", ""), "sprite_prefix")
                package_root = temp_dir / "sprites" / prefix
                for sprite in char_data.get("sprites") or []:
                    if isinstance(sprite, dict) and sprite.get("mouth_sync"):
                        relative = safe_package_relpath(sprite["mouth_sync"], "mouth sync")
                        if relative.parts[0] != "mouth-sync" or relative.name != "manifest.json":
                            raise ValueError("Invalid mouth sync bundle path")
                        read_manifest(safe_existing_file_path(relative, roots=[package_root]))
                for edge in char_data.get("sprite_transitions") or []:
                    relative = safe_package_relpath(edge["path"], "transition clip")
                    if relative.parts[0] != "transitions" or relative.suffix.lower() != ".webm":
                        raise ValueError("Invalid transition clip path")
                    checked_clip = safe_existing_file_path(relative, roots=[package_root])
                    expected_frames = edge.get("frame_count", 5)
                    if expected_frames not in {5, 22} or verify_alpha_video(checked_clip) != expected_frames:
                        raise ValueError("Transition clip frame count does not match its metadata")
                    for key in ("from_path", "to_path"):
                        safe_package_basename(edge[key], "transition endpoint")
                for kind, bank in (char_data.get("avatars") or {}).items():
                    if not isinstance(bank, dict) or not is_registered_format(kind) or not bank.get("model_path"):
                        continue
                    try:
                        relative = safe_package_relpath(bank["model_path"], "avatar model")
                    except ValueError:
                        continue
                    if not (package_root / relative).is_file():
                        continue
                    model = safe_existing_file_path(relative, roots=[package_root])
                    adapter = adapter_for(kind)
                    adapter.inspect(model)
                    if any(model.parent.rglob(PENDING_MARKER)):
                        raise ValueError("Character package contains an uncommitted avatar import")
                    for sprite in bank.get("sprites", []):
                        saved = safe_existing_file_path(sprite["path"], roots=[package_root])
                        saved = safe_existing_file_path(saved, roots=[model.parent])
                        parsed = adapter.parse_state(model, json.loads(saved.read_text(encoding="utf-8")))
                        write_state_index(adapter, model, saved, parsed)

            imported_names = {SELF_PERSONA_NAME, *(str(n) for n in existing_names if n)}
            imported_prefixes = {
                SELF_PERSONA_SPRITE_PREFIX,
                *(str(p) for p in existing_prefixes if p),
            }

            for raw_entry in yaml_data:
                char_data = deepcopy(raw_entry)
                for reserved_flag in RESERVED_CHARACTER_PACKAGE_FIELDS:
                    char_data.pop(reserved_flag, None)
                char_data["id"] = uuid4().hex

                original_name = str(char_data.get("name") or "")
                original_prefix = safe_package_name(
                    char_data.get("sprite_prefix", ""), "sprite_prefix"
                )
                new_name = resolve_name_conflict(original_name, imported_names)
                char_data["name"] = new_name
                if char_data.get("relation_graph"):
                    char_data["relation_graph"] = _rename_relation_graph_owner(
                        char_data["relation_graph"],
                        original_name,
                        new_name,
                    )
                imported_names.add(new_name)

                new_prefix = resolve_sprite_prefix_conflict(original_prefix, imported_prefixes)
                char_data["sprite_prefix"] = new_prefix
                imported_prefixes.add(new_prefix)

                dest_sprite_dir = sprite_dir / new_prefix
                dest_speech_dir = speech_dir / new_prefix
                source_sprite_dir = temp_dir / "sprites" / original_prefix

                if new_prefix and source_sprite_dir.is_dir():
                    existed = dest_sprite_dir.exists()
                    shutil.copytree(source_sprite_dir, dest_sprite_dir, dirs_exist_ok=True)
                    if not existed:
                        staged.created_dirs.append(dest_sprite_dir)

                if new_prefix:
                    source_speech_dir = temp_dir / "speech" / original_prefix
                    if source_speech_dir.is_dir():
                        existed = dest_speech_dir.exists()
                        shutil.copytree(source_speech_dir, dest_speech_dir, dirs_exist_ok=True)
                        if not existed:
                            staged.created_dirs.append(dest_speech_dir)

                sprites = char_data.get("sprites") or []
                for sprite in sprites:
                    if not isinstance(sprite, dict):
                        continue
                    filename = safe_package_basename_or_legacy_absolute(
                        sprite.get("path", ""), "sprite path"
                    )
                    if new_prefix:
                        sprite["path"] = format_restored_path(dest_sprite_dir / filename, cwd_base)
                    else:
                        sprite["path"] = filename

                    if sprite.get("voice_path"):
                        voice_filename = safe_package_basename_or_legacy_absolute(
                            sprite["voice_path"], "voice_path"
                        )
                        if new_prefix:
                            sprite["voice_path"] = format_restored_path(
                                dest_speech_dir / voice_filename, cwd_base
                            )
                        else:
                            sprite["voice_path"] = voice_filename
                        voice_type = str(sprite.get("voice_type") or "").strip().lower()
                        if voice_type:
                            if voice_type not in {"fallback", "preset", "reference"}:
                                raise ValueError(
                                    f"voice_type must be fallback, preset, or reference: {voice_type!r}"
                                )
                            sprite["voice_type"] = voice_type
                        else:
                            sprite["voice_type"] = (
                                "reference"
                                if str(sprite.get("voice_text") or "").strip()
                                else "fallback"
                            )

                    if sprite.get("mouth_sync"):
                        relative = safe_package_relpath(sprite["mouth_sync"], "mouth sync")
                        sprite["mouth_sync"] = (dest_sprite_dir / relative).resolve().as_posix()

                for key in ("gpt_model_path", "sovits_model_path", "refer_audio_path"):
                    raw_model_rel = char_data.get(key)
                    if not raw_model_rel:
                        continue
                    source_model_path = temp_dir / safe_package_relpath(raw_model_rel, key)
                    dest_model_dir = model_dir / new_prefix
                    existed = dest_model_dir.exists()
                    dest_model_dir.mkdir(parents=True, exist_ok=True)
                    if not existed:
                        staged.created_dirs.append(dest_model_dir)
                    dest_model_path = dest_model_dir / safe_package_basename(raw_model_rel, key)
                    if source_model_path.exists():
                        shutil.copy2(source_model_path, dest_model_path)
                        char_data[key] = dest_model_path.as_posix()
                    else:
                        char_data[key] = None

                for edge in char_data.get("sprite_transitions") or []:
                    edge["path"] = (
                        dest_sprite_dir
                        / safe_package_relpath(edge["path"], "transition clip")
                    ).resolve().as_posix()
                    for endpoint_key in ("from_path", "to_path"):
                        endpoint = dest_sprite_dir / safe_package_basename(
                            edge[endpoint_key], "transition endpoint"
                        )
                        edge[endpoint_key] = format_restored_path(endpoint, cwd_base)

                for kind, bank in (char_data.get("avatars") or {}).items():
                    if not isinstance(bank, dict):
                        continue
                    model_text = bank.get("model_path", "")
                    if not model_text or not new_prefix:
                        continue
                    try:
                        model_relative = safe_package_relpath(model_text, "avatar model")
                    except ValueError:
                        continue
                    if not (source_sprite_dir / model_relative).is_file():
                        continue
                    bank["model_path"] = (dest_sprite_dir / model_relative).resolve().as_posix()
                    for sprite in bank.get("sprites", []):
                        sprite["path"] = (
                            dest_sprite_dir
                            / safe_package_relpath(sprite["path"], "avatar state")
                        ).resolve().as_posix()
                        if sprite.get("voice_path"):
                            sprite["voice_path"] = (
                                dest_sprite_dir
                                / safe_package_relpath(sprite["voice_path"], "avatar voice")
                            ).resolve().as_posix()

                model = Character.model_validate(normalize_sprite_voice_types(dict(char_data)))
                staged.characters.append(model)
                staged.raw_dicts.append(char_data)
        return staged
    except BaseException:
        rollback_staged_assets(staged.created_dirs)
        raise


__all__ = [
    "RESERVED_CHARACTER_PACKAGE_FIELDS",
    "StagedCharacterImport",
    "export_character_package",
    "stage_character_package_import",
]
