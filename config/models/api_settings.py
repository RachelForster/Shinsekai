"""Pure API/provider settings model and pre-decode legacy normalizers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, Union

from pydantic import BaseModel, Field, HttpUrl, model_validator

from config.models.common import DefaultIfNone, clamp_compact_target_ratio
from config.perception import (
    DEFAULT_PERCEPTION_MODEL,
    DEFAULT_SALIENCE_THRESHOLD,
    GGUF_MODEL_ID,
)


def normalize_api_config_dict(value: Any) -> Any:
    """Upgrade legacy ApiConfig mappings at codec/model boundaries without disk I/O."""
    if not isinstance(value, Mapping):
        return value
    migrated = dict(value)
    if migrated.get("vision_config_version") is None:
        migrated["vision_config_version"] = 1
        selected = str(migrated.get("vision_provider") or "auto").strip().lower() or "auto"
        models = migrated.get("vision_model")
        if (
            selected == "auto"
            and isinstance(models, Mapping)
            and str(models.get("deepseek") or "").strip() == "deepseek-flash"
        ):
            # Mark migration so choosing deepseek-flash explicitly afterward is preserved.
            migrated["vision_model"] = {
                key: model for key, model in models.items() if key != "deepseek"
            }
    if str(migrated.get("perception_model") or "").strip() == GGUF_MODEL_ID:
        migrated["perception_model"] = DEFAULT_PERCEPTION_MODEL
        migrated["perception_use_gguf"] = True
    return migrated


class ApiConfig(BaseModel):
    """API 相关的配置，如 GPT-SoVITS 和 LLM 的设置"""

    gpt_sovits_api_path: DefaultIfNone[str] = Field(default="", description="TTS 服务启动目录（历史字段名）")
    gpt_sovits_url: DefaultIfNone[Union[HttpUrl, str]] = Field(
        default="http://127.0.0.1:9880", description="TTS 服务访问 URL"
    )
    tts_provider: DefaultIfNone[str] = Field(
        default="gpt-sovits",
        description=(
            "TTS 提供器: gpt-sovits / kaggle-gpt-sovits / genie-tts / index-tts / cosyvoice / "
            "qwen3-tts-gguf / none（不使用语音合成）"
        ),
    )
    tts_speed: DefaultIfNone[float] = Field(default=1.0, description="TTS 语速 (默认值 1.0)")

    tts_split_enabled: DefaultIfNone[bool] = Field(default=False, description="是否启用TTS分句发送")
    tts_max_sentence_length: DefaultIfNone[int] = Field(default=15, description="TTS分句最大长度（字符数）")

    t2i_provider: DefaultIfNone[str] = Field(
        default="comfyui",
        description="T2I 引擎标识（与 T2IAdapterFactory 注册名一致，含插件）",
    )
    t2i_work_path: DefaultIfNone[str] = Field(default="", description="T2I API 的工作目录")
    t2i_api_url: DefaultIfNone[Union[HttpUrl, str]] = Field(
        default="http://127.0.0.1:8188", description="T2I API 的访问 URL"
    )
    t2i_default_workflow_path: DefaultIfNone[str] = Field(default="", description="T2I API 默认工作流路径")
    t2i_prompt_node_id: DefaultIfNone[str] = Field(default="6", description="T2I 工作流的 Prompt 节点ID")
    t2i_output_node_id: DefaultIfNone[str] = Field(default="9", description="T2I 工作流的 保存图片 节点id")

    llm_api_key: DefaultIfNone[Dict[str, str]] = Field(
        default_factory=dict, description="不同 LLM 服务商的 API Key 字典"
    )
    llm_base_url: DefaultIfNone[Union[HttpUrl, str]] = Field(default="", description="LLM 服务的 Base URL")
    llm_base_urls: DefaultIfNone[Dict[str, str]] = Field(
        default_factory=dict,
        description="不同模型服务商共用的 Base URL 字典",
    )
    llm_model: DefaultIfNone[Dict[str, str]] = Field(
        default_factory=dict, description="不同 LLM 服务商使用的具体模型名称字典"
    )
    llm_provider: DefaultIfNone[str] = Field(default="Deepseek", description="LLM 服务器商名字")
    is_streaming: DefaultIfNone[bool] = Field(default=True, description="是否使用流式响应")

    vision_provider: DefaultIfNone[str] = Field(
        default="auto",
        description="视觉理解适配器：auto 默认跟随当前 LLM / remote provider / moondream",
    )
    vision_model: DefaultIfNone[Dict[str, str]] = Field(
        default_factory=dict,
        description="不同视觉服务商使用的模型名称字典；未指定时沿用该服务商的 LLM 模型",
    )
    vision_config_version: DefaultIfNone[int] = Field(
        default=1,
        ge=1,
        description="视觉配置迁移版本，用于区分历史默认值与显式模型选择",
    )

    # --- Interrupt & Batch Input ---
    interrupt_enabled: DefaultIfNone[bool] = Field(
        default=True, description="是否启用打断功能：新消息可中断正在生成的回复"
    )
    is_batch_input_enabled: DefaultIfNone[bool] = Field(
        default=False, description="启用批量消息输入：连续发送多条后合并为一条"
    )
    batch_input_timeout: DefaultIfNone[float] = Field(
        default=5.0,
        description="输入框空闲等待时间（秒）：空输入这么长后自动提交批量消息",
        ge=0.3,
        le=120.0,
    )
    batch_input_separator: DefaultIfNone[str] = Field(
        default="\n---\n", description="合并批量消息的分隔符"
    )
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

    knowledge_enabled: DefaultIfNone[bool] = Field(default=False, description="Automatic knowledge retrieval enabled")
    knowledge_search_limit: DefaultIfNone[int] = Field(
        default=5, ge=1, le=20, description="Knowledge search result limit per turn"
    )
    memory_auto_enabled: DefaultIfNone[bool] = Field(
        default=False, description="Automatic long-term memory extraction enabled"
    )
    memory_extract_interval_turns: DefaultIfNone[int] = Field(
        default=5, ge=1, le=50, description="Turns between automatic long-term memory extraction"
    )
    memory_search_limit: DefaultIfNone[int] = Field(
        default=5, ge=1, le=20, description="Long-term memory search result limit per turn"
    )
    memory_recent_buffer_messages: DefaultIfNone[int] = Field(
        default=16, ge=2, le=64, description="Recent messages used for automatic memory extraction"
    )

    # --- Real-time Game Perception (Local VLM Reflex + RP Input Cache + Gatekeeper) ---
    perception_enabled: DefaultIfNone[bool] = Field(default=False, description="是否启用实时画面/游戏状态感知模块")
    perception_base_url: DefaultIfNone[str] = Field(
        default="http://127.0.0.1:8091/v1", description="本地感知小模型 OpenAI 兼容服务地址"
    )
    perception_api_key: DefaultIfNone[str] = Field(default="", description="本地感知模型 API Key（本地服务可留空）")
    perception_model: DefaultIfNone[str] = Field(default=DEFAULT_PERCEPTION_MODEL, description="常规感知模型名称")
    perception_use_gguf: DefaultIfNone[bool] = Field(default=True, description="使用本地 Q4 GGUF 感知模型")
    perception_python_path: DefaultIfNone[str] = Field(
        default="", description="一键启动本地感知推理服务的 Python 解释器或环境路径（默认使用新世界自带 Python 运行时）"
    )
    perception_interval_sec: DefaultIfNone[float] = Field(
        default=2.0, ge=0.5, le=30.0, description="本地感知模型的常规识别间隔（秒）"
    )
    perception_capture_interval_sec: DefaultIfNone[float] = Field(
        default=0.5, ge=0.2, le=5.0, description="共享屏幕画面变化检测间隔（秒）"
    )
    perception_ocr_interval_sec: DefaultIfNone[float] = Field(
        default=1.0, ge=0.5, le=10.0, description="共享屏幕文字识别间隔（秒）"
    )
    perception_frame_max_side: DefaultIfNone[int] = Field(
        default=512, ge=256, le=1280, description="共享屏幕上传帧最大边长（像素）"
    )
    perception_diff_threshold: DefaultIfNone[float] = Field(
        default=0.06, ge=0.0, le=0.5, description="画面像素变化跳过阈值（0 表示每周期都采样）"
    )
    perception_ocr_enabled: DefaultIfNone[bool] = Field(
        default=True, description="由内置本地感知服务识别共享画面中的文字"
    )
    perception_reflex_enabled: DefaultIfNone[bool] = Field(
        default=True, description="启用本地小模型快速反应（实时立绘切换 + 短促气泡台词，无语音）"
    )
    perception_reflex_cooldown_sec: DefaultIfNone[float] = Field(
        default=15.0, ge=0.5, le=60.0, description="气泡反应最小冷却时间（秒）"
    )
    perception_proactive_enabled: DefaultIfNone[bool] = Field(
        default=True, description="启用 Gatekeeper 主动触发主 RP 大模型发言"
    )
    perception_salience_threshold: DefaultIfNone[float] = Field(
        default=DEFAULT_SALIENCE_THRESHOLD,
        ge=0.1,
        le=1.0,
        description="Gatekeeper 放行主动 RP 发言的事件重要度阈值",
    )
    perception_proactive_cooldown_sec: DefaultIfNone[float] = Field(
        default=25.0, ge=3.0, le=600.0, description="主动 RP 发言最小冷却时间（秒）"
    )

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
    vision_extra_configs: DefaultIfNone[Dict[str, Dict[str, Any]]] = Field(
        default_factory=dict,
        description="视觉适配器扩展参数：provider 名 -> 字段名 -> 值",
    )

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_defaults(cls, value: Any) -> Any:
        return normalize_api_config_dict(value)

    @model_validator(mode="after")
    def _clamp_compact_ratios(self):
        self.compact_target_ratio = clamp_compact_target_ratio(
            self.compact_threshold,
            self.compact_target_ratio,
        )
        return self


__all__ = ["ApiConfig", "normalize_api_config_dict"]
