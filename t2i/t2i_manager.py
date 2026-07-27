"""Compatibility alias for :mod:`ai.t2i.t2i_manager`."""

import sys
from ai.t2i import t2i_manager as _module

sys.modules[__name__] = _module
