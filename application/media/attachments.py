"""Application facade for staging user-selected chat attachments."""

from core.media.chat_attachments import stage_uploaded_chat_attachments

__all__ = ["stage_uploaded_chat_attachments"]
