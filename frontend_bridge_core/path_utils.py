"""Lightweight, dependency-free path helpers.

Kept import-light on purpose so any module can reuse these without pulling
in the rest of the frontend bridge.
"""

from __future__ import annotations


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
