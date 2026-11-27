"""Built-in Ren'Py-style script DSL dialog format package."""

from .errors import RenpyParseError, format_renpy_parse_error, renpy_error
from .format import (
    RenpyDslDialogFormat,
    RenpyPromptProvider,
    get_default_renpy_prompt_provider,
    set_default_renpy_prompt_provider,
)
from .lexer import RESERVED_SPEAKER_KEYWORDS, format_renpy_speaker
from .parser import RenpyDslStreamParser
from .plugin import RenpyDslPlugin

__all__ = [
    "RESERVED_SPEAKER_KEYWORDS",
    "RenpyDslDialogFormat",
    "RenpyDslPlugin",
    "RenpyDslStreamParser",
    "RenpyParseError",
    "RenpyPromptProvider",
    "format_renpy_parse_error",
    "format_renpy_speaker",
    "get_default_renpy_prompt_provider",
    "renpy_error",
    "set_default_renpy_prompt_provider",
]
