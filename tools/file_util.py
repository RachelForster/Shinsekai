import os
import threading
import zipfile
import yaml
import json
import re
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from config.character_config import CharacterConfig
from config.schema import Background
from config.config_manager import ConfigManager
from core.archive_paths import (
    extract_zip_safely,
    write_directory_to_zip_without_links,
    write_zip_files_without_links,
)
from core.file_transactions import (
    atomic_binary_writer,
    atomic_write_text,
    copy_directory_without_links,
    copy_file_exclusive,
    create_private_temporary_directory,
    file_snapshot_is_stable,
    open_binary_read_without_links,
    portable_name_key,
    read_text_without_links,
    remove_directory_without_links,
    remove_link_without_following,
    snapshot_directory_entries_without_links,
)
from core.paths import (
    _metadata_is_link_or_reparse_point,
    managed_child_path,
    managed_project_storage,
    path_is_link_or_reparse_point,
    portable_project_path,
    project_root as runtime_project_root,
    resolve_managed_project_path,
    resolve_project_output_path,
    resolve_project_path,
    resolve_runtime_asset_read_path,
    require_directory_without_links,
    require_symlink_free_absolute_path,
    safe_path_component,
    safe_path_component_with_suffix,
)
from core.process_launch import open_with_default_application
from typing import List
import platform
import subprocess

# 定义项目的基础数据路径
BASE_DATA_PATH = Path('data')
SPRITE_DIR = BASE_DATA_PATH / 'sprite'
SPEECH_DIR = BASE_DATA_PATH / 'speech'
MODEL_DIR = BASE_DATA_PATH / 'models'
CONFIG_DIR = BASE_DATA_PATH / 'config'
CHARACTERS_CONFIG_PATH = CONFIG_DIR / 'characters.yaml'
BACKGROUND_CONFIG_PATH = CONFIG_DIR / 'background.yaml'
BACKGROUND_UPLOAD_DIR = BASE_DATA_PATH / 'backgrounds'
BGM_UPLOAD_DIR = BASE_DATA_PATH / 'bgm'
EFFECT_UPLOAD_DIR = BASE_DATA_PATH / 'effects'

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_PACKAGE_IO_LOCK = threading.RLock()


@dataclass(frozen=True)
class _PackagePaths:
    project_root: Path | None
    sprite: Path
    speech: Path
    models: Path
    config: Path
    characters_config: Path
    backgrounds: Path
    bgm: Path
    effects: Path


def _package_paths(project_root: str | os.PathLike | None) -> _PackagePaths:
    """Resolve package storage once, independent of later cwd changes.

    Direct callers without an explicit root still use the legacy configurable
    globals, but relative globals are anchored to the authoritative project
    root instead of the process working directory.  Absolute test/integration
    overrides retain their explicit meaning.
    """

    if project_root is None:
        root = runtime_project_root()

        def anchored(value: str | os.PathLike, *, file_path: bool = False) -> Path:
            path = Path(value).expanduser()
            if not path.is_absolute():
                resolver = resolve_managed_project_path if file_path else managed_project_storage
                return resolver(value, root=root)
            try:
                path.relative_to(root)
            except ValueError:
                return require_symlink_free_absolute_path(
                    path,
                    field="package storage path",
                )
            return resolve_managed_project_path(value, root=root)

        return _PackagePaths(
            project_root=root,
            sprite=anchored(SPRITE_DIR),
            speech=anchored(SPEECH_DIR),
            models=anchored(MODEL_DIR),
            config=anchored(CONFIG_DIR),
            characters_config=anchored(CHARACTERS_CONFIG_PATH, file_path=True),
            backgrounds=anchored(BACKGROUND_UPLOAD_DIR),
            bgm=anchored(BGM_UPLOAD_DIR),
            effects=anchored(EFFECT_UPLOAD_DIR),
        )

    root = resolve_project_path(".", root=project_root)
    config = managed_project_storage("data/config", root=root)
    paths = _PackagePaths(
        project_root=root,
        sprite=managed_project_storage("data/sprite", root=root),
        speech=managed_project_storage("data/speech", root=root),
        models=managed_project_storage("data/models", root=root),
        config=config,
        characters_config=resolve_managed_project_path(
            "data/config/characters.yaml",
            root=root,
        ),
        backgrounds=managed_project_storage("data/backgrounds", root=root),
        bgm=managed_project_storage("data/bgm", root=root),
        effects=managed_project_storage("data/effects", root=root),
    )
    return paths


def _resolve_io_path(
    value: str | os.PathLike,
    paths: _PackagePaths,
    *,
    writable: bool = False,
) -> Path:
    if paths.project_root is not None:
        if writable:
            return resolve_project_output_path(value, root=paths.project_root)
        return resolve_runtime_asset_read_path(value, root=paths.project_root)
    return Path(value).expanduser()


def _stored_path(value: Path, paths: _PackagePaths) -> str:
    if paths.project_root is not None:
        return portable_project_path(value, root=paths.project_root)
    return value.as_posix()


def _package_storage_child(
    paths: _PackagePaths,
    storage: Path,
    component: str,
    *,
    field: str,
) -> Path:
    """Resolve one storage child and recheck project-owned ancestors."""

    name = safe_path_component(component, field=field)
    unresolved = storage / name
    if paths.project_root is not None:
        try:
            unresolved.relative_to(paths.project_root)
        except ValueError:
            pass
        else:
            return resolve_managed_project_path(
                unresolved,
                root=paths.project_root,
            )
    return managed_child_path(storage, name, field=field)


_OwnedDirectory = tuple[Path, os.stat_result]


def _new_package_temp_dir(kind: str) -> _OwnedDirectory:
    return create_private_temporary_directory(prefix=f"shinsekai-{kind}-")


def _existing_storage_names(*roots: Path) -> set[str]:
    names: set[str] = set()
    for root in roots:
        try:
            _root, _identity, entries = (
                snapshot_directory_entries_without_links(
                    root,
                    field="package storage directory",
                )
            )
            names.update(child.name for child, _metadata in entries)
        except (FileNotFoundError, NotADirectoryError):
            continue
    return names


def _write_yaml_atomic(path: Path, data: object) -> None:
    atomic_write_text(
        path,
        yaml.dump(data, allow_unicode=True, sort_keys=False),
    )


@contextmanager
def _atomic_package_output(output: Path):
    """Publish a complete archive without clobbering a valid older export."""

    with atomic_binary_writer(output) as staging:
        yield staging


def _record_import_directory(path: Path, created: list[_OwnedDirectory]) -> Path:
    exact = require_directory_without_links(
        path,
        field="package import directory",
    )
    created.append((exact, exact.lstat()))
    return exact


def _reserve_import_directory(
    path: Path,
    created: list[_OwnedDirectory],
    *,
    expected_parent_identity: os.stat_result | None = None,
) -> None:
    """Reserve a previously conflict-checked directory without following links."""

    path.parent.mkdir(parents=True, exist_ok=True)
    parent = require_directory_without_links(
        path.parent,
        field="package import parent directory",
    )
    parent_identity = parent.lstat()
    if (
        expected_parent_identity is not None
        and not os.path.samestat(
            expected_parent_identity,
            parent_identity,
        )
    ):
        raise PermissionError(
            f"package import parent identity changed: {parent}"
        )
    if os.path.lexists(path):
        raise FileExistsError(f"import target already exists: {path}")
    path.mkdir()
    created_path = _record_import_directory(path, created)
    if not os.path.samestat(parent_identity, parent.lstat()):
        created_identity = created[-1][1]
        remove_directory_without_links(
            created_path,
            expected_identity=created_identity,
        )
        created.pop()
        raise PermissionError(
            f"package import parent identity changed: {parent}"
        )


def _rollback_import_directories(created: list[_OwnedDirectory]) -> None:
    for path, expected_identity in reversed(created):
        try:
            metadata = path.lstat()
            if not os.path.samestat(expected_identity, metadata):
                continue
            if _metadata_is_link_or_reparse_point(metadata):
                remove_link_without_following(path, expected_identity=metadata)
            elif stat.S_ISDIR(metadata.st_mode):
                remove_directory_without_links(path, expected_identity=metadata)
        except (FileNotFoundError, OSError, ValueError):
            pass


def _cleanup_private_directory(path: Path, expected_identity: os.stat_result) -> None:
    try:
        remove_directory_without_links(path, expected_identity=expected_identity)
    except (FileNotFoundError, OSError, ValueError):
        pass


@contextmanager
def package_import_transaction():
    """Keep imported resources rollbackable until their YAML save succeeds.

    Package extraction and configuration persistence are one logical mutation.
    Callers pass the yielded list to ``import_background`` / ``import_effect``;
    any exception before leaving the context removes only directories created
    by those imports.  The process-local package lock also spans the YAML save,
    closing the former race between conflict selection and persistence.
    """

    created_directories: list[_OwnedDirectory] = []
    with _PACKAGE_IO_LOCK:
        try:
            yield created_directories
        except BaseException:
            _rollback_import_directories(created_directories)
            raise


def _unique_file_name(original: str, used_names: set[str]) -> str:
    name = safe_path_component(original, field="package filename")
    candidate = name
    counter = 1
    while portable_name_key(candidate) in used_names:
        source = Path(name)
        candidate = safe_path_component_with_suffix(
            source.stem,
            f"_{counter}{source.suffix}",
            field="package filename",
        )
        counter += 1
    used_names.add(portable_name_key(candidate))
    return candidate


def _open_export_folder(output_path: str | os.PathLike) -> None:
    folder_path = Path(output_path).parent
    try:
        folder_path = require_directory_without_links(
            folder_path,
            field="export directory",
        )
        open_with_default_application(
            folder_path,
            system_name=platform.system(),
            popen_factory=subprocess.Popen,
            startfile_factory=getattr(os, "startfile", None),
        )
    except Exception as e:
        print(f"Failed to open export folder {folder_path}: {e}")


def _safe_package_relpath(path: str | os.PathLike | None, field_name: str) -> Path:
    """Interpret package paths written on Windows or POSIX as safe relative paths."""
    raw = str(path or "").replace("\\", "/")
    if raw != raw.strip():
        raise ValueError(f"{field_name} contains surrounding whitespace: {path!r}")
    if not raw:
        raise ValueError(f"{field_name} must not be empty")
    if "\x00" in raw or raw.startswith("/") or _WINDOWS_DRIVE_RE.match(raw):
        raise ValueError(f"{field_name} must be a relative package path: {path!r}")
    if any(part in ("", ".", "..") for part in raw.split("/")):
        raise ValueError(f"{field_name} contains an unsafe path component: {path!r}")
    rel = PurePosixPath(raw)
    for component in rel.parts:
        safe_path_component(component, field=field_name)
    return Path(*rel.parts)


def _safe_package_basename(path: str | os.PathLike | None, field_name: str) -> str:
    return _safe_package_relpath(path, field_name).name


def _safe_package_basename_or_legacy_absolute(
    path: str | os.PathLike | None, field_name: str
) -> str:
    """Return a safe package filename, accepting old host-absolute YAML paths."""
    raw = str(path or "").replace("\\", "/")
    if raw != raw.strip():
        raise ValueError(f"{field_name} contains surrounding whitespace: {path!r}")
    if not raw:
        raise ValueError(f"{field_name} must not be empty")
    if "\x00" in raw:
        raise ValueError(f"{field_name} contains an unsafe path component: {path!r}")

    has_windows_drive = _WINDOWS_DRIVE_RE.match(raw)
    is_legacy_absolute = raw.startswith("/") or (
        has_windows_drive and raw[2:3] == "/"
    )
    if not is_legacy_absolute:
        return _safe_package_basename(raw, field_name)

    tail = raw[3:] if has_windows_drive else raw
    parts = tail.lstrip("/").split("/")
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"{field_name} contains an unsafe path component: {path!r}")
    return _safe_package_name(parts[-1], field_name)


def _safe_package_name(value: str | os.PathLike | None, field_name: str) -> str:
    raw = str(value or "").replace("\\", "/")
    if not raw:
        return ""
    if (
        "\x00" in raw
        or "/" in raw
        or raw in (".", "..")
        or _WINDOWS_DRIVE_RE.match(raw)
    ):
        raise ValueError(f"{field_name} must be a plain package name: {value!r}")
    return safe_path_component(raw, field=field_name)


def _safe_extract_zip(zf: zipfile.ZipFile, target_dir: Path) -> None:
    extract_zip_safely(zf, target_dir)


def _extract_package_zip(package_path: Path, target_dir: Path) -> None:
    try:
        package_identity = package_path.lstat()
    except FileNotFoundError:
        raise FileNotFoundError(f"文件未找到: {package_path}") from None
    if (
        _metadata_is_link_or_reparse_point(package_identity)
        or not stat.S_ISREG(package_identity.st_mode)
    ):
        raise FileNotFoundError(f"文件未找到: {package_path}")
    with open_binary_read_without_links(
        package_path,
        expected_identity=package_identity,
    ) as package_file:
        before = os.fstat(package_file.fileno())
        with zipfile.ZipFile(package_file, "r") as archive:
            _safe_extract_zip(archive, target_dir)
        after = os.fstat(package_file.fileno())
    if not file_snapshot_is_stable(before, after):
        raise PermissionError(
            f"package changed while it was extracted: {package_path}"
        )


def _sanitize_background_package_paths(bg_data: dict) -> None:
    sprites = bg_data.get('sprites') or []
    if isinstance(sprites, list):
        for sprite_entry in sprites:
            if isinstance(sprite_entry, dict) and sprite_entry.get('path'):
                sprite_entry['path'] = _safe_package_basename_or_legacy_absolute(
                    sprite_entry['path'], "background sprite path"
                )

    bgm_list = bg_data.get('bgm_list')
    if isinstance(bgm_list, list):
        bg_data['bgm_list'] = [
            _safe_package_basename_or_legacy_absolute(path, "background bgm path")
            for path in bgm_list
        ]

def export_character(
    character_configs: list[CharacterConfig],
    output_path: str,
    open_folder: bool = True,
    *,
    project_root: str | os.PathLike | None = None,
):
    """
    将人物配置及其依赖文件打包成一个 .cha 文件。
    
    Args:
        character_configs (list[CharacterConfig]): 要导出的 CharacterConfig 对象列表。
        output_path (str): 导出的 .cha 文件路径。
        open_folder (bool): 导出后是否打开输出目录。
    """
    paths = _package_paths(project_root)
    output = _resolve_io_path(output_path, paths, writable=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_dir, temp_dir_identity = _new_package_temp_dir("character-export")
    
    try:
        manifest_data = {'original_paths': {}}
        character_data_list = []
        used_model_names: set[str] = set()

        for config in character_configs:
            # 准备要写入YAML的配置数据
            char_data = {
                'name': config.name,
                'color': config.color,
                'sprite_prefix': config.sprite_prefix,
                'prompt_text': config.prompt_text,
                'prompt_lang': config.prompt_lang,
                'sprite_scale': config.sprite_scale,
                'sprites': config.sprites,
                'emotion_tags': config.emotion_tags,
                'character_setting': config.character_setting,
                'speech_speed': getattr(config, 'speech_speed', 1.0),
                'speech_volume': getattr(config, 'speech_volume', 1.0),
                'pronunciation_map': getattr(config, 'pronunciation_map', None) or {},
            }

            # 处理绝对路径的模型和参考音频
            model_paths = {
                'gpt_model_path': config.gpt_model_path,
                'sovits_model_path': config.sovits_model_path,
                'refer_audio_path': config.refer_audio_path
            }

            for key, abs_path in model_paths.items():
                file_path = _resolve_io_path(abs_path, paths) if abs_path else None
                if file_path is not None and file_path.is_file():
                    archive_name = _unique_file_name(file_path.name, used_model_names)
                    new_relative_path = Path('models') / archive_name

                    # 将模型的原始绝对路径记录到清单中
                    manifest_data['original_paths'][archive_name] = str(file_path)

                    # 将模型文件复制到临时目录
                    destination_path = copy_file_exclusive(
                        file_path,
                        temp_dir / new_relative_path.parent,
                        archive_name,
                        field="model filename",
                    )

                    # 更新YAML数据中的路径为相对路径
                    char_data[key] = new_relative_path.as_posix()
                else:
                    char_data[key] = None

            # 处理立绘文件
            if config.sprite_prefix:
                sprite_prefix = _safe_package_name(config.sprite_prefix, "sprite_prefix")
                sprite_source_dir = _package_storage_child(
                    paths,
                    paths.sprite,
                    sprite_prefix,
                    field="sprite_prefix",
                )
                if sprite_source_dir.is_dir():
                    copy_directory_without_links(
                        sprite_source_dir,
                        temp_dir / 'sprites' / sprite_prefix,
                    )

            # 重写 sprite/voice path 为仅文件名（导入时按文件名匹配重建路径）
            sprites = char_data.get('sprites') or []
            normalized_sprites = []
            for s in sprites if isinstance(sprites, list) else []:
                # 统一转为 dict（Pydantic Sprite 对象需显式转换，否则 yaml.dump 可能丢失数据）
                if hasattr(s, 'model_dump'):
                    sprite_data = s.model_dump()
                elif isinstance(s, dict):
                    sprite_data = dict(s)
                else:
                    sprite_data = {"path": str(getattr(s, "path", ""))}
                if sprite_data.get('path'):
                    sprite_data['path'] = _safe_package_basename_or_legacy_absolute(
                        sprite_data['path'], "sprite path"
                    )
                else:
                    sprite_data['path'] = ""
                if sprite_data.get('voice_path'):
                    sprite_data['voice_path'] = _safe_package_basename_or_legacy_absolute(
                        sprite_data['voice_path'], "voice_path"
                    )
                # 清理 voice_type 的 None 值，避免 YAML 中多余的 null
                if 'voice_type' in sprite_data and sprite_data['voice_type'] is None:
                    del sprite_data['voice_type']
                normalized_sprites.append(sprite_data)
            if isinstance(sprites, list):
                char_data['sprites'] = normalized_sprites

            # 复制语音文件
            if config.sprite_prefix:
                sprite_prefix = _safe_package_name(config.sprite_prefix, "sprite_prefix")
                voice_src_dir = _package_storage_child(
                    paths,
                    paths.speech,
                    sprite_prefix,
                    field="sprite_prefix",
                )
                if voice_src_dir.is_dir():
                    copy_directory_without_links(
                        voice_src_dir,
                        temp_dir / 'speech' / sprite_prefix,
                    )

            character_data_list.append(char_data)

        # 将配置数据和清单写入临时文件
        atomic_write_text(
            temp_dir / "character.yaml",
            yaml.dump(character_data_list, allow_unicode=True, sort_keys=False),
        )
        atomic_write_text(
            temp_dir / "manifest.json",
            json.dumps(manifest_data, indent=4),
        )
            
        # 打包成 .cha 文件
        with _atomic_package_output(output) as staging_output:
            with zipfile.ZipFile(staging_output, 'w', zipfile.ZIP_DEFLATED) as zf:
                write_directory_to_zip_without_links(zf, temp_dir)
        
        if open_folder:
            _open_export_folder(output)

        print(f"人物成功导出到: {output}")

    finally:
        # 清理临时目录
        _cleanup_private_directory(temp_dir, temp_dir_identity)

def _resolve_name_conflict(name: str, existing_names: set) -> str:
    """
    解决名称冲突，如果名称已存在则添加(1)、(2)等后缀。
    
    Args:
        name (str): 原始名称
        existing_names (set): 已存在的名称集合
        
    Returns:
        str: 解决冲突后的名称
    """
    if name not in existing_names:
        return name
    
    counter = 1
    new_name = f"{name}（{counter}）"
    while new_name in existing_names:
        counter += 1
        new_name = f"{name}（{counter}）"
    
    return new_name

def _resolve_sprite_prefix_conflict(sprite_prefix: str, existing_prefixes: set) -> str:
    """
    解决sprite_prefix冲突，如果前缀已存在则添加1、2等后缀。
    
    Args:
        sprite_prefix (str): 原始sprite_prefix
        existing_prefixes (set): 已存在的sprite_prefix集合
        
    Returns:
        str: 解决冲突后的sprite_prefix
    """
    folded_prefixes = {portable_name_key(str(value)) for value in existing_prefixes}
    if portable_name_key(sprite_prefix) not in folded_prefixes:
        return sprite_prefix
    
    counter = 1
    new_prefix = safe_path_component_with_suffix(
        sprite_prefix,
        str(counter),
        field="sprite_prefix",
    )
    while portable_name_key(new_prefix) in folded_prefixes:
        counter += 1
        new_prefix = safe_path_component_with_suffix(
            sprite_prefix,
            str(counter),
            field="sprite_prefix",
        )
    
    return new_prefix

def import_character(
    input_path: str,
    *,
    project_root: str | os.PathLike | None = None,
) -> list[CharacterConfig]:
    """Import a character package under one process-local mutation lock."""

    with _PACKAGE_IO_LOCK:
        return _import_character_unlocked(input_path, project_root=project_root)


def _import_character_unlocked(
    input_path: str,
    *,
    project_root: str | os.PathLike | None = None,
) -> list[CharacterConfig]:
    """
    从 .cha 文件导入人物配置及其依赖文件，并将配置追加入 characters.yaml。
    检测名称和sprite_prefix冲突，自动添加后缀解决冲突。
    
    Args:
        input_path (str): 要导入的 .cha 文件路径。
        
    Returns:
        list[CharacterConfig]: 导入的 CharacterConfig 对象列表。
    """
    paths = _package_paths(project_root)
    package_path = _resolve_io_path(input_path, paths)
    if not package_path.is_file():
        raise FileNotFoundError(f"文件未找到: {package_path}")

    temp_dir, temp_dir_identity = _new_package_temp_dir("character-import")
    
    imported_configs = []
    created_directories: list[_OwnedDirectory] = []
    committed = False

    try:
        # 解压 .cha 文件到临时目录
        _extract_package_zip(package_path, temp_dir)

        # 读取YAML配置文件
        yaml_data = yaml.safe_load(
            read_text_without_links(temp_dir / 'character.yaml')
        )

        if not yaml_data:
            raise ValueError("YAML配置文件为空或格式错误。")

        # 读取现有配置，用于检测冲突
        existing_names = set()
        existing_sprite_prefixes = set()
        
        if paths.characters_config.exists():
            existing_configs = yaml.safe_load(
                read_text_without_links(paths.characters_config)
            ) or []
            for config in existing_configs:
                existing_names.add(config.get('name', ''))
                existing_sprite_prefixes.add(config.get('sprite_prefix', ''))
        existing_sprite_prefixes.update(
            _existing_storage_names(paths.sprite, paths.speech, paths.models)
        )
        
        # 记录本次导入中已使用的名称和sprite_prefix，避免内部冲突
        imported_names = set(existing_names)
        imported_sprite_prefixes = set(existing_sprite_prefixes)

        for char_data in yaml_data:
            original_name = char_data.get('name', '')
            original_sprite_prefix = _safe_package_name(
                char_data.get('sprite_prefix', ''), "sprite_prefix"
            )
            
            # 解决名称冲突
            new_name = _resolve_name_conflict(original_name, imported_names)
            char_data['name'] = new_name
            imported_names.add(new_name)
            
            # 解决sprite_prefix冲突
            new_sprite_prefix = _resolve_sprite_prefix_conflict(original_sprite_prefix, imported_sprite_prefixes)
            char_data['sprite_prefix'] = new_sprite_prefix
            imported_sprite_prefixes.add(new_sprite_prefix)
            
            # 如果名称或sprite_prefix被修改，打印提示信息
            if new_name != original_name or new_sprite_prefix != original_sprite_prefix:
                print(f"检测到冲突，已将 '{original_name}' ({original_sprite_prefix}) 重命名为 '{new_name}' ({new_sprite_prefix})")
            
            sprites = char_data.get('sprites') or []
            dest_sprite_dir = (
                _package_storage_child(
                    paths,
                    paths.sprite,
                    new_sprite_prefix,
                    field="sprite_prefix",
                )
                if new_sprite_prefix
                else paths.sprite
            )
            dest_speech_dir = (
                _package_storage_child(
                    paths,
                    paths.speech,
                    new_sprite_prefix,
                    field="sprite_prefix",
                )
                if new_sprite_prefix
                else paths.speech
            )

            # 恢复立绘文件（使用新的sprite_prefix）
            if new_sprite_prefix:
                source_sprite_dir = temp_dir / 'sprites' / original_sprite_prefix
                if source_sprite_dir.is_dir():
                    _record_import_directory(
                        copy_directory_without_links(source_sprite_dir, dest_sprite_dir),
                        created_directories,
                    )

            # 修复 sprite path：指向导入机器上的实际路径；无 prefix 时至少去掉宿主机路径。
            for s in sprites:
                if isinstance(s, dict):
                    filename = _safe_package_basename_or_legacy_absolute(
                        s.get('path', ''), "sprite path"
                    )
                    if new_sprite_prefix:
                        new_path = dest_sprite_dir / filename
                        s['path'] = _stored_path(new_path, paths)
                    else:
                        s['path'] = filename

            if new_sprite_prefix:
                # 恢复语音文件（使用新的sprite_prefix）
                source_speech_dir = temp_dir / 'speech' / original_sprite_prefix
                if source_speech_dir.is_dir():
                    _record_import_directory(
                        copy_directory_without_links(source_speech_dir, dest_speech_dir),
                        created_directories,
                    )

            # 修复 voice_path：指向 SPEECH_DIR；无 prefix 时至少去掉宿主机路径。
            for s in sprites:
                if isinstance(s, dict) and s.get('voice_path'):
                    filename = _safe_package_basename_or_legacy_absolute(
                        s['voice_path'], "voice_path"
                    )
                    if new_sprite_prefix:
                        new_vp = dest_speech_dir / filename
                        s['voice_path'] = _stored_path(new_vp, paths)
                    else:
                        s['voice_path'] = filename
                    voice_type = str(s.get('voice_type') or '').strip().lower()
                    if voice_type:
                        if voice_type not in {'fallback', 'preset', 'reference'}:
                            raise ValueError(f"voice_type must be fallback, preset, or reference: {voice_type!r}")
                        s['voice_type'] = voice_type
                    else:
                        s['voice_type'] = 'reference' if str(s.get('voice_text') or '').strip() else 'fallback'
            
            # 恢复模型文件并更新路径
            model_paths = {
                'gpt_model_path': char_data.get('gpt_model_path'),
                'sovits_model_path': char_data.get('sovits_model_path'),
                'refer_audio_path': char_data.get('refer_audio_path')
            }
            
            dest_model_dir: Path | None = None
            for key, path in model_paths.items():
                if path:  # 确保路径不为空
                    source_model_path = temp_dir / _safe_package_relpath(path, key)
                    if source_model_path.is_file():  # 确保源文件存在
                        if dest_model_dir is None:
                            model_storage_prefix = new_sprite_prefix
                            if not model_storage_prefix:
                                model_storage_prefix = _resolve_sprite_prefix_conflict(
                                    "character-models",
                                    imported_sprite_prefixes,
                                )
                                imported_sprite_prefixes.add(model_storage_prefix)
                            dest_model_dir = _package_storage_child(
                                paths,
                                paths.models,
                                model_storage_prefix,
                                field="model storage prefix",
                            )
                            _reserve_import_directory(dest_model_dir, created_directories)
                        dest_model_path = copy_file_exclusive(
                            source_model_path,
                            dest_model_dir,
                            _safe_package_basename(path, key),
                            field=key,
                        )
                        char_data[key] = _stored_path(dest_model_path, paths)
                    else:
                        char_data[key] = None

            # 将更新后的数据创建为 CharacterConfig 对象
            imported_configs.append(CharacterConfig.parse_dic(char_data=char_data))
        
        # 将配置追加到 characters.yaml
        paths.config.mkdir(parents=True, exist_ok=True)
        
        existing_data = []
        if paths.characters_config.exists():
            existing_data = yaml.safe_load(
                read_text_without_links(paths.characters_config)
            ) or []

        # 将导入的配置转换为字典格式并追加
        new_data_list = [config.__dict__ for config in imported_configs]
        existing_data.extend(new_data_list)
        
        _write_yaml_atomic(paths.characters_config, existing_data)
        committed = True

        print(f"人物成功从 {package_path} 导入，并已将配置追加到 {paths.characters_config}。")
        return imported_configs

    finally:
        if not committed:
            _rollback_import_directories(created_directories)
        # 清理临时目录
        _cleanup_private_directory(temp_dir, temp_dir_identity)

# ---------------------------------------------


def export_background(
    background_configs: List[Background],
    output_path: str = 'output/background.bg',
    open_folder: bool = True,
    *,
    project_root: str | os.PathLike | None = None,
):
    """
    将背景配置及其依赖文件（图片和音乐）打包成一个 .bg 文件。
    
    Args:
        background_configs (List[Background]): 要导出的 Background 对象列表。
        output_path (str): 导出的 .bg 文件路径 (默认路径为 output/background.bg)。
        open_folder (bool): 导出后是否打开输出目录。
    """
    paths = _package_paths(project_root)
    output = _resolve_io_path(output_path, paths, writable=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_dir, temp_dir_identity = _new_package_temp_dir("background-export")
    
    try:
        background_data_list = []

        for config in background_configs:
            # 准备要写入YAML的配置数据 (转换为字典，排除 FilePath 类型)
            bg_data = config.model_dump(
                exclude_none=True, 
                mode='json' # 确保 FilePath/HttpUrl 被转换为字符串
            )
            
            # 处理背景图片文件 (sprites)
            if config.sprite_prefix:
                sprite_prefix = _safe_package_name(
                    config.sprite_prefix, "background sprite_prefix"
                )
                # 复制图片文件
                sprite_source_dir = _package_storage_child(
                    paths,
                    paths.backgrounds,
                    sprite_prefix,
                    field="background sprite_prefix",
                )
                if sprite_source_dir.is_dir():
                    copy_directory_without_links(
                        sprite_source_dir,
                        temp_dir / 'sprites' / sprite_prefix,
                    )
                
                # 复制背景音乐文件 (bgm_list)
                bgm_source_dir = _package_storage_child(
                    paths,
                    paths.bgm,
                    sprite_prefix,
                    field="background sprite_prefix",
                )
                if bgm_source_dir.is_dir():
                    copy_directory_without_links(
                        bgm_source_dir,
                        temp_dir / 'bgm' / sprite_prefix,
                    )
                    
            _sanitize_background_package_paths(bg_data)
            
            background_data_list.append(bg_data)

        # 将配置数据写入临时文件
        atomic_write_text(
            temp_dir / "background.yaml",
            yaml.dump(background_data_list, allow_unicode=True, sort_keys=False),
        )
        
        # 打包成 .bg 文件
        with _atomic_package_output(output) as staging_output:
            with zipfile.ZipFile(staging_output, 'w', zipfile.ZIP_DEFLATED) as zf:
                write_directory_to_zip_without_links(zf, temp_dir)
        
        if open_folder:
            _open_export_folder(output)

        print(f"背景包成功导出到: {output}")

    finally:
        # 清理临时目录
        _cleanup_private_directory(temp_dir, temp_dir_identity)

def import_background(
    input_path: str,
    existing_configs: List[Background],
    *,
    project_root: str | os.PathLike | None = None,
    transaction_paths: list[_OwnedDirectory] | None = None,
) -> List[Background]:
    with _PACKAGE_IO_LOCK:
        return _import_background_unlocked(
            input_path,
            existing_configs,
            project_root=project_root,
            transaction_paths=transaction_paths,
        )


def _import_background_unlocked(
    input_path: str,
    existing_configs: List[Background],
    *,
    project_root: str | os.PathLike | None = None,
    transaction_paths: list[_OwnedDirectory] | None = None,
) -> List[Background]:
    """
    从 .bg 文件导入背景配置及其依赖文件，并将配置合并到现有列表中。
    检测名称和sprite_prefix冲突，自动添加后缀解决冲突。
    
    Args:
        input_path (str): 要导入的 .bg 文件路径。
        existing_configs (List[Background]): 当前已有的 Background 配置列表。
        
    Returns:
        List[Background]: 导入的 Background 对象列表。
    """
    paths = _package_paths(project_root)
    package_path = _resolve_io_path(input_path, paths)
    if not package_path.is_file():
        raise FileNotFoundError(f"文件未找到: {package_path}")

    temp_dir, temp_dir_identity = _new_package_temp_dir("background-import")
    
    imported_configs = []
    created_directories: list[_OwnedDirectory] = []
    committed = False

    try:
        # 解压 .bg 文件到临时目录
        _extract_package_zip(package_path, temp_dir)

        # 读取YAML配置文件
        yaml_data = yaml.safe_load(
            read_text_without_links(temp_dir / 'background.yaml')
        )

        if not yaml_data:
            raise ValueError("背景配置 YAML 文件为空或格式错误。")

        # 读取现有配置，用于检测冲突
        existing_names = {config.name for config in existing_configs}
        existing_sprite_prefixes = {config.sprite_prefix for config in existing_configs}
        existing_sprite_prefixes.update(
            _existing_storage_names(paths.backgrounds, paths.bgm)
        )
        
        # 记录本次导入中已使用的名称和sprite_prefix，避免内部冲突
        imported_names = set(existing_names)
        imported_sprite_prefixes = set(existing_sprite_prefixes)

        for bg_data in yaml_data:
            original_name = bg_data.get('name', '')
            original_sprite_prefix = _safe_package_name(
                bg_data.get('sprite_prefix', ''), "background sprite_prefix"
            )
            
            # 解决名称冲突
            new_name = _resolve_name_conflict(original_name, imported_names)
            bg_data['name'] = new_name
            imported_names.add(new_name)
            
            # 解决sprite_prefix冲突
            new_sprite_prefix = _resolve_sprite_prefix_conflict(original_sprite_prefix, imported_sprite_prefixes)
            bg_data['sprite_prefix'] = new_sprite_prefix
            imported_sprite_prefixes.add(new_sprite_prefix)
            
            # 如果名称或sprite_prefix被修改，打印提示信息
            if new_name != original_name or new_sprite_prefix != original_sprite_prefix:
                print(f"检测到背景冲突，已将 '{original_name}' ({original_sprite_prefix}) 重命名为 '{new_name}' ({new_sprite_prefix})")
            
            # 恢复背景图片文件（使用新的sprite_prefix）
            if new_sprite_prefix:
                # 恢复图片
                source_sprite_dir = temp_dir / 'sprites' / original_sprite_prefix
                dest_sprite_dir = _package_storage_child(
                    paths,
                    paths.backgrounds,
                    new_sprite_prefix,
                    field="background sprite_prefix",
                )
                if source_sprite_dir.is_dir():
                    _record_import_directory(
                        copy_directory_without_links(source_sprite_dir, dest_sprite_dir),
                        created_directories,
                    )

                # 恢复音乐文件
                source_bgm_dir = temp_dir / 'bgm' / original_sprite_prefix
                dest_bgm_dir = _package_storage_child(
                    paths,
                    paths.bgm,
                    new_sprite_prefix,
                    field="background sprite_prefix",
                )
                if source_bgm_dir.is_dir():
                    _record_import_directory(
                        copy_directory_without_links(source_bgm_dir, dest_bgm_dir),
                        created_directories,
                    )
            # 更新 sprites 中的路径
            if 'sprites' in bg_data:
                for sprite_entry in bg_data['sprites']:
                    # 路径是相对路径，需要重新构建新的绝对或相对路径
                    if 'path' in sprite_entry:
                        # 假设 path 存储的是文件名或相对于原始前缀的路径
                        filename = _safe_package_basename_or_legacy_absolute(
                            sprite_entry['path'], "background sprite path"
                        )
                        new_path = paths.backgrounds / new_sprite_prefix / filename
                        sprite_entry['path'] = _stored_path(new_path, paths)

            # 更新 bgm_list 中的路径
            if 'bgm_list' in bg_data:
                new_bgm_list = []
                for path in bg_data['bgm_list']:
                    filename = _safe_package_basename_or_legacy_absolute(path, "background bgm path")
                    new_path = paths.bgm / new_sprite_prefix / filename
                    new_bgm_list.append(_stored_path(new_path, paths))
                bg_data['bgm_list'] = new_bgm_list
                
            # 将更新后的数据创建为 Background 对象
            # 注意：这里需要一个从字典创建 Background 实例的方法，假设 Pydantic 的 Background() 可用
            imported_configs.append(Background.model_validate(bg_data))
        
        # 导入后，调用方需要将这些 imported_configs 合并到 ConfigManager 的配置中并保存。
        if transaction_paths is not None:
            transaction_paths.extend(created_directories)
        committed = True
        print(f"背景包成功从 {package_path} 导入。")
        return imported_configs

    finally:
        if not committed:
            _rollback_import_directories(created_directories)
        # 清理临时目录
        _cleanup_private_directory(temp_dir, temp_dir_identity)


def export_effect(
    effect_configs: list,
    output_path: str = 'output/effect.ef',
    open_folder: bool = True,
    *,
    project_root: str | os.PathLike | None = None,
):
    """Export effects as a .ef package file."""
    paths = _package_paths(project_root)
    output = _resolve_io_path(output_path, paths, writable=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_dir, temp_dir_identity = _new_package_temp_dir("effect-export")

    try:
        effect_data_list = []
        packaged_audio: list[tuple[Path, str]] = []
        used_audio_names: set[str] = set()
        for config in effect_configs:
            ef_data = config.model_dump(exclude_none=True, mode='json')
            _safe_package_name(ef_data.get("name", ""), "effect name")
            normalized_audio = []
            for audio_path in (config.audio_list or []):
                audio_file = _resolve_io_path(audio_path, paths)
                if not audio_file.is_file():
                    continue
                original_name = _safe_package_basename_or_legacy_absolute(
                    audio_path, "effect audio path"
                )
                archive_name = original_name
                counter = 1
                while portable_name_key(archive_name) in used_audio_names:
                    source_name = Path(original_name)
                    archive_name = safe_path_component_with_suffix(
                        source_name.stem,
                        f"_{counter}{source_name.suffix}",
                        field="effect audio filename",
                    )
                    counter += 1
                used_audio_names.add(portable_name_key(archive_name))
                normalized_audio.append(archive_name)
                packaged_audio.append((audio_file, archive_name))
            ef_data["audio_list"] = normalized_audio
            effect_data_list.append(ef_data)

        yaml_path = temp_dir / 'effect.yaml'
        atomic_write_text(
            yaml_path,
            yaml.dump(
                effect_data_list,
                allow_unicode=True,
                default_flow_style=False,
            ),
        )

        with _atomic_package_output(output) as staging_output:
            with zipfile.ZipFile(staging_output, 'w', zipfile.ZIP_DEFLATED) as zf:
                write_zip_files_without_links(
                    zf,
                    [
                        (yaml_path, "effect.yaml"),
                        *[
                            (audio_file, f"audio/{archive_name}")
                            for audio_file, archive_name in packaged_audio
                        ],
                    ],
                )

        if open_folder:
            _open_export_folder(output)

        print(f"特效导出完成：{output}")
    finally:
        _cleanup_private_directory(temp_dir, temp_dir_identity)


def import_effect(
    input_path: str,
    existing_configs: list,
    *,
    effect_upload_dir: str | os.PathLike | None = None,
    project_root: str | os.PathLike | None = None,
    transaction_paths: list[_OwnedDirectory] | None = None,
) -> list:
    with _PACKAGE_IO_LOCK:
        return _import_effect_unlocked(
            input_path,
            existing_configs,
            effect_upload_dir=effect_upload_dir,
            project_root=project_root,
            transaction_paths=transaction_paths,
        )


def _import_effect_unlocked(
    input_path: str,
    existing_configs: list,
    *,
    effect_upload_dir: str | os.PathLike | None = None,
    project_root: str | os.PathLike | None = None,
    transaction_paths: list[_OwnedDirectory] | None = None,
) -> list:
    """Import effects from a .ef package file."""
    paths = _package_paths(project_root)
    package_path = _resolve_io_path(input_path, paths)
    if not package_path.is_file():
        raise FileNotFoundError(f"文件未找到: {package_path}")

    temp_dir, temp_dir_identity = _new_package_temp_dir("effect-import")

    imported_configs = []
    created_directories: list[_OwnedDirectory] = []
    committed = False

    try:
        _extract_package_zip(package_path, temp_dir)

        yaml_path = temp_dir / 'effect.yaml'
        yaml_data = yaml.safe_load(read_text_without_links(yaml_path))

        if not yaml_data:
            raise ValueError("特效配置 YAML 文件为空或格式错误。")
        if not isinstance(yaml_data, list):
            yaml_data = [yaml_data]

        from config.schema import Effect as EffectModel

        audio_source_dir = temp_dir / 'audio'

        managed_effect_root = (
            _resolve_io_path(effect_upload_dir, paths, writable=True)
            if effect_upload_dir is not None
            else paths.effects
        )
        if paths.project_root is not None:
            expected_effect_root = paths.effects
            if managed_effect_root != expected_effect_root:
                raise PermissionError("effect upload directory must be project data/effects")
        managed_effect_root.mkdir(parents=True, exist_ok=True)
        managed_effect_root = require_directory_without_links(
            managed_effect_root,
            field="effect storage directory",
        )
        (
            _managed_effect_root,
            managed_effect_root_identity,
            managed_effect_entries,
        ) = snapshot_directory_entries_without_links(
            managed_effect_root,
            field="effect storage directory",
        )

        existing_names = {portable_name_key(str(e.name)) for e in existing_configs}
        existing_names.update(
            portable_name_key(child.name)
            for child, _metadata in managed_effect_entries
        )

        for item in yaml_data:
            if not isinstance(item, dict):
                continue
            original_name = _safe_package_name(item.get('name', ''), "effect name")
            if not original_name:
                raise ValueError("effect name must not be empty")
            name = original_name
            counter = 1
            while portable_name_key(name) in existing_names:
                name = safe_path_component_with_suffix(
                    original_name,
                    f"_{counter}",
                    field="effect name",
                )
                counter += 1
            item['name'] = name
            existing_names.add(portable_name_key(name))

            # Create managed directory and copy audio files
            ef_dir = managed_child_path(
                managed_effect_root,
                name,
                field="effect name",
            )
            _reserve_import_directory(
                ef_dir,
                created_directories,
                expected_parent_identity=managed_effect_root_identity,
            )

            new_audio_list = []
            old_audio_list = item.get('audio_list') or []
            for audio_path in old_audio_list:
                audio_filename = _safe_package_basename_or_legacy_absolute(
                    audio_path, "effect audio path"
                )
                src = audio_source_dir / audio_filename
                if src.is_file():
                    dest = copy_file_exclusive(
                        src,
                        ef_dir,
                        audio_filename,
                        field="effect audio filename",
                    )
                    new_audio_list.append(_stored_path(dest, paths))

            item['audio_list'] = new_audio_list

            effect = EffectModel.model_validate(item)
            imported_configs.append(effect)

        if transaction_paths is not None:
            transaction_paths.extend(created_directories)
        committed = True
        print(f"特效包成功从 {package_path} 导入。")
        return imported_configs

    finally:
        if not committed:
            _rollback_import_directories(created_directories)
        _cleanup_private_directory(temp_dir, temp_dir_identity)
