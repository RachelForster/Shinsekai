import os
import shutil
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional, Union
from config.schema import Character, Sprite
from config.config_manager import ConfigManager 
import gradio as gr 
import yaml 

UPLOAD_DIR = "data/sprite"
VOICE_DIR = "data/voices"
MODEL_DIR = "data/models"
CHARACTER_CONFIG_PATH = ConfigManager._CHARACTERS_CONFIG_PATH 


class CharacterManager:
    """
    负责角色配置、立绘、语音和 LLM 设定的管理。
    内部使用 ConfigManager 来持久化数据。
    """
    
    # 私有属性，用于缓存 LLM Manager 实例
    _llm_manager: Optional[Any] = None 
    _config_manager: ConfigManager
    
    def __init__(self):
        """初始化 CharacterManager，获取 ConfigManager 单例。"""
        self._config_manager = ConfigManager()

    def _get_characters(self) -> List[Character]:
        """获取当前的 Character 列表"""
        try:
            return self._config_manager.config.characters
        except Exception:
            # 如果配置未加载或失败，返回空列表
            return []
    def get_character_name_list(self):
        return [c.name for c in self._config_manager.config.characters]

    def _save_characters_config(self) -> None:
        """保存角色配置的便捷方法"""
        self._config_manager.save_characters_config()

    def generate_character_setting(self, name: str, setting: str) -> Tuple[str, str]:
        """
        使用 LLM 为角色生成详细设定。
        
        Args:
            name: 角色名称。
            setting: 用户的补充信息/初步设定。
            
        Returns:
            Tuple[str, str]: (操作结果消息, 生成或当前的设定内容)
        """
        if not name:
            return "请选择或输入要生成的角色的名字！", setting
        
        # 查找角色
        character = self._config_manager.get_character_by_name(name)
        
        # 如果角色不存在，则先创建一个默认角色
        if character is None:
            self.add_character(name=name, color='', sprite_prefix='', gpt_model_path='', 
                                            sovits_model_path='', refer_audio_path='', prompt_text='', prompt_lang='', character_setting=setting)
            # 重新获取角色实例
            character = self._config_manager.get_character_by_name(name)
            if character is None:
                return f"创建角色 {name} 失败。", setting

        setting = "无" if not setting else setting
        
        # 构造 Prompt 模板
        template = f"""
        你需要帮助用户写出{name}的角色设定，包括{name}的背景信息，性格特点，和语言习惯。输出plain text格式，不要使用markdown格式。
        将{name}的背景信息，性格特点，和语言习惯分段写，并且同一段内标号，不一定是3点，有可能比3点多。
        输出格式示例：
        {name}的背景信息：
        1.姓名和出处：
        2.外表：
        3.背景：
        4.经历：

        {name}的性格特点：
        1.
        2.
        3.

        {name}的语言习惯：
        1.
        2.
        """
        
        try:
            llm_provider, llm_model, llm_base_url, api_key = self._config_manager.get_llm_api_config()
            
            if not llm_provider or not api_key or not llm_model:
                return "LLM 配置不完整，请先设定大语言模型供应商、模型和 API Key。", setting
                
            if self._llm_manager is None:
                # 假设 LLMAdapterFactory 和 LLMManager 已定义
                from llm.llm_manager import LLMAdapterFactory, LLMManager 
                llm_adapter = LLMAdapterFactory.create_adapter(llm_provider=llm_provider, api_key=api_key, base_url=llm_base_url, model=llm_model)
                self._llm_manager = LLMManager(adapter=llm_adapter, user_template=template)
                
            self._llm_manager.set_user_template(template)
            
            # 假设 chat 方法返回生成的文本
            new_setting_text = self._llm_manager.chat(f"补充信息：{setting},请输出结果：", stream=False, response_format={"type": "text"})
            
            # 更新 Character 实例并保存
            character.character_setting = new_setting_text
            self._config_manager.save_characters_config() 
            
            return "输出成功", character.character_setting
            
        except ImportError:
            return "输出失败: LLM 模块依赖未找到 (LLMAdapterFactory, LLMManager)", setting
        except Exception as e:
            return f"输出失败:{e}", setting


    def save_characters_to_file(self) -> str:
        """
        保存所有角色配置到文件。
        
        Returns:
            str: 操作结果消息。
        """
        try:
            self._save_characters_config()
            return f"人物设定已保存到 {CHARACTER_CONFIG_PATH}！"
        except Exception as e:
            return f"保存失败: {str(e)}"


    def add_character(self, name: str, color: str, sprite_prefix: str, gpt_model_path: str, 
                     sovits_model_path: str, refer_audio_path: str, prompt_text: str, 
                     prompt_lang: str, character_setting: str) -> Tuple[str, List[str]]:
        """
        添加或更新角色配置。
        
        Returns:
            Tuple[str, List[str]]: (操作结果消息, 当前所有角色名称列表)
        """
        current_names = [c.name for c in self._get_characters()]
        if not name:
            return "名称不能为空！", current_names
            
        characters = self._config_manager.config.characters 
        existing_character: Optional[Character] = self._config_manager.get_character_by_name(name)
        
        if existing_character is None:
            # 创建新的 Character 实例
            new_character = Character(
                name=name,
                color=color,
                sprite_prefix=sprite_prefix,
                gpt_model_path=gpt_model_path,
                sovits_model_path=sovits_model_path,
                refer_audio_path=refer_audio_path,
                prompt_text=prompt_text,
                prompt_lang=prompt_lang,
                sprites=[],
                sprite_scale=1.0,
                emotion_tags="",
                character_setting=character_setting,
            )    
            characters.append(new_character)
            self._save_characters_config()
            return "人物已添加！", [c.name for c in characters]
        else:
            # 更新现有 Character 实例的属性
            existing_character.name = name
            existing_character.color = color
            existing_character.sprite_prefix = sprite_prefix
            existing_character.gpt_model_path = gpt_model_path
            existing_character.sovits_model_path = sovits_model_path
            existing_character.prompt_text = prompt_text
            existing_character.prompt_lang = prompt_lang
            existing_character.refer_audio_path = refer_audio_path
            existing_character.character_setting = character_setting

            self._save_characters_config()
            return "人物已更新！", [c.name for c in characters]


    def delete_character(self, name: str) -> Tuple[str, List[str]]:
        """
        删除角色及其相关文件。
        
        Returns:
            Tuple[str, List[str]]: (操作结果消息, 当前所有角色名称列表)
        """
        characters = self._config_manager.config.characters
        current_names = [c.name for c in characters]
        
        if not name or name == "新角色":
            return "请选择要删除的角色！", current_names
        
        character_to_delete: Optional[Character] = self._config_manager.get_character_by_name(name)
        
        if character_to_delete is None:
            return f"找不到角色: {name}", current_names
        
        # 移除角色
        try:
            characters.remove(character_to_delete)
        except ValueError:
            return f"找不到角色: {name}", current_names
            
        self._save_characters_config()
        new_names = [c.name for c in characters]

        sprite_prefix = character_to_delete.sprite_prefix
        if not sprite_prefix:
            return "已删除角色", new_names
        
        # 删除相关目录
        for base_dir in [UPLOAD_DIR, VOICE_DIR, MODEL_DIR]:
            char_dir = os.path.join(base_dir, sprite_prefix)
            if os.path.exists(char_dir):
                shutil.rmtree(char_dir)
        
        return f"角色 {name} 已删除！", new_names


    def update_character_options(self):
        """
        返回用于 Gradio CheckboxGroup 的选项列表。
        
        Returns:
            gr.CheckboxGroup: Gradio 组件的配置（假设）或选项列表。
        """
        try:
            import gradio as gr 
            choices = [c.name for c in self._get_characters()]
            return gr.CheckboxGroup(choices=choices)
        except ImportError:
            return [c.name for c in self._get_characters()]


    def upload_sprites(self, character_name: str, sprite_files: List[Any], emotion_tags: str) -> Tuple[str, List[str], str]:
        """
        上传立绘文件并更新角色的立绘列表和情绪标签。

        Returns:
            Tuple[str, List[str], str]: (操作结果消息, 所有立绘路径列表, 更新后的情绪标签文本)
        """
        if not character_name:
            return "请先选择或创建角色！", [], ''
        
        if not sprite_files:
            return "请选择要上传的图片！", [], ''
        
        character: Optional[Character] = self._config_manager.get_character_by_name(character_name)
        if not character:
            return f"找不到角色: {character_name}", [], ''
        
        char_dir = os.path.join(UPLOAD_DIR, character.sprite_prefix)
        Path(char_dir).mkdir(parents=True, exist_ok=True)
        
        if character.sprites is None:
            character.sprites = []

        num_existing_sprites = len(character.sprites)
        emotion_tags_to_add = ''
        
        for i, file in enumerate(sprite_files):
            filename = os.path.basename(file.name)
            dest_path = os.path.join(char_dir, filename)
            shutil.copyfile(file.name, dest_path)
            
            new_sprite_data = {"path": dest_path}
            character.sprites.append(new_sprite_data)
            
            emotion_tags_to_add += f'立绘 {num_existing_sprites + i + 1}：\n'
            
        current_emotion_tags = character.emotion_tags if character.emotion_tags else ""
        character.emotion_tags = current_emotion_tags + emotion_tags_to_add

        self._config_manager.save_characters_config()

        all_sprite_paths = [s.path if isinstance(s, Sprite) else s.get('path', '') for s in character.sprites]
        return f"成功为 {character_name} 上传 {len(sprite_files)} 张立绘！", all_sprite_paths, character.emotion_tags


    def delete_all_sprites(self, character_name: str) -> Tuple[str, List[str], str]:
        """
        删除角色的所有立绘及其语音文件。
        
        Returns:
            Tuple[str, List[str], str]: (操作结果消息, 空立绘路径列表, 空情绪标签文本)
        """
        if not character_name:
            return "请先选择角色！", [], ""
        
        character: Optional[Character] = self._config_manager.get_character_by_name(character_name)
        if not character:
            return f"找不到角色: {character_name}", [], ""
        
        # 删除立绘目录
        char_dir = os.path.join(UPLOAD_DIR, character.sprite_prefix)
        if os.path.exists(char_dir):
            shutil.rmtree(char_dir)

        # 删除语音目录
        char_voice_dir = os.path.join(VOICE_DIR, character.sprite_prefix)
        if os.path.exists(char_voice_dir):
            shutil.rmtree(char_voice_dir)
        
        # 清空角色属性
        character.sprites = []
        character.emotion_tags = ""
        
        self._config_manager.save_characters_config()
        
        return f"已删除 {character_name} 的所有立绘！", [], ""


    def delete_single_sprite(self, character_name: str, sprite_index: int) -> Tuple[str, List[str], str]:
        """
        删除角色的指定立绘及其语音文件。
        
        Returns:
            Tuple[str, List[str], str]: (操作结果消息, 剩余立绘路径列表, 更新后的情绪标签文本)
        """
        if not character_name:
            return "请先选择角色！", [], ""
        
        character: Optional[Character] = self._config_manager.get_character_by_name(character_name)
        if not character:
            return f"找不到角色: {character_name}", [], ""
        
        # 索引检查
        if not character.sprites or sprite_index < 0 or sprite_index >= len(character.sprites):
            remaining_paths = [s.path if isinstance(s, Sprite) else s.get('path', '') for s in character.sprites]
            return "立绘不存在！", remaining_paths, character.emotion_tags
        
        sprite_data: Union[Sprite, dict] = character.sprites[sprite_index]
        
        # 获取路径
        sprite_path = sprite_data.path if isinstance(sprite_data, Sprite) else sprite_data.get("path", "")
        voice_path = sprite_data.voice_path if isinstance(sprite_data, Sprite) else sprite_data.get("voice_path", "")

        # 删除文件
        if sprite_path and os.path.exists(sprite_path) and os.path.isfile(sprite_path):
            os.remove(sprite_path)
            
        if voice_path and os.path.exists(voice_path) and os.path.isfile(voice_path):
            os.remove(voice_path)
        
        # 从列表中移除
        character.sprites.pop(sprite_index)
        
        # 更新情绪标签
        emotion_tags = ""
        original_tags_list = character.emotion_tags.strip().split('\n') if character.emotion_tags else []
        
        if sprite_index < len(original_tags_list):
            original_tags_list.pop(sprite_index)
        
        for i, line in enumerate(original_tags_list):
            parts = line.split('：') if '：' in line else line.split(':')
            current_tag = parts[-1].strip() if len(parts) > 1 else ""
            emotion_tags += f'立绘 {i+1}：{current_tag}\n'
            
        character.emotion_tags = emotion_tags
        
        self._config_manager.save_characters_config()
        
        remaining_sprite_paths = [s.path if isinstance(s, Sprite) else s.get('path', '') for s in character.sprites]
        return f"已删除 {character_name} 的第 {sprite_index+1} 张立绘！", remaining_sprite_paths, emotion_tags


    def upload_emotion_tags(self, character_name: str, emotion_tags: str) -> str:
        """
        上传/更新角色的情绪标签文本。
        
        Returns:
            str: 操作结果消息。
        """
        if not character_name:
            return "请先选择或创建角色！"
        
        if not emotion_tags: # 假设原始代码中的 emotion_inputs 应该被 emotion_tags 取代
            return "请输入情绪标注！"
        
        character: Optional[Character] = self._config_manager.get_character_by_name(character_name)
        if not character:
            return f"找不到角色: {character_name}"
        
        try:
            character.emotion_tags = emotion_tags
            self._config_manager.save_characters_config()
            return "标注成功！"
        except Exception as e:
            return f"标注出错了：{e}"


    def upload_voice(self, character_name: str, sprite_index: int, voice_file: str, voice_text: str) -> Tuple[str, Optional[str]]:
        """
        为指定立绘上传语音文件。
        
        Returns:
            Tuple[str, Optional[str]]: (操作结果消息, 语音文件路径或 None)
        """
        if not character_name:
            return "请先选择角色！", None
        
        character: Optional[Character] = self._config_manager.get_character_by_name(character_name)
        if not character:
            return f"找不到角色: {character_name}", None
        
        if not character.sprites or sprite_index < 0 or sprite_index >= len(character.sprites):
            return "立绘不存在！", None
        
        sprite_data: Union[Sprite, dict] = character.sprites[sprite_index]
        original_voice_path = sprite_data.voice_path if isinstance(sprite_data, Sprite) else sprite_data.get("voice_path", "")
        
        if (not voice_file) and (not original_voice_path):
            return "请选择语音文件！", None
        
        voice_char_dir = os.path.join(VOICE_DIR, character.sprite_prefix)
        Path(voice_char_dir).mkdir(parents=True, exist_ok=True)
        
        file_ext = Path(voice_file).suffix
        voice_filename = f"voice_{sprite_index:02d}{file_ext}"
        voice_path = os.path.join(voice_char_dir, voice_filename)
        shutil.copyfile(voice_file, voice_path)
        
        # 更新角色数据
        if isinstance(sprite_data, Sprite):
            sprite_data.voice_path = voice_path
            sprite_data.voice_text = voice_text
        else:
            character.sprites[sprite_index]["voice_path"] = voice_path
            character.sprites[sprite_index]["voice_text"] = voice_text
            
        self._config_manager.save_characters_config()
        
        return f"语音已上传到立绘 {sprite_index+1}！", voice_path


    def get_sprite_voice(self, character_name: str, sprite_index: int) -> Tuple[Optional[str], str]:
        """
        获取指定立绘的语音路径和文本。
        
        Returns:
            Tuple[Optional[str], str]: (语音文件路径或 None, 语音文本内容)
        """
        if not character_name or sprite_index is None:
            return None, ""
        
        character: Optional[Character] = self._config_manager.get_character_by_name(character_name)
        
        if not character or not character.sprites or sprite_index < 0 or sprite_index >= len(character.sprites):
            return None, ""
        
        sprite_data: Union[Sprite, dict] = character.sprites[sprite_index]
        
        if isinstance(sprite_data, Sprite):
            voice_path = sprite_data.voice_path
            voice_text = sprite_data.voice_text if sprite_data.voice_text else ""
        else:
            voice_path = sprite_data.get("voice_path", None)
            voice_text = sprite_data.get("voice_text", "")

        return voice_path, voice_text


    def get_character_sprites(self, character_name: str) -> Tuple[List[str], str, List[Any]]:
        """
        获取指定角色的所有立绘路径和情绪标签。
        
        Returns:
            Tuple[List[str], str, List[Any]]: (立绘路径列表, 情绪标签文本, 额外的返回列表 (始终为空))
        """
        if not character_name:
            return [], "", []
        
        character: Optional[Character] = self._config_manager.get_character_by_name(character_name)
        
        if not character:
            return [], "", []

        sprite_paths = [s.path if isinstance(s, Sprite) else s.get('path', '') for s in character.sprites if s]
        emotion_tags = character.emotion_tags if character.emotion_tags else ""
        
        return sprite_paths, emotion_tags, []


    def save_sprite_scale(self, name: str, scale: float) -> str:
        """
        保存角色的立绘缩放比例。
        
        Returns:
            str: 操作结果消息。
        """
        if not name:
            return "名称不能为空！", [c.name for c in self._get_characters()]
            
        character: Optional[Character] = self._config_manager.get_character_by_name(name)

        if character:
            character.sprite_scale = scale
            self._config_manager.save_characters_config()
            return "保存立绘缩放倍率成功"
        
        return f"找不到角色: {name}"


    def load_characters_from_file(self) -> Tuple[str, List[List[str]]]:
        """
        重新加载人物设定文件。
        
        Returns:
            Tuple[str, List[List[str]]]: (操作结果消息, 角色信息列表: [[name, color, prompt_lang], ...])
        """
        try:
            self._config_manager.reload()
            characters = self._config_manager.config.characters
            
            char_info_list = [[c.name, c.color, c.prompt_lang if c.prompt_lang else ""] for c in characters]
            return "人物设定已加载！", char_info_list
        except Exception as e:
            try:
                 characters = self._config_manager.config.characters
                 char_info_list = [[c.name, c.color, c.prompt_lang if c.prompt_lang else ""] for c in characters]
            except:
                 char_info_list = []
                 
            return f"加载失败: {str(e)}", char_info_list