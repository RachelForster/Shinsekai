"""Reusable prompt composition primitives, without application initialization."""

from .context import TemplateContext
from .section import Section, TextSection

__all__ = ["Section", "TemplateContext", "TextSection"]
