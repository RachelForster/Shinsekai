"""Compatibility alias for the canonical :mod:`sdk.path_references` module."""

from __future__ import annotations

import sys

from sdk import path_references as _implementation


sys.modules[__name__] = _implementation
