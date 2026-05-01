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
    tts_provider: DefaultIfNone[str] = Field(
        default="gpt-sovits",
        description="TTS 提供器: gpt-sovits / genie-tts / none（不使用语音合成）",
    )
    tts_speed: DefaultIfNone[float] = Field(default=1.0, description="TTS 语速 (默认值 1.0)")

    t2i_work_path: DefaultIfNone[str] = Field(default='', description="T2I API 的工作目录")
    t2i_api_url: DefaultIfNone[Union[HttpUrl, str]] = Field(default='http://127.0.0.1:8188', description="T2I API 的访问 URL")
    t2i_default_workflow_path: DefaultIfNone[str] = Field(default='', description="T2I API 默认工作流路径")
    t2i_prompt_node_id: DefaultIfNone[str] = Field(default='6', description="T2I 工作流的 Prompt 节点ID")
    t2i_output_node_id: DefaultIfNone[str] = Field(default='9', description="T2I 工作流的 保存图片 节点id")

    llm_api_key: DefaultIfNone[Dict[str, str]] = Field(default_factory=dict, description="不同 LLM 服务商的 API Key 字典")
    llm_base_url: DefaultIfNone[Union[HttpUrl, str]] = Field(default='', description="LLM 服务的 Base URL")
    llm_model: DefaultIfNone[Dict[str, str]] = Field(default_factory=dict, description="不同 LLM 服务商使用的具体模型名称字典")
    llm_provider: DefaultIfNone[str] = Field(default="Deepseek", description="LLM 服务器商名字")
    is_streaming: DefaultIfNone[bool] = Field(default=True, description="是否使用流式响应")
    temperature: DefaultIfNone[float] = Field(default=0.7, description="LLM 采样温度")
    repetition_penalty: DefaultIfNone[float] = Field(default=1.0, description="重复惩罚")
    presence_penalty: DefaultIfNone[float] = Field(default=0.0, description="存在惩罚")
    frequency_penalty: DefaultIfNone[float] = Field(default=0.0, description="频率惩罚")
    max_context_tokens: DefaultIfNone[int] = Field(default=128000, description="最大上下文 token")

    hugging_face_access_token: DefaultIfNone[str] = Field(default="", description="Hugging Face Access Token")

    llm_extra_configs: DefaultIfNone[Dict[str, Dict[str, Any]]] = Field(
        default_factory=dict,
        description="LLM 适配器扩展参数：provider 名 -> 字段名 -> 值",
    )
    tts_extra_configs: DefaultIfNone[Dict[str, Dict[str, Any]]] = Field(
        default_factory=dict,
        description="TTS 适配器扩展参数：引擎 slug -> 字段名 -> 值",
    )
    asr_extra_configs: DefaultIfNone[Dict[str, Dict[str, Any]]] = Field(
        default_factory=dict,
        description="ASR 适配器扩展参数：后端 slug -> 字段名 -> 值",
    )
    t2i_extra_configs: DefaultIfNone[Dict[str, Dict[str, Any]]] = Field(
        default_factory=dict,
        description="T2I 适配器扩展参数：引擎名（如 comfyui） -> 字段名 -> 值",
    )

# System Config Model
class SystemConfig(BaseModel):
    """系统相关的通用配置"""
    # 应用 DefaultIfNone
    base_font_size_px: DefaultIfNone[int] = Field(default=56, description="基础字体大小 (像素)")
    ui_language: DefaultIfNone[str] = Field(
        default="zh_CN",
        description="界面语言: zh_CN / en / ja",
    )
    voice_language: DefaultIfNone[str] = Field(default='ja', description="系统语音的默认语言 (例如: ja)")
    asr_provider: DefaultIfNone[str] = Field(
        default="vosk",
        description="麦克风语音识别后端：vosk | faster_whisper | realtime_stt",
    )
    asr_language: DefaultIfNone[str] = Field(
        default="",
        description="麦克风识别语言 UI 码（en/zh/ja/yue），留空则跟随 ui_language",
    )
    asr_whisper_model_size: DefaultIfNone[str] = Field(
        default="small",
        description="faster-whisper / RealtimeSTT 模型名（如 tiny/base/small）或本地模型目录",
    )
    asr_whisper_device: DefaultIfNone[str] = Field(
        default="auto",
        description="faster-whisper / RealtimeSTT 设备：auto | cuda | cpu",
    )
    asr_whisper_compute_type: DefaultIfNone[str] = Field(
        default="",
        description="faster-whisper / RealtimeSTT compute_type，留空则按设备自动选择",
    )
    music_volumn: DefaultIfNone[int] =Field(default=30,description="bgm 音量")
    theme_color: DefaultIfNone[str] = Field(default='rgba(50,50,50,200)',description="主题色")
    bgm_path: DefaultIfNone[str] = Field(default="",description="BGM 的路径")
    background_path: DefaultIfNone[str] = Field(default="",description="背景图片的路径")
    live_room_id : DefaultIfNone[str] = Field(default="", description="直播间ID，用于直播相关功能")
    chat_window_geometry_b64: DefaultIfNone[str] = Field(
        default="",
        description="聊天主窗口上次关闭时的 saveGeometry Base64，留空则使用默认居中与尺寸",
    )

    # 音乐翻唱流水线（YouTube/B站下载 → UVR 分离 → RVC 转换 → pydub 合成）
    music_cover_work_dir: DefaultIfNone[str] = Field(
        default="./data/music_cover",
        description="翻唱流水线工作目录（下载、分离、中间文件与成品）",
    )
    music_cover_yt_dlp_exe: DefaultIfNone[str] = Field(
        default="",
        description="yt-dlp 可执行文件路径，留空则从 PATH 查找 yt-dlp",
    )
    music_cover_ffmpeg_exe: DefaultIfNone[str] = Field(
        default="",
        description="ffmpeg 可执行文件路径，留空则由 pydub 使用系统 PATH",
    )
    music_cover_uvr_cmd_template: DefaultIfNone[str] = Field(
        default="",
        description=(
            "UVR 或其它分离工具命令模板。占位符：{input_wav} 输入波形，{out_dir} 输出目录。"
            "需在 out_dir 下生成可识别的 vocals / instrumental 波形（文件名含 Vocals、Instrumental、no_vocals 等关键字）。"
        ),
    )
    music_cover_rvc_cmd_template: DefaultIfNone[str] = Field(
        default="",
        description=(
            "留空则使用 rvc-python（RVCInference）；若填写则改为 shell 命令模板。"
            "占位符：{input_wav} 干声，{output_wav} 输出，{model_pth} 模型，{index_file} 索引。"
        ),
    )
    music_cover_rvc_model_path: DefaultIfNone[str] = Field(
        default="",
        description="RVC .pth 模型路径",
    )
    music_cover_rvc_index_path: DefaultIfNone[str] = Field(
        default="",
        description="RVC .index 特征索引路径（可选，无则传空）",
    )
    # rvc-python（RVCInference）参数；若 music_cover_rvc_cmd_template 非空则仍走命令行
    music_cover_rvc_device: DefaultIfNone[str] = Field(
        default="cuda:0",
        description='rvc-python 计算设备，如 "cpu"、"cuda:0"',
    )
    music_cover_rvc_model_version: DefaultIfNone[str] = Field(
        default="v2",
        description='模型版本：v1 或 v2（对应 CLI -v）',
    )
    music_cover_rvc_f0_method: DefaultIfNone[str] = Field(
        default="rmvpe",
        description="音高提取：harvest / crepe / rmvpe / pm",
    )
    music_cover_rvc_pitch: DefaultIfNone[float] = Field(
        default=0.0,
        description="变调（半音）",
    )
    music_cover_rvc_index_rate: DefaultIfNone[float] = Field(
        default=0.75,
        description="特征检索占比 index_rate",
    )
    music_cover_rvc_filter_radius: DefaultIfNone[int] = Field(
        default=3,
        description="音高中值滤波半径 filter_radius",
    )
    music_cover_rvc_resample_sr: DefaultIfNone[int] = Field(
        default=0,
        description="输出重采样采样率，0 表示使用库默认（不强制传参）",
    )
    music_cover_rvc_rms_mix_rate: DefaultIfNone[float] = Field(
        default=0.25,
        description="音量包络混合比例 rms_mix_rate",
    )
    music_cover_rvc_protect: DefaultIfNone[float] = Field(
        default=0.33,
        description="清辅音保护 protect",
    )

# Main Config Model
class AppConfig(BaseModel):
    """应用的整体配置模型，包含角色列表、API 配置和系统配置"""
    characters: List[Character] = Field(..., description="角色配置列表")
    background_list: List[Background] = Field(..., description="背景组设置")
    api_config: ApiConfig = Field(..., description="API 相关配置")
    system_config: SystemConfig = Field(..., description="系统相关配置")