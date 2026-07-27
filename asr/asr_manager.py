"""Compatibility alias for :mod:`ai.asr.asr_manager`."""

import sys
from ai.asr import asr_manager as _module

sys.modules[__name__] = _module
