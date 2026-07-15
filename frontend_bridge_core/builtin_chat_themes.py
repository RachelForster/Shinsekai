"""Registry for the built-in chat UI themes.

Theme manifest content lives exclusively in ``assets/chat_ui_themes``.  This
module only keeps the stable IDs that the bridge needs for default selection
and built-in deletion protection.
"""

from __future__ import annotations


DEFAULT_BUILTIN_CHAT_THEME_ID = "windborne-adventure"
NEON_NIGHT_CITY_THEME_ID = "neon-night-city"

BUILTIN_THEME_IDS = frozenset(
    {
        DEFAULT_BUILTIN_CHAT_THEME_ID,
        NEON_NIGHT_CITY_THEME_ID,
    }
)
