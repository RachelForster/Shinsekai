from pydantic import BaseModel, Field, HttpUrl, FilePath
from typing import List, Dict, Optional, Union

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
    # 使用 Union[List[Sprite], List[dict]] 提高兼容性
    sprites: List[Union[Sprite, dict]] = Field(default_factory=list, description="角色的立绘和对应语音的列表")
    
    character_setting: str = Field(default="", description="角色背景、性格和语言习惯的详细描述")
    sprite_scale: float = Field(default=1.0, description="立绘的缩放比例 (默认值 1.0)")
    emotion_tags: str = Field(default="", description="情绪标签和对应的立绘编号描述")
    
    # gpt-sovits 相关的配置
    gpt_model_path: Optional[str] = Field(None, description="角色 GPT 模型的路径 (可选)")
    sovits_model_path: Optional[str] = Field(None, description="角色的 SoVITS 语音模型路径 (可选)")
    refer_audio_path: Optional[str] = Field(None, description="用于语音克隆的参考音频路径 (可选)")
    prompt_text: Optional[str] = Field(None, description="角色的初始 Prompt/台词 (可选)")
    prompt_lang: Optional[str] = Field(None, description="Prompt 语言，例如: ja (可选)")


# API Config Model
class ApiConfig(BaseModel):
    """API 相关的配置，如 GPT-SoVITS 和 LLM 的设置"""
    gpt_sovits_api_path: Optional[str] = Field(..., description="GPT-SoVITS API 的安装路径")
    gpt_sovits_url: Optional[Union[HttpUrl, str]] = Field(..., description="GPT-SoVITS API 的访问 URL")
    llm_api_key: Dict[str, str] = Field(..., description="不同 LLM 服务商的 API Key 字典")
    llm_base_url: Union[HttpUrl, str] = Field(..., description="LLM 服务的 Base URL")
    llm_model: Dict[str, str] = Field(..., description="不同 LLM 服务商使用的具体模型名称字典")
    llm_provider: Optional[str] = Field("Deepseek", description="LLM 服务器商名字")

# System Config Model
class SystemConfig(BaseModel):
    """系统相关的通用配置"""
    base_font_size_px: Optional[int] = Field(48, description="基础字体大小 (像素)")
    voice_language: Optional[str] = Field(..., description="系统语音的默认语言 (例如: ja)")

# Main Config Model
class AppConfig(BaseModel):
    """应用的整体配置模型，包含角色列表、API 配置和系统配置"""
    characters: List[Character] = Field(..., description="角色配置列表")
    api_config: ApiConfig = Field(..., description="API 相关配置")
    system_config: SystemConfig = Field(..., description="系统相关配置")