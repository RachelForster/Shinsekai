"""Business-independent Composite sections and extensible render contexts."""

from .catalog import PROMPT_CATALOG, PromptCatalog
from .context import TemplateContext
from .prompt_spec import PromptLanguagePolicy, PromptSpec
from .section import I18nSection, Section, TextSection

__all__ = [
    "I18nSection",
    "PROMPT_CATALOG",
    "PromptCatalog",
    "PromptLanguagePolicy",
    "PromptSpec",
    "Section",
    "TemplateContext",
    "TextSection",
]
