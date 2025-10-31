import os
import shutil
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional, Union
from config.schema import Background, Sprite # 确保导入了 Background 和 Sprite
from config.config_manager import ConfigManager
import tools.file_util as fu
import pandas as pd
import gradio as gr 
import yaml 

BACKGROUND_CONFIG_PATH = ConfigManager._BACKGOUND_CONFIG_PATH # 更正为背景配置路径
BACKGROUND_UPLOAD_DIR = "data/backgrounds"
BGM_UPLOAD_DIR = "data/bgm"

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
                bg_tags="",
                bgm_list=[],
                bgm_tags="",
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
            background_list.remove(background_to_delete)
        except ValueError:
            return f"找不到背景组: {name}", current_names
            
        self._save_background_config() # 修正保存方法
        new_names = [b.name for b in background_list]

        sprite_prefix = background_to_delete.sprite_prefix
        if not sprite_prefix:
            return "已删除背景组", new_names
        
        # 删除相关目录 (只删除背景图片目录)
        char_dir = os.path.join(BACKGROUND_UPLOAD_DIR, sprite_prefix) # 修正为背景目录
        if sprite_prefix and os.path.exists(char_dir):
            shutil.rmtree(char_dir)

        bgm_dir = os.path.join(BGM_UPLOAD_DIR, sprite_prefix) # 删除相关 BGM 目录
        if sprite_prefix and os.path.exists(bgm_dir):
            shutil.rmtree(bgm_dir)
        
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
        
    # ------------------------- BGM 管理 --------------------------
    def upload_bgms(self, background_name: str, bgm_files: List[Any]):
        """
        上传背景音乐文件并更新背景的音乐列表和标签。

        Returns:
            Tuple[str, List[str], str]: (操作结果消息, 所有背景音乐路径列表, 更新后的标签文本)
        """
        if not background_name:
            return "请先选择或创建背景组！", pd.DataFrame(), ''
        
        if not bgm_files:
            return "请选择要上传的背景音乐文件！", pd.DataFrame(), ''
        
        background: Optional[Background] = self._config_manager.get_background_by_name(background_name)
        if not background:
            return f"找不到背景组: {background_name}", pd.DataFrame(), ''
        
        # 修正目录，使用 Background 的 prefix 和 BGM_UPLOAD_DIR
        bgm_dir = os.path.join(BGM_UPLOAD_DIR, background.sprite_prefix) # 使用 sprite_prefix 作为子目录名
        Path(bgm_dir).mkdir(parents=True, exist_ok=True)
        
        # 确保 bgm_list 存在
        if not hasattr(background, 'bgm_list') or background.bgm_list is None:
            background.bgm_list = []

        num_existing_bgms = len(background.bgm_list)
        bgm_tags_to_add = ''
        
        for i, file in enumerate(bgm_files):
            filename = os.path.basename(file.name)
            dest_path = os.path.join(bgm_dir, filename)
            shutil.copyfile(file.name, dest_path)
            
            # 假设 bgm_list 存储的是路径字符串
            background.bgm_list.append(dest_path) 
            
            # 为新上传的音乐添加标签占位符
            bgm_tags_to_add += f'音乐 {num_existing_bgms + i + 1}：\n'
            
        current_bgm_tags = background.bgm_tags if hasattr(background, 'bgm_tags') and background.bgm_tags else ""
        background.bgm_tags = current_bgm_tags + bgm_tags_to_add

        self._config_manager.save_background_config()

        df, tags = self.load_bgms_and_tags(background_name)

        return f"成功为 {background_name} 上传 {len(bgm_files)} 个背景音乐文件！", df, tags


    def delete_all_bgms(self, background_name: str) -> Tuple[str, List[str], str]:
        """
        删除背景组的所有背景音乐文件。
        
        Returns:
            Tuple[str, List[str], str]: (操作结果消息, 空音乐路径列表, 空标签文本)
        """
        if not background_name:
            return "请先选择背景组！", [], ""
        
        background: Optional[Background] = self._config_manager.get_background_by_name(background_name)
        if not background:
            return f"找不到背景组: {background_name}", [], ""
        
        # 删除背景音乐目录
        bgm_dir = os.path.join(BGM_UPLOAD_DIR, background.sprite_prefix)
        if os.path.exists(bgm_dir):
            shutil.rmtree(bgm_dir)
        
        # 清空背景属性
        if hasattr(background, 'bgm_list'):
            background.bgm_list = []
        if hasattr(background, 'bgm_tags'):
            background.bgm_tags = ""
        
        self._config_manager.save_background_config()
        
        return f"已删除 {background_name} 的所有背景音乐！", [], ""


    def upload_bgm_tags(self, background_name: str, bgm_tags: str) -> str:
        """
        上传/更新背景的音乐标签文本。
        
        Returns:
            str: 操作结果消息。
        """
        if not background_name:
            return "请先选择或创建背景组！"
        
        if not bgm_tags:
            return "请输入背景音乐标注！"
        
        background: Optional[Background] = self._config_manager.get_background_by_name(background_name)
        if not background:
            return f"找不到背景组: {background_name}"
        
        try:
            background.bgm_tags = bgm_tags
            self._config_manager.save_background_config()
            return "背景音乐标注成功！"
        except Exception as e:
            return f"背景音乐标注出错了：{e}"


    def get_background_bgms(self, background_name: str):
        """
        获取指定背景组的所有背景音乐路径和标签。
        
        Returns:
            Tuple[List[str], str, List[Any]]: (音乐路径列表, 标签文本, 额外的返回列表 (始终为空))
        """
        if not background_name:
            return [], "", []
        
        background: Optional[Background] = self._config_manager.get_background_by_name(background_name)
        
        if not background:
            return [], "", []

        bgm_paths = getattr(background, 'bgm_list', [])
        bgm_tags = getattr(background, 'bgm_tags', "")
        
        return bgm_paths, bgm_tags, []
    
    def format_bgms_for_display(self,bgm_paths: List[str], bgm_tags: str) -> pd.DataFrame:
        """
        将 BGM 路径和标签格式化为带序号和复选框的 Dataframe。
        """
        data = []
        # 尝试解析标签（假设标签是按行与路径对应的）
        tags_list = bgm_tags.strip().split('\n') if bgm_tags else []
        
        for i, path in enumerate(bgm_paths):
            # 提取文件名
            file_name = os.path.basename(path)
            # 获取对应标签，如果标签列表不够长，则使用空字符串
            tag_line = tags_list[i] if i < len(tags_list) else ""
            # 尝试从标签行中提取实际内容（跳过 '音乐 X：' 前缀）
            tag_content = tag_line.split('：', 1)[-1].strip() if '：' in tag_line else tag_line

            data.append({
                "选择": False, # 默认不选中
                "序号": i + 1,
                "文件名": file_name,
                "路径": path,
                "标签描述": tag_content
            })
        return pd.DataFrame(data)
    
    def load_bgms_and_tags(self, background_name: str):
        """
        根据选择的背景组加载并显示 BGM 列表和标签。
        """
        if not background_name:
            return pd.DataFrame(), ""
            
        bgm_paths, bgm_tags, _ = self.get_background_bgms(background_name)
        
        # 将路径和标签转换为 Dataframe 格式
        bgm_dataframe = self.format_bgms_for_display(bgm_paths, bgm_tags)
        
        return bgm_dataframe, bgm_tags
    
    def delete_single_bgm(self, background_name: str, bgm_index: int) -> Tuple[str, List[str], str]:
        """
        删除背景组的指定背景音乐文件。
        
        Returns:
            Tuple[str, List[str], str]: (操作结果消息, 剩余音乐路径列表, 更新后的标签文本)
        """
        if not background_name:
            return "请先选择背景组！", [], ""
        
        background: Optional[Background] = self._config_manager.get_background_by_name(background_name)
        if not background:
            return f"找不到背景组: {background_name}", [], ""
        
        bgm_list = getattr(background, 'bgm_list', [])
        bgm_tags = getattr(background, 'bgm_tags', "")

        # 索引检查
        if not bgm_list or bgm_index < 0 or bgm_index >= len(bgm_list):
            return "背景音乐不存在！", bgm_list, bgm_tags
        
        bgm_path: str = bgm_list[bgm_index]
        
        # 删除文件
        if bgm_path and os.path.exists(bgm_path) and os.path.isfile(bgm_path):
            os.remove(bgm_path)
        
        # 从列表中移除
        bgm_list.pop(bgm_index)
        
        # 更新标签
        new_bgm_tags = ""
        original_tags_list = bgm_tags.strip().split('\n') if bgm_tags else []
        
        if bgm_index < len(original_tags_list):
            original_tags_list.pop(bgm_index)
        
        for i, line in enumerate(original_tags_list):
            # 尝试解析并重建标签行
            parts = line.split('：') if '：' in line else line.split(':')
            current_tag = parts[-1].strip() if len(parts) > 1 else ""
            new_bgm_tags += f'音乐 {i+1}：{current_tag}\n'
        
        background.bgm_tags = new_bgm_tags
        
        self._config_manager.save_background_config()
        
        return f"已删除 {background_name} 的第 {bgm_index+1} 个背景音乐文件！", bgm_list, new_bgm_tags

    def batch_delete_bgms(
        self,
        background_name: str, 
        bgm_dataframe: pd.DataFrame,
        bgm_tags 
    ) -> Tuple[str, pd.DataFrame]:
        """
        根据 Dataframe 中的复选框状态批量删除选定的背景音乐。
        """
        if not background_name:
            return "请先选择背景组！", pd.DataFrame(), bgm_tags

        if bgm_dataframe.empty:
            return "没有音乐条可供删除。", pd.DataFrame(), ""

        # 1. 确定要删除的索引
        try:
            # 获取 Dataframe 中 '选择' 为 True 的行
            selected_rows = bgm_dataframe[bgm_dataframe['选择'] == True]
            # 获取这些行在原始 BGM 列表中的索引 (即 '序号' - 1)
            indices_to_delete = selected_rows['序号'].tolist()
        except Exception as e:
            return f"处理数据失败: {e}", bgm_dataframe, bgm_tags

        if not indices_to_delete:
            return "请勾选要删除的音乐条。", bgm_dataframe, bgm_tags

        # 2. 批量删除（从大索引到小索引，防止删除操作改变后续索引）
        indices_to_delete.sort(reverse=True)
        
        deleted_count = 0
        message = ""

        for original_index in indices_to_delete:
            # 注意：这里的 index 是用户看到的 '序号' (从 1 开始)，需要减 1 转换为 Python 列表索引 (从 0 开始)
            list_index = original_index - 1 
            
            # 调用 Manager 的单条删除方法
            try:
                msg, remaining_paths, remaining_tags = self.delete_single_bgm(background_name, list_index)
                # 如果删除成功，则计数
                if "已删除" in msg:
                    deleted_count += 1
                else:
                    message += f"删除序号 {original_index} 失败: {msg}\n"
            except Exception as e:
                message += f"删除序号 {original_index} 发生异常: {e}\n"

        # 3. 重新加载和显示剩余的 BGM
        remaining_paths, remaining_tags, _ = self.get_background_bgms(background_name)
        new_dataframe = self.format_bgms_for_display(remaining_paths, remaining_tags)

        final_message = f"成功删除了 {deleted_count} 个音乐条。"
        if message:
            final_message += "\n部分删除失败的提示：\n" + message
            
        return final_message, new_dataframe, remaining_tags
    
    def handle_bgm_selection(self, evt: gr.SelectData, bgm_dataframe: pd.DataFrame):
        """
        处理 Dataframe 行选择事件，返回选中行的路径和 Audio 组件的更新。
        
        Returns:
            Tuple[str, gr.Audio.update]: (操作消息, Audio 组件更新对象)
        """
        if evt is None or evt.index is None:
            return "请点击 Dataframe 中的一行。", ""
        
        # 获取点击的行索引 (evt.index 是 (row_index, col_index))
        row_index = evt.index[0]
        
        if row_index < 0 or row_index >= len(bgm_dataframe):
            return "无效的行选择。", ""
        
        # 从 Dataframe 中取出选中行对应的文件路径
        # 假设 '路径' 是 Dataframe 中的一列
        try:
            selected_path = bgm_dataframe.iloc[row_index]['路径']
            
            if not selected_path or not os.path.exists(selected_path):
                return f"文件路径不存在: {selected_path}", ""
                
            file_name = os.path.basename(selected_path)
            
            # 返回更新后的 Audio 组件
            return (
                f"正在播放: {file_name}", 
                selected_path
            )
            
        except KeyError:
            return "Dataframe 缺少 '路径' 列，无法播放。", ""
        except Exception as e:
            return f"播放出错: {e}", ""
        

    def export_background_file(self, background_name: str) -> str:
        """导出指定背景组到 .bg 文件"""
        try:
            background: Optional[Background] = self._config_manager.get_background_by_name(background_name)
            if not background:
                return f"找不到背景组: {background_name}"

            fu.export_background([background], f"./output/{background_name}.bg")
            return f"背景组已导出到: /output/{background_name}.bg"
        except Exception as e:
            return f"背景导出失败: {e}"
    def import_background_file(self, input_path: str):
        """从 .bg 文件导入背景配置"""
        try:
            existing_configs = self._config_manager.config.background_list
            new_configs = fu.import_background(input_path, existing_configs)
            
            # 将导入的配置合并到现有配置中
            # 注意：import_background 已经处理了冲突，这里只需要追加
            for config in new_configs:
                # 检查是否因为冲突被重命名，如果 name 已在 existing_configs 中，则说明是 import 函数解决的冲突
                if config not in existing_configs:
                     existing_configs.append(config)

            self._config_manager.save_background_config()
            
            # 刷新显示列表 (与 load_backgrounds_from_file 类似)
            bg_name_list = [b.name for b in existing_configs]
            
            return f"成功导入 {len(new_configs)} 个背景组！", bg_name_list
        except Exception as e:
            # 刷新显示列表
            bg_name_list = [b.name for b in self._config_manager.config.background_list]
            return f"背景导入失败: {e}", bg_name_list