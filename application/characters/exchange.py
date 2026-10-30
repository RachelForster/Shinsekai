"""Prepare portable characters without committing or overwriting existing profiles."""

from __future__ import annotations

import json
import shutil
import stat
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from uuid import uuid4

import yaml

from config.schema import Character

_DOKI = "http://127.0.0.1:8000/api/character-packages"
_LIMIT = 2 * 1024**3


def list_doki():
    with urllib.request.urlopen(f"{_DOKI}/list", timeout=10) as response:
        return json.loads(response.read(2 * 1024**2))


def _relative(raw):
    value = str(raw or "").replace("\\", "/")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(p in {"", ".", ".."} or ":" in p for p in value.split("/")):
        raise ValueError("Invalid character package resource path")
    return path.as_posix()


def prepare_character(use_case, payload):
    """Import into a fresh resource directory; only the later Save commits config."""
    root = use_case._resource_paths.project_root if hasattr(use_case._resource_paths, "project_root") else Path(getattr(use_case._state, "project_root_dir", "") or Path.cwd())
    root = Path(root).resolve()
    token = uuid4().hex
    staged = root / "data" / "character_exchange" / token
    staged.mkdir(parents=True)
    if payload.get("dokiId"):
        from urllib.parse import quote
        request = urllib.request.Request(f"{_DOKI}/export/{quote(str(payload['dokiId']), safe='')}")
        source = staged / "source.char"
        with urllib.request.urlopen(request, timeout=300) as response, source.open("xb") as output:
            total = 0
            while chunk := response.read(1024**2):
                total += len(chunk)
                if total > _LIMIT:
                    raise ValueError("Character package exceeds 2 GB")
                output.write(chunk)
    else:
        source = use_case._file(payload.get("path"), field="character package")
    if source.suffix.lower() not in {".char", ".cha"}:
        raise ValueError("Select a .char character package")
    with zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        if len(entries) > 10000 or sum(i.file_size for i in entries) > _LIMIT:
            raise ValueError("Character package is too large")
        seen = set()
        for entry in entries:
            name = _relative(entry.filename.rstrip("/"))
            if name.casefold() in seen or stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                raise ValueError("Duplicate, encrypted or symbolic-link package entry")
            seen.add(name.casefold())
        if archive.getinfo("character.yaml").file_size > 2 * 1024**2:
            raise ValueError("Character configuration is too large")
        rows = yaml.safe_load(archive.read("character.yaml"))
        if not isinstance(rows, list) or not rows or not all(isinstance(c, dict) for c in rows):
            raise ValueError("Invalid character.yaml")
        if payload.get("previewOnly"):
            return {"characters": [{"index": i, "name": c.get("name", ""), "persona": c.get("character_setting", "")} for i, c in enumerate(rows)]}
        index = payload.get("index", 0)
        if not isinstance(index, int) or index < 0 or index >= len(rows):
            raise ValueError("Invalid character selection")
        incoming = rows[index]
        target = str(payload.get("targetName") or "")
        existing = use_case._character(target) if target else None
        data = existing.model_dump(mode="json") if existing else {}
        # Never merge arbitrary external fields, plugin configuration or personal content.
        allowed = {"name", "color", "character_setting", "character_brief", "sprites", "sprite_scale", "portrait_crop", "emotion_tags", "avatar_type", "avatars", "gpt_model_path", "sovits_model_path", "refer_audio_path", "prompt_text", "prompt_lang", "speech_speed", "speech_volume", "pronunciation_map", "emotion_resources"}
        for key in allowed:
            if key in incoming and incoming[key] is not None and incoming[key] != "":
                data[key] = incoming[key]
        # Updating a target preserves its name and identity; renaming remains an explicit edit.
        if target:
            data["name"] = target
        else:
            names = set(use_case._state.character_manager.get_character_name_list())
            if data.get("name") in names:
                raise ValueError("已有同名角色，请选择更新已有角色，或先修改角色包名称。")
        old_prefix = _relative(incoming.get("sprite_prefix") or "character")
        prefix = f"exchange_{token}"
        sprite_root = root / "data" / "sprite" / prefix
        speech_root = root / "data" / "speech" / prefix
        model_root = root / "data" / "models" / prefix
        def extract(name, destination):
            name = _relative(name)
            entry = archive.getinfo(name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                with archive.open(entry) as src, destination.open("xb") as dst:
                    shutil.copyfileobj(src, dst)
            return destination.resolve().as_posix()
        for entry in entries:
            if entry.is_dir():
                continue
            for source_prefix, destination in ((f"sprites/{old_prefix}/", sprite_root), (f"speech/{old_prefix}/", speech_root)):
                if entry.filename.startswith(source_prefix):
                    extract(entry.filename, destination / _relative(entry.filename[len(source_prefix):]))
        for key in ("gpt_model_path", "sovits_model_path", "refer_audio_path"):
            if incoming.get(key):
                name = _relative(incoming[key])
                data[key] = extract(name, model_root / PurePosixPath(name).name)
        if "sprites" in incoming:
            data["sprites"] = [dict(s) for s in incoming["sprites"]]
            for sprite in data["sprites"]:
                sprite["path"] = (sprite_root / PurePosixPath(str(sprite["path"]).replace("\\", "/")).name).as_posix()
                if sprite.get("voice_path"):
                    sprite["voice_path"] = (speech_root / PurePosixPath(str(sprite["voice_path"]).replace("\\", "/")).name).as_posix()
        if "emotion_resources" in incoming:
            data["emotion_resources"] = [{k: v for k, v in e.items() if k in {"tag", "voice_path", "voice_text", "voice_type", "voice_lang", "sprite_indices"}} for e in incoming["emotion_resources"]]
            for emotion in data["emotion_resources"]:
                if emotion.get("voice_path"):
                    emotion["voice_path"] = (speech_root / PurePosixPath(str(emotion["voice_path"]).replace("\\", "/")).name).as_posix()
        if "avatars" in incoming:
            for bank in data.get("avatars", {}).values():
                if bank.get("model_path"):
                    bank["model_path"] = (sprite_root / _relative(bank["model_path"])).as_posix()
                for sprite in bank.get("sprites", []):
                    sprite["path"] = (sprite_root / _relative(sprite["path"])).as_posix()
                    if sprite.get("voice_path"):
                        sprite["voice_path"] = (sprite_root / _relative(sprite["voice_path"])).as_posix()
        for sprite in data.get("sprites", []):
            if not Path(sprite["path"]).is_file() or (sprite.get("voice_path") and not Path(sprite["voice_path"]).is_file()):
                raise ValueError("角色包引用的立绘或语音资源缺失。")
        for emotion in data.get("emotion_resources", []):
            if emotion.get("voice_path") and not Path(emotion["voice_path"]).is_file():
                raise ValueError("角色包引用的情绪语音资源缺失。")
        data.update({"sprite_prefix": prefix, "color": data.get("color") or "#d07d7d"})
        return {"character": Character.model_validate(data).model_dump(mode="json"), "originalName": target}
