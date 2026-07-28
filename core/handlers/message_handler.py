"""Compatibility exports for the migrated application handler chains."""

from core.handlers.tts_message_handler import get_tts_handlers
from core.handlers.ui_message_handler import get_ui_output_handlers

__all__ = ["get_tts_handlers", "get_ui_output_handlers"]
