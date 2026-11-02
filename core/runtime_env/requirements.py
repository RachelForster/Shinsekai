"""Version-aware checks for installed Python runtime requirements."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import re
from dataclasses import dataclass
from typing import Mapping

try:
    from packaging.requirements import InvalidRequirement, Requirement
    from packaging.version import InvalidVersion
except Exception:  # pragma: no cover - minimal runtimes are repaired first.
    InvalidRequirement = ValueError  # type: ignore[assignment]
    InvalidVersion = ValueError  # type: ignore[assignment]
    Requirement = None  # type: ignore[assignment]


@dataclass(frozen=True)
class RequirementCheck:
    requirement: str
    name: str
    installed_version: str | None
    applies: bool
    satisfied: bool

    @property
    def issue(self) -> str:
        if self.satisfied:
            return ""
        if self.installed_version is None:
            return f"{self.name} is not installed (requires {self.requirement})"
        return (
            f"{self.name} {self.installed_version} does not satisfy "
            f"{self.requirement}"
        )


def canonical_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", str(name or "")).strip("-").lower()


def requirement_name(requirement_text: str) -> str:
    requirement_text = str(requirement_text or "").strip()
    if Requirement is not None:
        try:
            return Requirement(requirement_text).name
        except InvalidRequirement:
            pass
    name = re.split(
        r"\s*(?:===|==|~=|!=|<=|>=|<|>|@)\s*",
        requirement_text,
        maxsplit=1,
    )[0]
    return name.split("[", 1)[0].strip()


def installed_distribution_version(
    name: str,
    installed_versions: Mapping[str, str] | None = None,
) -> str | None:
    if installed_versions is not None:
        canonical_name = canonical_distribution_name(name)
        return next(
            (
                version
                for distribution_name, version in installed_versions.items()
                if canonical_distribution_name(distribution_name) == canonical_name
            ),
            None,
        )
    try:
        return importlib_metadata.version(name)
    except importlib_metadata.PackageNotFoundError:
        return None


def check_requirement(
    requirement_text: str,
    installed_versions: Mapping[str, str] | None = None,
) -> RequirementCheck:
    requirement_text = str(requirement_text or "").strip()
    if Requirement is None:
        name = requirement_name(requirement_text)
        installed = installed_distribution_version(name, installed_versions)
        return RequirementCheck(
            requirement=requirement_text,
            name=name,
            installed_version=installed,
            applies=True,
            satisfied=bool(name and installed is not None),
        )

    try:
        requirement = Requirement(requirement_text)
    except InvalidRequirement:
        name = requirement_name(requirement_text)
        installed = installed_distribution_version(name, installed_versions)
        return RequirementCheck(
            requirement=requirement_text,
            name=name,
            installed_version=installed,
            applies=True,
            satisfied=bool(name and installed is not None),
        )

    applies = requirement.marker is None or requirement.marker.evaluate()
    if not applies:
        return RequirementCheck(
            requirement=requirement_text,
            name=requirement.name,
            installed_version=None,
            applies=False,
            satisfied=True,
        )

    installed = installed_distribution_version(requirement.name, installed_versions)
    satisfied = installed is not None
    if satisfied and requirement.specifier:
        try:
            satisfied = requirement.specifier.contains(installed, prereleases=True)
        except InvalidVersion:
            satisfied = False
    return RequirementCheck(
        requirement=requirement_text,
        name=requirement.name,
        installed_version=installed,
        applies=True,
        satisfied=satisfied,
    )


def unsatisfied_requirements(
    requirement_texts: tuple[str, ...] | list[str],
    installed_versions: Mapping[str, str] | None = None,
) -> tuple[RequirementCheck, ...]:
    return tuple(
        check
        for requirement_text in requirement_texts
        if (check := check_requirement(requirement_text, installed_versions)).applies
        and not check.satisfied
    )
