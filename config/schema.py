from pydantic import BaseModel, Field, HttpUrl, FilePath, BeforeValidator, model_validator
from pydantic_core import PydanticUseDefault
from typing import List, Dict, Optional, Union, Any, Annotated, TypeVar
from config.network_proxy import normalize_proxy_url

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

COMPACT_TARGET_RATIO_MIN_GAP = 0.05


def clamp_compact_target_ratio(compact_threshold: float, compact_target_ratio: float) -> float:
    """Keep compaction target safely below the trigger threshold."""
    try:
        threshold = float(compact_threshold)
        target = float(compact_target_ratio)
    except (TypeError, ValueError):
        return compact_target_ratio
    max_target = max(0.0, threshold - COMPACT_TARGET_RATIO_MIN_GAP)
    return round(min(target, max_target), 6)


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
    speech_speed: DefaultIfNone[float] = Field(default=1.0, description="角色TTS语速倍率 (默认值 1.0)")
    speech_volume: DefaultIfNone[float] = Field(default=1.0, description="角色TTS语音音量 (0.0-2.0, 默认 1.0)")
    pronunciation_map: DefaultIfNone[Dict[str, str]] = Field(default_factory=dict, description="角色名 → 日语读音映射（用于 TTS 发音替换）")

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
    gpt_sovits_url: DefaultIfNone[Union[HttpUrl, str]] = Field(default='http://127.0.0.1:9880', description="GPT-SoVITS API 的访问 URL")
    tts_provider: DefaultIfNone[str] = Field(
        default="gpt-sovits",
        description="TTS 提供器: gpt-sovits / kaggle-gpt-sovits / genie-tts / none（不使用语音合成）",
    )
    tts_speed: DefaultIfNone[float] = Field(default=1.0, description="TTS 语速 (默认值 1.0)")

    tts_split_enabled: DefaultIfNone[bool] = Field(default=False, description="是否启用TTS分句发送")
    tts_max_sentence_length: DefaultIfNone[int] = Field(default=15, description="TTS分句最大长度（字符数）")

    t2i_provider: DefaultIfNone[str] = Field(
        default="comfyui",
        description="T2I 引擎标识（与 T2IAdapterFactory 注册名一致，含插件）",
    )
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
    compact_threshold: DefaultIfNone[float] = Field(default=0.4, description="触发历史压缩的上下文占比")
    compact_target_ratio: DefaultIfNone[float] = Field(default=0.3, description="历史压缩后的目标上下文占比")
    history_recent_messages: DefaultIfNone[int] = Field(default=20, description="压缩或加载历史时保留的最近消息数")
    max_tool_result_chars: DefaultIfNone[int] = Field(default=6000, description="写入历史的单次工具结果最大字符数")
    max_active_tool_groups: DefaultIfNone[int] = Field(default=3, description="同时启用的工具组数量上限")

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

    @model_validator(mode="after")
    def _clamp_compact_ratios(self):
        self.compact_target_ratio = clamp_compact_target_ratio(
            self.compact_threshold,
            self.compact_target_ratio,
        )
        return self

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
    theme_color: DefaultIfNone[str] = Field(default='#d4788e',description="主题色")
    bgm_path: DefaultIfNone[str] = Field(default="",description="BGM 的路径")
    background_path: DefaultIfNone[str] = Field(default="",description="背景图片的路径")
    live_room_id : DefaultIfNone[str] = Field(default="", description="直播间ID，用于直播相关功能")
    chat_window_geometry_b64: DefaultIfNone[str] = Field(
        default="",
        description="聊天主窗口上次关闭时的 saveGeometry Base64，留空则使用默认居中与尺寸",
    )
    chat_ui_theme_path: DefaultIfNone[str] = Field(
        default="",
        description="聊天主窗外观补丁 JSON 路径，留空则使用 data/chat_ui_theme.json（若存在）",
    )
    chat_ui_theme_id: DefaultIfNone[str] = Field(
        default="windborne-adventure",
        description="React chat stage 当前激活的主题 mod id（对应 data/chat_ui_themes/<id>/），留空则用默认主题",
    )
    chat_ui_runtime_mode: DefaultIfNone[str] = Field(
        default="native",
        description="聊天界面运行模式：native 使用原生 Qt 聊天窗口；react 使用流式 React chat stage",
    )
    react_chat_fork_experimental_enabled: DefaultIfNone[bool] = Field(
        default=False,
        description="实验性功能：启用 React Chat UI 的历史 Fork 功能",
    )
    react_chat_flowchart_experimental_enabled: DefaultIfNone[bool] = Field(
        default=False,
        description="实验性功能：启用 React Chat UI 的对话分支流程图/树功能",
    )

    # 音乐翻唱流水线（YouTube/B站下载 → UVR 分离 → RVC 转换 → pydub 合成）
    mirror_auto_detect_china: DefaultIfNone[bool] = Field(
        default=True,
        description="Auto-detect China network and fill mirror sources.",
    )
    mirror_region: DefaultIfNone[str] = Field(
        default="auto",
        description="Detected mirror region: auto / china / global.",
    )
    huggingface_mirror_url: DefaultIfNone[str] = Field(
        default="",
        description="Hugging Face mirror URL, exported as HF_ENDPOINT.",
    )
    huggingface_cache_dir: DefaultIfNone[str] = Field(
        default="",
        description="Hugging Face cache directory, exported as HF_HOME.",
    )
    github_mirror_url: DefaultIfNone[str] = Field(
        default="",
        description="GitHub mirror URL or proxy prefix.",
    )
    pypi_mirror_url: DefaultIfNone[str] = Field(
        default="",
        description="PyPI mirror URL for Shinsekai-managed pip installs.",
    )
    network_proxy_enabled: DefaultIfNone[bool] = Field(
        default=False,
        description="Whether Shinsekai should write the configured proxy URLs to process environment variables.",
    )
    http_proxy_url: DefaultIfNone[str] = Field(
        default="",
        description="HTTP proxy URL, exported as HTTP_PROXY/http_proxy.",
    )
    https_proxy_url: DefaultIfNone[str] = Field(
        default="",
        description="HTTPS proxy URL, exported as HTTPS_PROXY/https_proxy.",
    )
    socks5_proxy_url: DefaultIfNone[str] = Field(
        default="",
        description="SOCKS5 proxy URL, exported as ALL_PROXY/all_proxy.",
    )

    @model_validator(mode="after")
    def _normalize_proxy_urls(self):
        self.http_proxy_url = normalize_proxy_url(
            self.http_proxy_url,
            allowed_schemes={"http", "https"},
            field_name="http_proxy_url",
        )
        self.https_proxy_url = normalize_proxy_url(
            self.https_proxy_url,
            allowed_schemes={"http", "https"},
            field_name="https_proxy_url",
        )
        self.socks5_proxy_url = normalize_proxy_url(
            self.socks5_proxy_url,
            allowed_schemes={"socks5", "socks5h"},
            field_name="socks5_proxy_url",
        )
        return self

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
