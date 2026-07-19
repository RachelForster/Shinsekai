"""
队列消息 Pydantic 模型。

字段别名保持 LLM JSON 兼容：旧 key ``character_name`` / ``speech`` / ``sprite`` 可继续用于
解析，代码中统一用 ``name`` / ``text`` / ``asset_id``。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Union


class UserInputMessage(BaseModel):
    """用户输入队列的消息格式 (user_input_queue)。"""

    text: str = Field(..., description="用户输入的聊天文本")


class LLMDialogMessage(BaseModel):
    """LLM 输出对话片段队列的消息格式 (tts_queue)。"""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str = Field(..., alias="character_name", description="实体名称（角色名 / 系统关键字如 bgm/NARR 等）")
    text: Optional[str] = Field("", alias="speech", description="文本内容（台词 / 系统提示）")
    asset_id: Optional[Union[str, int]] = Field("-1", alias="sprite", description="资源编号（立绘索引 / BGM 索引等），-1 表示无需变化")
    translate: Optional[str] = Field("", description="可选的翻译文本，如果存在则用于 TTS")
    effect: Optional[str] = Field("", description="特效名称")
    turn_id: Optional[int] = Field(
        None,
        exclude=True,
        repr=False,
        description="Internal runtime turn identity",
    )


class TTSOutputMessage(BaseModel):
    """TTS Worker 处理后输出的 UI 队列消息 (audio_path_queue)。"""

    model_config = ConfigDict(populate_by_name=True)

    audio_path: str = Field(..., description="生成的语音 / 资源文件的路径")
    name: str = Field(..., alias="character_name", description="实体名称")
    text: Optional[str] = Field("", alias="speech", description="文本内容")
    asset_id: Optional[Union[str, int]] = Field("-1", alias="sprite", description="资源编号")
    effect: Optional[str] = Field("", description="特效名称")
    is_system_message: bool = Field(False, description="是否是系统通知或非对话消息")
    is_final_segment: bool = Field(True, description="是否是多段TTS中的最后一段")
    timeout: Optional[float] = Field(None, description="可选的等待时间（秒）")
