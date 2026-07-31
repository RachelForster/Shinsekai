"""Compatibility alias for the canonical :mod:`sdk.archive_paths` module."""

from __future__ import annotations

import sys

from sdk import archive_paths as _implementation


sys.modules[__name__] = _implementation
