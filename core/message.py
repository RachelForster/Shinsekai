from pydantic import BaseModel, Field
from typing import Optional, Union

# --- 队列消息 Pydantic 模型定义 ---

class UserInputMessage(BaseModel):
    """
    用户输入队列的消息格式 (user_input_queue)。
    包装用户输入的聊天文本。
    """
    text: str = Field(..., description="用户输入的聊天文本")

class LLMDialogMessage(BaseModel):
    """
    LLM 输出对话片段队列的消息格式 (tts_queue)。
    这是从 LLM 响应流中解析出的 JSON 对象。
    """
    character_name: str = Field(..., description="说话的角色名称")
    speech: str = Field(..., description="角色将要说出的文本")
    sprite: Optional[Union[str,int]] = Field("-1", description="角色立绘编号，'-1'表示不需要立绘变化")
    translate: Optional[str] = Field("", description="可选的翻译文本，如果存在则用于 TTS")

class TTSOutputMessage(BaseModel):
    """
    TTS Worker 处理完毕后输出的最终数据队列的消息格式 (audio_path_queue)。
    包含生成的音频文件路径和其他 UI 信息。
    """
    audio_path: str = Field(..., description="生成的语音文件的路径")
    character_name: str = Field(..., description="说话的角色名称")
    speech: str = Field(..., description="原始的角色文本")
    sprite: str = Field(..., description="当前使用的立绘编号")
    is_system_message: bool = Field(False, description="是否是系统通知或非对话消息")