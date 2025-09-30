import os
import shutil
import zipfile
import yaml
import json
from pathlib import Path
from config.character_config import CharacterConfig
import platform
import subprocess

# 定义项目的基础数据路径
BASE_DATA_PATH = Path('./data')
SPRITE_DIR = BASE_DATA_PATH / 'sprite'
SPEECH_DIR = BASE_DATA_PATH / 'speech'
MODEL_DIR = BASE_DATA_PATH / 'models'
CONFIG_DIR = BASE_DATA_PATH / 'config'
CHARACTERS_CONFIG_PATH = CONFIG_DIR / 'characters.yaml'

def export_character(character_configs: list[CharacterConfig], output_path: str):
    """
    将人物配置及其依赖文件打包成一个 .cha 文件。
    
    Args:
        character_configs (list[CharacterConfig]): 要导出的 CharacterConfig 对象列表。
        output_path (str): 导出的 .cha 文件路径。
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
                'emotion_tags':config.emotion_tags,
                'character_setting': config.character_setting
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

            # 处理立绘和语音文件
            if config.sprite_prefix:
                sprite_source_dir = SPRITE_DIR / config.sprite_prefix
                if sprite_source_dir.is_dir():
                    shutil.copytree(sprite_source_dir, temp_dir / 'sprites' / config.sprite_prefix, dirs_exist_ok=True)
                
                # 复制语音文件
                voice_source_dir = SPEECH_DIR / config.sprite_prefix
                if voice_source_dir.is_dir():
                    shutil.copytree(voice_source_dir, temp_dir / 'speech' / config.sprite_prefix, dirs_exist_ok=True)

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
        
        folder_path = Path(output_path).parent.resolve()
        
        system = platform.system()
        if system == 'Windows':
            os.startfile(folder_path)
        elif system == 'Darwin':  # macOS
            subprocess.Popen(['open', folder_path])
        elif system == 'Linux':
            subprocess.Popen(['xdg-open', folder_path])

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
            zf.extractall(temp_dir)

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
            original_sprite_prefix = char_data.get('sprite_prefix', '')
            
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
            
            # 恢复立绘文件（使用新的sprite_prefix）
            if new_sprite_prefix:
                source_sprite_dir = temp_dir / 'sprites' / original_sprite_prefix
                dest_sprite_dir = SPRITE_DIR / new_sprite_prefix
                if source_sprite_dir.is_dir():
                    shutil.copytree(source_sprite_dir, dest_sprite_dir, dirs_exist_ok=True)

                # 恢复语音文件（使用新的sprite_prefix）
                source_speech_dir = temp_dir / 'speech' / original_sprite_prefix
                dest_speech_dir = SPEECH_DIR / new_sprite_prefix
                if source_speech_dir.is_dir():
                    shutil.copytree(source_speech_dir, dest_speech_dir, dirs_exist_ok=True)
            
            # 恢复模型文件并更新路径
            model_paths = {
                'gpt_model_path': char_data.get('gpt_model_path'),
                'sovits_model_path': char_data.get('sovits_model_path'),
                'refer_audio_path': char_data.get('refer_audio_path')
            }
            
            for key, path in model_paths.items():
                if path:  # 确保路径不为空
                    source_model_path = temp_dir / path
                    dest_model_dir = MODEL_DIR / new_sprite_prefix
                    dest_model_dir.mkdir(parents=True, exist_ok=True)
                    dest_model_path = dest_model_dir / Path(path).name
                    if source_model_path.exists():  # 确保源文件存在
                        shutil.copy2(source_model_path, dest_model_path)
                        char_data[key] = str(dest_model_path.resolve())  # 更新为新的绝对路径
                    else:
                        char_data[key] = None

            # 将更新后的数据创建为 CharacterConfig 对象
            imported_configs.append(CharacterConfig.parse_dic(char_data=char_data))
            print(f"==========import{char_data.get("character_setting")}")
        
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