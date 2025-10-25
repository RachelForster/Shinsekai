import os
import shutil
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional, Union
from config.schema import Background, Sprite # 确保导入了 Background 和 Sprite
from config.config_manager import ConfigManager
import gradio as gr 
import yaml 

UPLOAD_DIR = "data/sprites" # 保持不变，但逻辑上应该指向背景图片目录
BACKGROUND_CONFIG_PATH = ConfigManager._BACKGOUND_CONFIG_PATH # 更正为背景配置路径

# 定义背景图片目录的基路径，与角色区分
BACKGROUND_UPLOAD_DIR = "data/backgrounds" # 新增背景专属目录

class BackgroundManager:
    """
    负责背景配置和背景图片（Sprite）的管理。
    内部使用 ConfigManager 来持久化数据。
    """
    
    # 私有属性，用于缓存 LLM Manager 实例 (在此处不相关, 但保留结构)
    _llm_manager: Optional[Any] = None 
    _config_manager: ConfigManager
    
    def __init__(self):
        """初始化 BackgroundManager，获取 ConfigManager 单例。"""
        self._config_manager = ConfigManager()

    def _get_background_list(self) -> List[Background]:
        """获取当前的 Background 列表"""
        try:
            return self._config_manager.config.background_list
        except Exception:
            # 如果配置未加载或失败，返回空列表
            return []
            
    def get_background_name_list(self):
        """获取所有背景组的名称列表"""
        return [b.name for b in self._config_manager.config.background_list]

    def _save_background_config(self) -> None:
        """保存背景配置的便捷方法"""
        self._config_manager.save_background_config()

    def add_background(self, name: str, sprite_prefix: str) -> Tuple[str, List[str]]:
        """
        添加或更新背景配置。
        
        Returns:
            Tuple[str, List[str]]: (操作结果消息, 当前所有背景名称列表)
        """
        current_names = [b.name for b in self._get_background_list()]
        if not name:
            return "名称不能为空！", current_names
            
        background_list = self._config_manager.config.background_list # 修正为 background_list
        existing_background: Optional[Background] = self._config_manager.get_background_by_name(name) # 修正方法

        if existing_background is None:
            # 创建新的 Background 实例
            new_background = Background( # 修正变量名和类型
                name=name,
                sprite_prefix=sprite_prefix,
                sprites=[],
                bg_tags=""
            )    
            background_list.append(new_background)
            self._save_background_config()
            return "背景组已添加！", [b.name for b in background_list] # 修正返回消息
        else:
            # 更新现有 Background 实例的属性
            existing_background.name = name
            existing_background.sprite_prefix = sprite_prefix

            self._save_background_config()
            return "背景组已更新！", [b.name for b in background_list] # 修正返回消息


    def delete_background(self, name: str) -> Tuple[str, List[str]]:
        """
        删除背景组及其相关文件。
        
        Returns:
            Tuple[str, List[str]]: (操作结果消息, 当前所有背景名称列表)
        """
        background_list = self._config_manager.config.background_list # 修正变量名
        current_names = [b.name for b in background_list]
        
        if not name or name == "新背景": # 修正提示
            return "请选择要删除的背景组！", current_names
        
        background_to_delete: Optional[Background] = self._config_manager.get_background_by_name(name) # 修正方法
        
        if background_to_delete is None:
            return f"找不到背景组: {name}", current_names
        
        # 移除背景组
        try:
            background_list.remove(background_to_delete) # 修正列表名
        except ValueError:
            return f"找不到背景组: {name}", current_names
            
        self._save_background_config() # 修正保存方法
        new_names = [b.name for b in background_list]

        sprite_prefix = background_to_delete.sprite_prefix
        if not sprite_prefix:
            return "已删除背景组", new_names
        
        # 删除相关目录 (只删除背景图片目录)
        char_dir = os.path.join(BACKGROUND_UPLOAD_DIR, sprite_prefix) # 修正为背景目录
        if os.path.exists(char_dir):
            shutil.rmtree(char_dir)
        
        return f"背景组 {name} 已删除！", new_names

    def upload_sprites(self, background_name: str, sprite_files: List[Any], bg_tags: str) -> Tuple[str, List[str], str]: # 修正参数名
        """
        上传背景图片文件并更新背景的图片列表和标签。

        Returns:
            Tuple[str, List[str], str]: (操作结果消息, 所有背景图片路径列表, 更新后的标签文本)
        """
        if not background_name:
            return "请先选择或创建背景组！", [], '' # 修正提示
        
        if not sprite_files:
            return "请选择要上传的图片！", [], ''
        
        background: Optional[Background] = self._config_manager.get_background_by_name(background_name) # 修正方法
        if not background:
            return f"找不到背景组: {background_name}", [], '' # 修正提示
        
        # 修正目录，使用 Background 的 prefix 和 BACKGROUND_UPLOAD_DIR
        bg_dir = os.path.join(BACKGROUND_UPLOAD_DIR, background.sprite_prefix) 
        Path(bg_dir).mkdir(parents=True, exist_ok=True)
        
        if background.sprites is None:
            background.sprites = []

        num_existing_sprites = len(background.sprites)
        bg_tags_to_add = '' # 修正变量名
        
        for i, file in enumerate(sprite_files):
            filename = os.path.basename(file.name)
            dest_path = os.path.join(bg_dir, filename)
            shutil.copyfile(file.name, dest_path)
            
            new_sprite_data = {"path": dest_path}
            # Background 模型中的 Sprite 没有 voice_path/voice_text, 保持简单
            background.sprites.append(new_sprite_data)
            
            # 为新上传的图片添加标签占位符
            bg_tags_to_add += f'场景 {num_existing_sprites + i + 1}：\n'
            
        current_bg_tags = background.bg_tags if background.bg_tags else "" # 修正变量名
        background.bg_tags = current_bg_tags + bg_tags_to_add # 修正变量名

        self._config_manager.save_background_config() # 修正保存方法

        all_sprite_paths = [s.path if isinstance(s, Sprite) else s.get('path', '') for s in background.sprites]
        return f"成功为 {background_name} 上传 {len(sprite_files)} 张背景图片！", all_sprite_paths, background.bg_tags # 修正消息


    def delete_all_sprites(self, background_name: str) -> Tuple[str, List[str], str]: # 修正参数名
        """
        删除背景组的所有背景图片。
        
        Returns:
            Tuple[str, List[str], str]: (操作结果消息, 空图片路径列表, 空标签文本)
        """
        if not background_name:
            return "请先选择背景组！", [], "" # 修正提示
        
        background: Optional[Background] = self._config_manager.get_background_by_name(background_name) # 修正方法
        if not background:
            return f"找不到背景组: {background_name}", [], "" # 修正提示
        
        # 删除背景图片目录
        bg_dir = os.path.join(BACKGROUND_UPLOAD_DIR, background.sprite_prefix) # 修正目录
        if os.path.exists(bg_dir):
            shutil.rmtree(bg_dir)
        
        # 清空背景属性
        background.sprites = []
        background.bg_tags = "" # 修正属性
        
        self._config_manager.save_background_config() # 修正保存方法
        
        return f"已删除 {background_name} 的所有背景图片！", [], "" # 修正消息


    def delete_single_sprite(self, background_name: str, sprite_index: int) -> Tuple[str, List[str], str]: # 修正参数名
        """
        删除背景组的指定背景图片。
        
        Returns:
            Tuple[str, List[str], str]: (操作结果消息, 剩余图片路径列表, 更新后的标签文本)
        """
        if not background_name:
            return "请先选择背景组！", [], "" # 修正提示
        
        background: Optional[Background] = self._config_manager.get_background_by_name(background_name) # 修正方法
        if not background:
            return f"找不到背景组: {background_name}", [], "" # 修正提示
        
        # 索引检查
        if not background.sprites or sprite_index < 0 or sprite_index >= len(background.sprites):
            remaining_paths = [s.path if isinstance(s, Sprite) else s.get('path', '') for s in background.sprites]
            return "背景图片不存在！", remaining_paths, background.bg_tags # 修正提示和属性
        
        sprite_data: Union[Sprite, dict] = background.sprites[sprite_index]
        
        # 获取路径
        sprite_path = sprite_data.path if isinstance(sprite_data, Sprite) else sprite_data.get("path", "")
        # 背景图片没有语音文件，移除 voice_path 相关代码
        
        # 删除文件
        if sprite_path and os.path.exists(sprite_path) and os.path.isfile(sprite_path):
            os.remove(sprite_path)
        
        # 从列表中移除
        background.sprites.pop(sprite_index)
        
        # 更新标签
        bg_tags = ""
        original_tags_list = background.bg_tags.strip().split('\n') if background.bg_tags else [] # 修正属性
        
        if sprite_index < len(original_tags_list):
            original_tags_list.pop(sprite_index)
        
        for i, line in enumerate(original_tags_list):
            # 尝试解析并重建标签行
            parts = line.split('：') if '：' in line else line.split(':')
            current_tag = parts[-1].strip() if len(parts) > 1 else ""
            bg_tags += f'场景 {i+1}：{current_tag}\n' # 修正标签前缀
            
        background.bg_tags = bg_tags # 修正属性
        
        self._config_manager.save_background_config() # 修正保存方法
        
        remaining_sprite_paths = [s.path if isinstance(s, Sprite) else s.get('path', '') for s in background.sprites]
        return f"已删除 {background_name} 的第 {sprite_index+1} 张背景图片！", remaining_sprite_paths, bg_tags # 修正消息


    def upload_bg_tags(self, background_name: str, bg_tags: str) -> str: # 修正函数名和参数名
        """
        上传/更新背景的标签文本。
        
        Returns:
            str: 操作结果消息。
        """
        if not background_name:
            return "请先选择或创建背景组！" # 修正提示
        
        if not bg_tags: # 修正变量名
            return "请输入背景标注！" # 修正提示
        
        background: Optional[Background] = self._config_manager.get_background_by_name(background_name) # 修正方法
        if not background:
            return f"找不到背景组: {background_name}" # 修正提示
        
        try:
            background.bg_tags = bg_tags # 修正属性
            self._config_manager.save_background_config() # 修正保存方法
            return "标注成功！"
        except Exception as e:
            return f"标注出错了：{e}"

    def get_background_sprites(self, background_name: str) -> Tuple[List[str], str, List[Any]]: # 修正函数名和参数名
        """
        获取指定背景组的所有背景图片路径和标签。
        
        Returns:
            Tuple[List[str], str, List[Any]]: (图片路径列表, 标签文本, 额外的返回列表 (始终为空))
        """
        if not background_name:
            return [], "", []
        
        background: Optional[Background] = self._config_manager.get_background_by_name(background_name) # 修正方法
        
        if not background:
            return [], "", []

        sprite_paths = [s.path if isinstance(s, Sprite) else s.get('path', '') for s in background.sprites if s]
        bg_tags = background.bg_tags if background.bg_tags else "" # 修正属性
        
        return sprite_paths, bg_tags, []


    def load_backgrounds_from_file(self) -> Tuple[str, List[List[str]]]: # 修正函数名
        """
        重新加载背景设定文件。
        
        Returns:
            Tuple[str, List[List[str]]]: (操作结果消息, 背景信息列表: [[name, sprite_prefix, bg_tags], ...])
        """
        try:
            self._config_manager.reload()
            background_list = self._config_manager.config.background_list # 修正列表名
            
            # Background 模型没有 color, prompt_lang 属性，使用 name, sprite_prefix, bg_tags
            bg_info_list = [[b.name, b.sprite_prefix, b.bg_tags if b.bg_tags else ""] for b in background_list] 
            return "背景设定已加载！", bg_info_list # 修正消息
        except Exception as e:
            try:
                 background_list = self._config_manager.config.background_list # 修正列表名
                 bg_info_list = [[b.name, b.sprite_prefix, b.bg_tags if b.bg_tags else ""] for b in background_list]
            except:
                 bg_info_list = []
                 
            return f"加载失败: {str(e)}", bg_info_list