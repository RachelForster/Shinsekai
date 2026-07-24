"""Lightweight, dependency-free path helpers.

Kept import-light on purpose so any module can reuse these without pulling
in the rest of the frontend bridge.
"""

from __future__ import annotations

import os
from pathlib import Path


def strip_windows_verbatim_prefix(value: str) -> str:
    r"""Drop Windows extended-length path prefixes (``\\?\`` / ``//?/``, incl. UNC).

    ``Path.resolve()`` can hand back such a prefixed path for long paths on
    Windows; stripping it yields the plain form callers and external tools
    (e.g. the file browser, the TTS engine) expect.
    """
    if value.startswith("\\\\?\\UNC\\"):
        return "\\\\" + value[len("\\\\?\\UNC\\") :]
    if value.startswith("\\\\?\\"):
        return value[len("\\\\?\\") :]
    if value.startswith("//?/UNC/"):
        return "//" + value[len("//?/UNC/") :]
    if value.startswith("//?/"):
        return value[len("//?/") :]
    return value


def resolve_regular_path(
    value: str | os.PathLike[str],
    *,
    strict: bool = False,
) -> Path:
    r"""Resolve a path, preferring regular Win32 spelling only when safe.

    Rust's ``Path::canonicalize`` may return a verbatim path. Short existing
    paths are converted back only when both spellings identify the same object.
    Long paths retain ``\\?\`` for explicit ``MAX_PATH`` compatibility.
    """

    resolved = Path(os.fspath(value)).expanduser().resolve(strict=strict)
    if os.name == "nt":
        resolved_text = str(resolved)
        regular_text = strip_windows_verbatim_prefix(resolved_text)
        if regular_text != resolved_text and len(regular_text) < 248:
            regular = Path(regular_text)
            try:
                if resolved.exists() and regular.exists() and os.path.samefile(resolved, regular):
                    return regular.resolve(strict=strict)
            except OSError:
                pass
    return resolved
