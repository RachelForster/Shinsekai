"""Structured diagnostics emitted by story loading and compilation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class DiagnosticSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class StoryDiagnostic:
    code: str
    message: str
    path: str
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR


class StoryValidationError(ValueError):
    """Raised when a story source cannot be normalized safely."""

    def __init__(self, diagnostics: Iterable[StoryDiagnostic]) -> None:
        self.diagnostics = tuple(diagnostics)
        summary = "; ".join(
            f"{diagnostic.path}: {diagnostic.message}"
            for diagnostic in self.diagnostics
        )
        super().__init__(summary or "story validation failed")


class StoryCompileError(StoryValidationError):
    """Raised when a normalized project cannot be compiled."""
