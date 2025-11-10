from pydantic import BaseModel, Field, HttpUrl, FilePath, BeforeValidator
from pydantic_core import PydanticUseDefault
from typing import List, Dict, Optional, Union, Any, Annotated, TypeVar

# ----------------- 解决 YAML None 问题的工具 -----------------
def default_if_none(value: Any) -> Any:
    """
    如果输入值是 None，则抛出 PydanticUseDefault 异常，
    让 Pydantic 使用字段的默认值。
    """
    if value is None:
        raise PydanticUseDefault()
    return value

# 创建一个可复用的 Annotated 类型，用于在遇到 None 时使用默认值
T = TypeVar('T')
# 注意：该 Annotated 类型应包裹原始类型，并且只能用于设置了默认值的字段。
DefaultIfNone = Annotated[T, BeforeValidator(default_if_none)]
# -------------------------------------------------------------


# Character Config Models
class Sprite(BaseModel):
    """角色的单个立绘/语音配置"""
    path: FilePath = Field(..., description="立绘图片的文件路径")
    voice_path: Optional[FilePath] = Field(None, description="对应的语音文件的路径 (可选)")
    voice_text: Optional[str] = Field(None, description="语音对应的文本内容 (可选, 存在于某些条目中)")

class Character(BaseModel):
    """单个角色配置的实体模型"""
    # 角色基本信息
    name: str = Field(..., description="角色名称")
    color: str = Field(..., description="角色对话框或名字的颜色")
    sprite_prefix: str = Field(..., description="立绘文件名的通用前缀")
    
    # 列表中可能包含 Sprite 模型，也可能只是原始字典
    sprites: List[Union[Sprite, dict]] = Field(default_factory=list, description="角色的立绘和对应语音的列表")
    character_setting: DefaultIfNone[str] = Field(default="", description="角色背景、性格和语言习惯的详细描述")
    sprite_scale: DefaultIfNone[float] = Field(default=1.0, description="立绘的缩放比例 (默认值 1.0)")
    emotion_tags: DefaultIfNone[str] = Field(default="", description="情绪标签和对应的立绘编号描述")

    # gpt-sovits 相关的配置
    gpt_model_path: Optional[str] = Field('', description="角色 GPT 模型的路径 (可选)")
    sovits_model_path: Optional[str] = Field('', description="角色的 SoVITS 语音模型路径 (可选)")
    refer_audio_path: Optional[str] = Field('', description="用于语音克隆的参考音频路径 (可选)")
    prompt_text: Optional[str] = Field('', description="角色的初始 Prompt/台词 (可选)")
    prompt_lang: Optional[str] = Field('', description="Prompt 语言，例如: ja (可选)")

class Background(BaseModel):
    """单个背景配置的实体模型"""
    name: str = Field(..., description="背景组名称")
    sprite_prefix: str = Field(..., description="背景图片的上传目录名")
    sprites: List[Union[Sprite, dict]] = Field(default_factory=list, description="背景图片列表")
    bg_tags: DefaultIfNone[str] = Field(default="", description="背景图片的信息") # 应用 DefaultIfNone
    bgm_list: Optional[List[str]] = Field(default_factory=list, description="背景音乐列表")
    bgm_tags: DefaultIfNone[str] = Field(default="",description="背景音乐描述")

# API Config Model
class ApiConfig(BaseModel):
    """API 相关的配置，如 GPT-SoVITS 和 LLM 的设置"""
    gpt_sovits_api_path: DefaultIfNone[str] = Field(default='', description="GPT-SoVITS API 的工作目录")
    gpt_sovits_url: DefaultIfNone[Union[HttpUrl, str]] = Field(default='', description="GPT-SoVITS API 的访问 URL")

    t2i_work_path: DefaultIfNone[str] = Field(default='', description="T2I API 的工作目录")
    t2i_api_url: DefaultIfNone[Union[HttpUrl, str]] = Field(default='http://127.0.0.1:8188', description="T2I API 的访问 URL")
    t2i_default_workflow_path: DefaultIfNone[str] = Field(default='', description="T2I API 默认工作流路径")
    t2i_prompt_node_id: DefaultIfNone[str] = Field(default='6', description="T2I 工作流的 Prompt 节点ID")
    t2i_output_node_id: DefaultIfNone[str] = Field(default='9', description="T2I 工作流的 保存图片 节点id")

    llm_api_key: DefaultIfNone[Dict[str, str]] = Field(default_factory=dict, description="不同 LLM 服务商的 API Key 字典")
    llm_base_url: DefaultIfNone[Union[HttpUrl, str]] = Field(default='', description="LLM 服务的 Base URL")
    llm_model: DefaultIfNone[Dict[str, str]] = Field(default_factory=dict, description="不同 LLM 服务商使用的具体模型名称字典")
    llm_provider: DefaultIfNone[str] = Field(default="Deepseek", description="LLM 服务器商名字")

    hugging_face_access_token: DefaultIfNone[str] = Field(default="", description="Hugging Face Access Token")

# System Config Model
class SystemConfig(BaseModel):
    """系统相关的通用配置"""
    # 应用 DefaultIfNone
    base_font_size_px: DefaultIfNone[int] = Field(default=48, description="基础字体大小 (像素)")
    voice_language: DefaultIfNone[str] = Field(default='ja', description="系统语音的默认语言 (例如: ja)")
    music_volumn: DefaultIfNone[int] =Field(default=30,description="bgm 音量")
    theme_color: DefaultIfNone[str] = Field(default='rgba(50,50,50,200)',description="主题色")

# Main Config Model
class AppConfig(BaseModel):
    """应用的整体配置模型，包含角色列表、API 配置和系统配置"""
    characters: List[Character] = Field(..., description="角色配置列表")
    background_list: List[Background] = Field(..., description="背景组设置")
    api_config: ApiConfig = Field(..., description="API 相关配置")
    system_config: SystemConfig = Field(..., description="系统相关配置")