"""Compatibility alias for the canonical :mod:`sdk.process_launch` module."""

from __future__ import annotations

import sys

from sdk import process_launch as _implementation


sys.modules[__name__] = _implementation
