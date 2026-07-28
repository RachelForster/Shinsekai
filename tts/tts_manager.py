"""Compatibility alias for :mod:`ai.tts.tts_manager`."""

import sys
from ai.tts import tts_manager as _module

sys.modules[__name__] = _module
