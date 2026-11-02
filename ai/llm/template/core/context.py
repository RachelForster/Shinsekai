"""Base context shared by prompt sections, independent of chat or model APIs."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TemplateContext:
    """Extend with typed fields for a particular system or user prompt.

    Contexts are passed at render time, never stored on sections. Frozen
    dataclass subclasses can use ``dataclasses.replace`` to derive a context
    for one subtree without changing its siblings' input.
    """
