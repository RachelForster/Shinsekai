"""
兼容层：TTS / UI 具体实现已分别置于 :mod:`core.handlers.tts_message_handler`、
:mod:`core.handlers.ui_message_handler`。
保留此模块以便 ``from core.handlers.message_handler import get_tts_handlers`` 等引用仍可用。
"""

from core.handlers.tts_message_handler import get_tts_handlers
from core.handlers.ui_message_handler import get_ui_output_handlers

__all__ = ["get_tts_handlers", "get_ui_output_handlers"]
