"""Business-independent Composite sections and extensible render contexts."""

from .context import TemplateContext
from .section import Section, TextSection

__all__ = ["Section", "TemplateContext", "TextSection"]
