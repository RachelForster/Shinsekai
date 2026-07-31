"""Compatibility alias for the canonical :mod:`sdk.file_transactions` module."""

from __future__ import annotations

import sys

from sdk import file_transactions as _implementation


sys.modules[__name__] = _implementation
