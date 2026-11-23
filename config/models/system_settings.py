"""Pure SystemConfig model and pre-decode normalizer (no env/disk side effects)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from config.feature_flags import FeatureFlagConfigManager
from config.models.common import DefaultIfNone
from config.network_proxy import normalize_proxy_url


def normalize_system_config_dict(data: Any) -> Any:
    """Apply fail-closed coercion for persisted experimental flags on SystemConfig mappings."""
    if not isinstance(data, Mapping):
        return data
    updated = dict(data)
    updated.pop("story_system_enabled_diagnostic", None)
    if "story_system_enabled" not in updated:
        return updated
    enabled, diagnostic = FeatureFlagConfigManager.coerce_persisted_value(
        updated.get("story_system_enabled")
    )
    updated["story_system_enabled"] = enabled
    if diagnostic:
        updated["story_system_enabled_diagnostic"] = diagnostic
    return updated


class SystemConfig(BaseModel):
    """系统相关的通用配置"""

    base_font_size_px: DefaultIfNone[int] = Field(default=56, description="基础字体大小 (像素)")
    ui_language: DefaultIfNone[str] = Field(
        default="zh_CN",
        description="界面语言: zh_CN / en / ja",
    )
    voice_language: DefaultIfNone[str] = Field(default="ja", description="系统语音的默认语言 (例如: ja)")
    asr_provider: DefaultIfNone[str] = Field(
        default="sherpa_onnx",
        description="麦克风语音识别后端：sherpa_onnx | vosk | faster_whisper | realtime_stt",
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
    music_volumn: DefaultIfNone[int] = Field(default=30, description="bgm 音量")
    theme_color: DefaultIfNone[str] = Field(default="#d4788e", description="主题色")
    bgm_path: DefaultIfNone[str] = Field(default="", description="BGM 的路径")
    background_path: DefaultIfNone[str] = Field(default="", description="背景图片的路径")
    live_room_id: DefaultIfNone[str] = Field(default="", description="直播间ID，用于直播相关功能")
    chat_window_geometry_b64: DefaultIfNone[str] = Field(
        default="",
        description="聊天主窗口上次关闭时的 saveGeometry Base64（运行态持久化至 data/state/ui_state.json）",
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
        default="react",
        description="聊天界面运行模式；当前固定使用流式 React chat stage",
    )
    story_system_enabled: DefaultIfNone[bool] = Field(
        default=False,
        description="Experimental master switch for every structured story capability.",
    )
    story_system_enabled_diagnostic: Optional[str] = Field(
        default=None,
        exclude=True,
        description="Load-time fail-closed diagnostic for story_system_enabled; never persisted.",
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
    music_cover_rvc_device: DefaultIfNone[str] = Field(
        default="cuda:0",
        description='rvc-python 计算设备，如 "cpu"、"cuda:0"',
    )
    music_cover_rvc_model_version: DefaultIfNone[str] = Field(
        default="v2",
        description="模型版本：v1 或 v2（对应 CLI -v）",
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

    @model_validator(mode="before")
    @classmethod
    def _fail_closed_story_system_enabled(cls, data: Any) -> Any:
        return normalize_system_config_dict(data)

    @field_validator("chat_ui_runtime_mode", mode="before")
    @classmethod
    def _force_react_chat_ui(cls, _value: Any) -> str:
        """Migrate legacy native-mode settings to the supported React runtime."""
        return "react"

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


__all__ = ["SystemConfig", "normalize_system_config_dict"]
