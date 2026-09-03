"""Canonical character selection shared by template entry points."""

import logging
from typing import Any

from config.config_manager import character_name_key

logger = logging.getLogger(__name__)


def resolve_chat_template_characters(
    selected_characters: Any,
    manager: Any,
) -> list[tuple[str, Any]]:
    """Resolve and canonicalize characters while preserving selection order."""
    requested_names: list[str] = []
    requested_name_keys: set[str] = set()
    for item in selected_characters or []:
        requested_name = str(item).strip()
        if not requested_name:
            continue
        requested_key = character_name_key(requested_name)
        if requested_key in requested_name_keys:
            continue
        requested_name_keys.add(requested_key)
        requested_names.append(requested_name)
    resolved_characters: list[tuple[str, Any]] = []
    missing_characters: list[str] = []
    resolved_name_keys: set[str] = set()
    for requested_name in requested_names:
        character = manager.get_character_by_name(requested_name)
        if character is None:
            missing_characters.append(requested_name)
            continue
        canonical_name = str(getattr(character, "name", "") or requested_name).strip()
        canonical_key = character_name_key(canonical_name)
        if canonical_key in resolved_name_keys:
            continue
        resolved_name_keys.add(canonical_key)
        resolved_characters.append((canonical_name, character))

    if missing_characters:
        logger.warning(
            "Skipping missing characters during template generation: %s",
            ", ".join(missing_characters),
            extra={
                "event": "template.characters.missing",
                "missing_characters": missing_characters,
            },
        )
    return resolved_characters
