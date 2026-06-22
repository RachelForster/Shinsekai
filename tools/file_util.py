import os
import shutil
import zipfile
import yaml
import json
import re
from pathlib import Path, PurePosixPath
from config.character_config import CharacterConfig
from config.schema import Background
from config.config_manager import ConfigManager
from typing import List
import platform
import subprocess

# 定义项目的基础数据路径
BASE_DATA_PATH = Path('./data')
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


def _open_export_folder(output_path: str | os.PathLike) -> None:
    folder_path = Path(output_path).parent.resolve()

    try:
        system = platform.system()
        if system == 'Windows':
            os.startfile(folder_path)  # type: ignore[attr-defined]
        elif system == 'Darwin':  # macOS
            subprocess.Popen(['open', str(folder_path)])
        elif system == 'Linux':
            subprocess.Popen(['xdg-open', str(folder_path)])
    except Exception as e:
        print(f"Failed to open export folder {folder_path}: {e}")


def _safe_package_relpath(path: str | os.PathLike | None, field_name: str) -> Path:
    """Interpret package paths written on Windows or POSIX as safe relative paths."""
    raw = str(path or "").replace("\\", "/").strip()
    while raw.startswith("./"):
        raw = raw[2:]
    if not raw:
        raise ValueError(f"{field_name} must not be empty")
    if "\x00" in raw or raw.startswith("/") or _WINDOWS_DRIVE_RE.match(raw):
        raise ValueError(f"{field_name} must be a relative package path: {path!r}")
    if any(part in ("", ".", "..") for part in raw.split("/")):
        raise ValueError(f"{field_name} contains an unsafe path component: {path!r}")
    rel = PurePosixPath(raw)
    return Path(*rel.parts)


def _safe_package_basename(path: str | os.PathLike | None, field_name: str) -> str:
    return _safe_package_relpath(path, field_name).name


def _safe_package_basename_or_legacy_absolute(
    path: str | os.PathLike | None, field_name: str
) -> str:
    """Return a safe package filename, accepting old host-absolute YAML paths."""
    raw = str(path or "").replace("\\", "/").strip()
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
    raw = str(value or "").replace("\\", "/").strip()
    if not raw:
        return ""
    if (
        "\x00" in raw
        or "/" in raw
        or raw in (".", "..")
        or _WINDOWS_DRIVE_RE.match(raw)
    ):
        raise ValueError(f"{field_name} must be a plain package name: {value!r}")
    return raw


def _safe_extract_zip(zf: zipfile.ZipFile, target_dir: Path) -> None:
    for info in zf.infolist():
        member = str(info.filename or "").replace("\\", "/").rstrip("/")
        if member:
            _safe_package_relpath(member, "zip member")
    zf.extractall(target_dir)


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

def export_character(character_configs: list[CharacterConfig], output_path: str, open_folder: bool = True):
    """
    将人物配置及其依赖文件打包成一个 .cha 文件。
    
    Args:
        character_configs (list[CharacterConfig]): 要导出的 CharacterConfig 对象列表。
        output_path (str): 导出的 .cha 文件路径。
        open_folder (bool): 导出后是否打开输出目录。
    """
    temp_dir = Path(f'./temp_export_{os.getpid()}')
    temp_dir.mkdir(exist_ok=True)
    
    try:
        manifest_data = {'original_paths': {}}
        character_data_list = []

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
                if abs_path and os.path.exists(abs_path):
                    file_path = Path(abs_path)
                    new_relative_path = Path('models') / file_path.name

                    # 将模型的原始绝对路径记录到清单中
                    manifest_data['original_paths'][file_path.name] = str(file_path)

                    # 将模型文件复制到临时目录
                    destination_path = temp_dir / new_relative_path
                    destination_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file_path, destination_path)

                    # 更新YAML数据中的路径为相对路径
                    char_data[key] = str(new_relative_path)
                else:
                    char_data[key] = None

            # 处理立绘文件
            if config.sprite_prefix:
                sprite_source_dir = SPRITE_DIR / config.sprite_prefix
                if sprite_source_dir.is_dir():
                    shutil.copytree(sprite_source_dir, temp_dir / 'sprites' / config.sprite_prefix, dirs_exist_ok=True)

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
                voice_src_dir = SPEECH_DIR / config.sprite_prefix
                if voice_src_dir.is_dir():
                    shutil.copytree(voice_src_dir, temp_dir / 'speech' / config.sprite_prefix, dirs_exist_ok=True)

            character_data_list.append(char_data)

        # 将配置数据和清单写入临时文件
        with open(temp_dir / 'character.yaml', 'w', encoding='utf-8') as f:
            yaml.dump(character_data_list, f, allow_unicode=True, sort_keys=False)
        
        with open(temp_dir / 'manifest.json', 'w', encoding='utf-8') as f:
            json.dump(manifest_data, f, indent=4)
            
        # 打包成 .cha 文件
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_path in temp_dir.rglob('*'):
                if file_path.is_file():
                    # 计算文件在zip中的相对路径
                    arcname = file_path.relative_to(temp_dir)
                    zf.write(file_path, arcname)
        
        if open_folder:
            _open_export_folder(output_path)

        print(f"人物成功导出到: {output_path}")

    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir)

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
    if sprite_prefix not in existing_prefixes:
        return sprite_prefix
    
    counter = 1
    new_prefix = f"{sprite_prefix}{counter}"
    while new_prefix in existing_prefixes:
        counter += 1
        new_prefix = f"{sprite_prefix}{counter}"
    
    return new_prefix

def import_character(input_path: str) -> list[CharacterConfig]:
    """
    从 .cha 文件导入人物配置及其依赖文件，并将配置追加入 characters.yaml。
    检测名称和sprite_prefix冲突，自动添加后缀解决冲突。
    
    Args:
        input_path (str): 要导入的 .cha 文件路径。
        
    Returns:
        list[CharacterConfig]: 导入的 CharacterConfig 对象列表。
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"文件未找到: {input_path}")
        
    temp_dir = Path(f'./temp_import_{os.getpid()}')
    temp_dir.mkdir(exist_ok=True)
    
    imported_configs = []

    try:
        # 解压 .cha 文件到临时目录
        with zipfile.ZipFile(input_path, 'r') as zf:
            _safe_extract_zip(zf, temp_dir)

        # 读取YAML配置文件
        with open(temp_dir / 'character.yaml', 'r', encoding='utf-8') as f:
            yaml_data = yaml.safe_load(f)

        if not yaml_data:
            raise ValueError("YAML配置文件为空或格式错误。")

        # 读取现有配置，用于检测冲突
        existing_names = set()
        existing_sprite_prefixes = set()
        
        if CHARACTERS_CONFIG_PATH.exists():
            with open(CHARACTERS_CONFIG_PATH, 'r', encoding='utf-8') as f:
                existing_configs = yaml.safe_load(f) or []
                for config in existing_configs:
                    existing_names.add(config.get('name', ''))
                    existing_sprite_prefixes.add(config.get('sprite_prefix', ''))
        
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
            dest_sprite_dir = SPRITE_DIR / new_sprite_prefix
            dest_speech_dir = SPEECH_DIR / new_sprite_prefix

            # 恢复立绘文件（使用新的sprite_prefix）
            if new_sprite_prefix:
                source_sprite_dir = temp_dir / 'sprites' / original_sprite_prefix
                if source_sprite_dir.is_dir():
                    shutil.copytree(source_sprite_dir, dest_sprite_dir, dirs_exist_ok=True)

            # 修复 sprite path：指向导入机器上的实际路径；无 prefix 时至少去掉宿主机路径。
            for s in sprites:
                if isinstance(s, dict):
                    filename = _safe_package_basename_or_legacy_absolute(
                        s.get('path', ''), "sprite path"
                    )
                    if new_sprite_prefix:
                        new_path = dest_sprite_dir / filename
                        try:
                            s['path'] = str(new_path.relative_to(Path.cwd()))
                        except ValueError:
                            s['path'] = new_path.as_posix()
                    else:
                        s['path'] = filename

            if new_sprite_prefix:
                # 恢复语音文件（使用新的sprite_prefix）
                source_speech_dir = temp_dir / 'speech' / original_sprite_prefix
                if source_speech_dir.is_dir():
                    shutil.copytree(source_speech_dir, dest_speech_dir, dirs_exist_ok=True)

                # 恢复语音文件
                source_speech_dir = temp_dir / 'speech' / original_sprite_prefix
                if source_speech_dir.is_dir():
                    shutil.copytree(source_speech_dir, SPEECH_DIR / new_sprite_prefix, dirs_exist_ok=True)

            # 修复 voice_path：指向 SPEECH_DIR；无 prefix 时至少去掉宿主机路径。
            for s in sprites:
                if isinstance(s, dict) and s.get('voice_path'):
                    filename = _safe_package_basename_or_legacy_absolute(
                        s['voice_path'], "voice_path"
                    )
                    if new_sprite_prefix:
                        new_vp = dest_speech_dir / filename
                        try:
                            s['voice_path'] = str(new_vp.relative_to(Path.cwd()))
                        except ValueError:
                            s['voice_path'] = new_vp.as_posix()
                    else:
                        s['voice_path'] = filename
            
            # 恢复模型文件并更新路径
            model_paths = {
                'gpt_model_path': char_data.get('gpt_model_path'),
                'sovits_model_path': char_data.get('sovits_model_path'),
                'refer_audio_path': char_data.get('refer_audio_path')
            }
            
            for key, path in model_paths.items():
                if path:  # 确保路径不为空
                    source_model_path = temp_dir / _safe_package_relpath(path, key)
                    dest_model_dir = MODEL_DIR / new_sprite_prefix
                    dest_model_dir.mkdir(parents=True, exist_ok=True)
                    dest_model_path = dest_model_dir / _safe_package_basename(path, key)
                    if source_model_path.exists():  # 确保源文件存在
                        shutil.copy2(source_model_path, dest_model_path)
                        char_data[key] = dest_model_path.as_posix()  # 更新为相对路径
                    else:
                        char_data[key] = None

            # 将更新后的数据创建为 CharacterConfig 对象
            imported_configs.append(CharacterConfig.parse_dic(char_data=char_data))
        
        # 将配置追加到 characters.yaml
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        
        existing_data = []
        if CHARACTERS_CONFIG_PATH.exists():
            with open(CHARACTERS_CONFIG_PATH, 'r', encoding='utf-8') as f:
                existing_data = yaml.safe_load(f) or []

        # 将导入的配置转换为字典格式并追加
        new_data_list = [config.__dict__ for config in imported_configs]
        existing_data.extend(new_data_list)
        
        with open(CHARACTERS_CONFIG_PATH, 'w', encoding='utf-8') as f:
            yaml.dump(existing_data, f, allow_unicode=True, sort_keys=False)

        print(f"人物成功从 {input_path} 导入，并已将配置追加到 {CHARACTERS_CONFIG_PATH}。")
        return imported_configs

    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir)

# ---------------------------------------------


def export_background(
    background_configs: List[Background],
    output_path: str = './output/background.bg',
    open_folder: bool = True,
):
    """
    将背景配置及其依赖文件（图片和音乐）打包成一个 .bg 文件。
    
    Args:
        background_configs (List[Background]): 要导出的 Background 对象列表。
        output_path (str): 导出的 .bg 文件路径 (默认路径为 ./output/background.bg)。
        open_folder (bool): 导出后是否打开输出目录。
    """
    Path('./output').mkdir(exist_ok=True) # 确保输出目录存在
    temp_dir = Path(f'./temp_export_bg_{os.getpid()}')
    temp_dir.mkdir(exist_ok=True)
    
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
                # 复制图片文件
                sprite_source_dir = Path(BACKGROUND_UPLOAD_DIR) / config.sprite_prefix
                if sprite_source_dir.is_dir():
                    shutil.copytree(sprite_source_dir, temp_dir / 'sprites' / config.sprite_prefix, dirs_exist_ok=True)
                
                # 复制背景音乐文件 (bgm_list)
                bgm_source_dir = Path(BGM_UPLOAD_DIR) / config.sprite_prefix
                if bgm_source_dir.is_dir():
                    shutil.copytree(bgm_source_dir, temp_dir / 'bgm' / config.sprite_prefix, dirs_exist_ok=True)
                    
            _sanitize_background_package_paths(bg_data)
            
            background_data_list.append(bg_data)

        # 将配置数据写入临时文件
        with open(temp_dir / 'background.yaml', 'w', encoding='utf-8') as f:
            yaml.dump(background_data_list, f, allow_unicode=True, sort_keys=False)
        
        # 打包成 .bg 文件
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_path in temp_dir.rglob('*'):
                if file_path.is_file():
                    # 计算文件在zip中的相对路径
                    arcname = file_path.relative_to(temp_dir)
                    zf.write(file_path, arcname)
        
        if open_folder:
            _open_export_folder(output_path)

        print(f"背景包成功导出到: {output_path}")

    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir)

def import_background(input_path: str, existing_configs: List[Background]) -> List[Background]:
    """
    从 .bg 文件导入背景配置及其依赖文件，并将配置合并到现有列表中。
    检测名称和sprite_prefix冲突，自动添加后缀解决冲突。
    
    Args:
        input_path (str): 要导入的 .bg 文件路径。
        existing_configs (List[Background]): 当前已有的 Background 配置列表。
        
    Returns:
        List[Background]: 导入的 Background 对象列表。
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"文件未找到: {input_path}")
        
    temp_dir = Path(f'./temp_import_bg_{os.getpid()}')
    temp_dir.mkdir(exist_ok=True)
    
    imported_configs = []

    try:
        # 解压 .bg 文件到临时目录
        with zipfile.ZipFile(input_path, 'r') as zf:
            _safe_extract_zip(zf, temp_dir)

        # 读取YAML配置文件
        with open(temp_dir / 'background.yaml', 'r', encoding='utf-8') as f:
            yaml_data = yaml.safe_load(f)

        if not yaml_data:
            raise ValueError("背景配置 YAML 文件为空或格式错误。")

        # 读取现有配置，用于检测冲突
        existing_names = {config.name for config in existing_configs}
        existing_sprite_prefixes = {config.sprite_prefix for config in existing_configs}
        
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
                dest_sprite_dir = Path(BACKGROUND_UPLOAD_DIR) / new_sprite_prefix
                if source_sprite_dir.is_dir():
                    shutil.copytree(source_sprite_dir, dest_sprite_dir, dirs_exist_ok=True)

                # 恢复音乐文件
                source_bgm_dir = temp_dir / 'bgm' / original_sprite_prefix
                dest_bgm_dir = Path(BGM_UPLOAD_DIR) / new_sprite_prefix
                if source_bgm_dir.is_dir():
                    shutil.copytree(source_bgm_dir, dest_bgm_dir, dirs_exist_ok=True)
            # 更新 sprites 中的路径
            if 'sprites' in bg_data:
                for sprite_entry in bg_data['sprites']:
                    # 路径是相对路径，需要重新构建新的绝对或相对路径
                    if 'path' in sprite_entry:
                        # 假设 path 存储的是文件名或相对于原始前缀的路径
                        filename = _safe_package_basename_or_legacy_absolute(
                            sprite_entry['path'], "background sprite path"
                        )
                        new_path = Path(BACKGROUND_UPLOAD_DIR) / new_sprite_prefix / filename
                        sprite_entry['path'] = new_path.as_posix()

            # 更新 bgm_list 中的路径
            if 'bgm_list' in bg_data:
                new_bgm_list = []
                for path in bg_data['bgm_list']:
                    filename = _safe_package_basename_or_legacy_absolute(path, "background bgm path")
                    new_path = Path(BGM_UPLOAD_DIR) / new_sprite_prefix / filename
                    new_bgm_list.append(new_path.as_posix())
                bg_data['bgm_list'] = new_bgm_list
                
            # 将更新后的数据创建为 Background 对象
            # 注意：这里需要一个从字典创建 Background 实例的方法，假设 Pydantic 的 Background() 可用
            imported_configs.append(Background.model_validate(bg_data))
        
        # 导入后，调用方需要将这些 imported_configs 合并到 ConfigManager 的配置中并保存。
        print(f"背景包成功从 {input_path} 导入。")
        return imported_configs

    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir)


def export_effect(
    effect_configs: list,
    output_path: str = './output/effect.ef',
    open_folder: bool = True,
):
    """Export effects as a .ef package file."""
    Path('./output').mkdir(exist_ok=True)
    temp_dir = Path(f'./temp_export_ef_{os.getpid()}')
    temp_dir.mkdir(exist_ok=True)

    try:
        effect_data_list = []
        for config in effect_configs:
            ef_data = config.model_dump(exclude_none=True, mode='json')
            effect_data_list.append(ef_data)

        yaml_path = temp_dir / 'effect.yaml'
        with open(yaml_path, 'w', encoding='utf-8') as f:
            yaml.dump(effect_data_list, f, allow_unicode=True, default_flow_style=False)

        output = Path(output_path)
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(yaml_path, 'effect.yaml')
            for config in effect_configs:
                for audio_path in (config.audio_list or []):
                    audio_file = Path(audio_path)
                    if audio_file.exists():
                        arcname = f"audio/{audio_file.name}"
                        zf.write(audio_file, arcname)

        if open_folder:
            os.startfile(output.parent)

        print(f"特效导出完成：{output}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def import_effect(input_path: str, existing_configs: list) -> list:
    """Import effects from a .ef package file."""
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"文件未找到: {input_path}")

    temp_dir = Path(f'./temp_import_ef_{os.getpid()}')
    temp_dir.mkdir(exist_ok=True)

    imported_configs = []

    try:
        with zipfile.ZipFile(input_path, 'r') as zf:
            _safe_extract_zip(zf, temp_dir)

        yaml_path = temp_dir / 'effect.yaml'
        with open(yaml_path, 'r', encoding='utf-8') as f:
            yaml_data = yaml.safe_load(f)

        if not yaml_data:
            raise ValueError("特效配置 YAML 文件为空或格式错误。")
        if not isinstance(yaml_data, list):
            yaml_data = [yaml_data]

        from config.schema import Effect as EffectModel

        existing_names = {e.name.lower() for e in existing_configs}

        audio_source_dir = temp_dir / 'audio'

        for item in yaml_data:
            if not isinstance(item, dict):
                continue
            original_name = _safe_package_name(item.get('name', ''), "effect name")
            if not original_name:
                raise ValueError("effect name must not be empty")
            name = original_name
            counter = 1
            while name.lower() in existing_names:
                name = f"{original_name}_{counter}"
                counter += 1
            item['name'] = name
            existing_names.add(name.lower())

            # Create managed directory and copy audio files
            ef_dir = EFFECT_UPLOAD_DIR / name
            ef_dir.mkdir(parents=True, exist_ok=True)

            new_audio_list = []
            old_audio_list = item.get('audio_list') or []
            for audio_path in old_audio_list:
                audio_filename = Path(str(audio_path)).name
                src = audio_source_dir / audio_filename
                if src.exists():
                    dest = ef_dir / audio_filename
                    counter2 = 1
                    while dest.exists():
                        stem = Path(audio_filename).stem
                        suffix = Path(audio_filename).suffix
                        dest = ef_dir / f"{stem}_{counter2}{suffix}"
                        counter2 += 1
                    shutil.copy2(src, dest)
                    new_audio_list.append(dest.as_posix())
                else:
                    # File not in archive, keep original path
                    new_audio_list.append(str(audio_path))

            item['audio_list'] = new_audio_list

            effect = EffectModel.model_validate(item)
            imported_configs.append(effect)

        print(f"特效包成功从 {input_path} 导入。")
        return imported_configs

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
