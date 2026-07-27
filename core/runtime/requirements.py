"""Compatibility alias for :mod:`core.runtime_env.requirements`."""

from __future__ import annotations

import sys

from core.runtime_env import requirements as _requirements

sys.modules[__name__] = _requirements
