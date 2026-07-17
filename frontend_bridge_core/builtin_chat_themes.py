"""Registry for the built-in chat UI themes.

Theme manifest content lives exclusively in ``assets/chat_ui_themes``.  This
module only keeps the stable IDs that the bridge needs for default selection
and built-in deletion protection.
"""

from __future__ import annotations


DEFAULT_BUILTIN_CHAT_THEME_ID = "windborne-adventure"
NEON_NIGHT_CITY_THEME_ID = "neon-night-city"
SAKURA_DREAM_THEME_ID = "sakura-dream"

# These themes were already built in before per-directory ownership markers
# existed, so an unmarked directory with either ID is still managed by the
# application.  ``sakura-dream`` is intentionally absent: older releases
# allowed users to install that ID, and those directories must stay user-owned.
LEGACY_UNMARKED_BUILTIN_THEME_IDS = frozenset(
    {
        DEFAULT_BUILTIN_CHAT_THEME_ID,
        NEON_NIGHT_CITY_THEME_ID,
    }
)

BUILTIN_THEME_IDS = frozenset(
    {
        DEFAULT_BUILTIN_CHAT_THEME_ID,
        NEON_NIGHT_CITY_THEME_ID,
        SAKURA_DREAM_THEME_ID,
    }
)
