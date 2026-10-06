"""Versioned, application-owned skill resources; no backend SDK dependency."""

from __future__ import annotations

from core.paths import resource_path


BUNDLED_SKILL_NAMES = (
    "shinsekai-guide",
    "shinsekai-diagnostics",
    "shinsekai-character-creation",
    "shinsekai-plugin-development",
)
BUNDLED_SKILL_VERSION = "1.0.0"
BUNDLED_SKILL_REFS = tuple(
    f"skill:{name}@{BUNDLED_SKILL_VERSION}" for name in BUNDLED_SKILL_NAMES
)


def bundled_skill_paths() -> dict[str, str]:
    return {
        reference: str(resource_path(f"assets/agent/skills/{name}/SKILL.md"))
        for reference, name in zip(BUNDLED_SKILL_REFS, BUNDLED_SKILL_NAMES)
    }
