"""Built-in Ren'Py-style script DSL dialog format package."""

from .errors import RenpyParseError, format_renpy_parse_error, renpy_error
from .format import RenpyDslDialogFormat, RenpyPromptProvider
from .lexer import RESERVED_SPEAKER_KEYWORDS, format_renpy_speaker, quote_dsl_string
from .parser import RenpyDslStreamParser

__all__ = [
    "RESERVED_SPEAKER_KEYWORDS",
    "RenpyDslDialogFormat",
    "RenpyDslStreamParser",
    "RenpyParseError",
    "RenpyPromptProvider",
    "format_renpy_parse_error",
    "format_renpy_speaker",
    "quote_dsl_string",
    "renpy_error",
]
