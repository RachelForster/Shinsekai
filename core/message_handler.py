"""
兼容层：TTS / UI 具体实现已分别置于 tts_message_handler、ui_message_handler。
保留此模块以便 `from core.message_handler import get_tts_handlers` 等旧引用仍可用。
"""

from core.tts_message_handler import get_tts_handlers
from core.ui_message_handler import get_ui_output_handlers

__all__ = ["get_tts_handlers", "get_ui_output_handlers"]
