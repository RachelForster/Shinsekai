"""Versioned, application-owned skill resources; no backend SDK dependency."""

from __future__ import annotations

from core.paths import resource_path


BUNDLED_SKILL_VERSIONS = {
    "shinsekai-guide": "1.0.0",
    "shinsekai-diagnostics": "1.1.0",
    "shinsekai-character-creation": "1.5.0",
    "shinsekai-plugin-development": "1.0.0",
}
BUNDLED_SKILL_NAMES = tuple(BUNDLED_SKILL_VERSIONS)
BUNDLED_SKILL_REFS = tuple(
    f"skill:{name}@{version}" for name, version in BUNDLED_SKILL_VERSIONS.items()
)


def bundled_skill_paths() -> dict[str, str]:
    return {
        reference: str(resource_path(f"assets/agent/skills/{name}/SKILL.md"))
        for reference, name in zip(BUNDLED_SKILL_REFS, BUNDLED_SKILL_NAMES)
    }
