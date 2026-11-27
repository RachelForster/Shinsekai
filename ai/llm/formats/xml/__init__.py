"""Built-in XML / HTML tag dialog format package (`xml_v1`)."""

from .format import XmlTagsDialogFormat
from .parser import NEXT_STAGE_OPEN_RE, XmlTagsStreamParser

__all__ = [
    "NEXT_STAGE_OPEN_RE",
    "XmlTagsDialogFormat",
    "XmlTagsStreamParser",
]
