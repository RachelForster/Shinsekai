"""Default dialog system prompt, its context and patch-compatible sections."""

from .builder import build_dialog_section
from .context import DialogTemplateContext

__all__ = ["DialogTemplateContext", "build_dialog_section"]
