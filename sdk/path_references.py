"""Lightweight, dependency-free path helpers.

Kept import-light on purpose so any module can reuse these without pulling
in the rest of the frontend bridge.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterable


_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_WINDOWS_DRIVE_PREFIX_RE = re.compile(r"^[A-Za-z]:")
_PATH_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f\ud800-\udfff]")


def portable_path_text(
    value: str | os.PathLike[str],
    *,
    field: str,
) -> str:
    """Validate path text without silently changing its identity."""

    raw = os.fspath(value)
    if not raw or raw != raw.strip() or _PATH_CONTROL_RE.search(raw):
        raise ValueError(
            f"{field} is required and must not contain surrounding whitespace "
            "or control characters"
        )
    return raw


def strip_windows_verbatim_prefix(value: str) -> str:
    r"""Drop Windows extended-length path prefixes (``\\?\`` / ``//?/``, incl. UNC).

    ``Path.resolve()`` can hand back such a prefixed path for long paths on
    Windows; stripping it yields the plain form callers and external tools
    (e.g. the file browser, the TTS engine) expect.
    """
    upper_value = value.upper()
    if upper_value.startswith("\\\\?\\UNC\\"):
        return "\\\\" + value[len("\\\\?\\UNC\\") :]
    if value.startswith("\\\\?\\"):
        tail = value[len("\\\\?\\") :]
        return tail if _WINDOWS_DRIVE_RE.match(tail) else value
    if upper_value.startswith("//?/UNC/"):
        return "//" + value[len("//?/UNC/") :]
    if value.startswith("//?/"):
        tail = value[len("//?/") :]
        return tail if _WINDOWS_DRIVE_RE.match(tail) else value
    return value


def display_path(value: str | os.PathLike[str]) -> str:
    """Return a stable, user-facing path without Windows verbatim prefixes."""

    text = strip_windows_verbatim_prefix(os.fspath(value))
    if os.name == "nt" or _WINDOWS_DRIVE_RE.match(text) or text.startswith(("\\\\", "//")):
        return text.replace("\\", "/")
    return text


def is_absolute_path_text(value: str | os.PathLike[str]) -> bool:
    """Recognize native paths plus Windows drive/UNC paths on every host.

    Recognizing Windows syntax on non-Windows hosts makes persisted path
    migration testable and prevents a moved Windows session from being
    mistaken for a project-relative path when inspected elsewhere.
    """

    text = strip_windows_verbatim_prefix(os.fspath(value))
    return (
        Path(text).is_absolute()
        or bool(_WINDOWS_DRIVE_RE.match(text))
        or text.startswith(("\\\\", "//"))
    )


def is_windows_drive_relative_path_text(value: str | os.PathLike[str]) -> bool:
    """Return whether a value uses ambiguous Windows ``C:relative`` syntax."""

    text = strip_windows_verbatim_prefix(os.fspath(value))
    return bool(_WINDOWS_DRIVE_PREFIX_RE.match(text)) and not bool(
        _WINDOWS_DRIVE_RE.match(text)
    )


def common_path_is_within(
    root: str | os.PathLike[str],
    candidate: str | os.PathLike[str],
    *,
    path_module: Any = os.path,
) -> bool:
    """Return whether *candidate* is inside *root*, including *root* itself.

    ``os.path.commonpath`` raises ``ValueError`` for paths on different
    Windows drives.  Containment is a predicate, so a different drive is a
    normal ``False`` result rather than an exception leaking into API calls.
    ``path_module`` is injectable so Windows semantics can be tested on POSIX.
    """

    try:
        root_text = strip_windows_verbatim_prefix(os.fspath(root))
        candidate_text = strip_windows_verbatim_prefix(os.fspath(candidate))
        normalized_root = path_module.normcase(path_module.normpath(root_text))
        normalized_candidate = path_module.normcase(
            path_module.normpath(candidate_text)
        )
        common = path_module.normcase(
            path_module.normpath(path_module.commonpath([normalized_root, normalized_candidate]))
        )
    except (AttributeError, OSError, TypeError, ValueError):
        return False
    return common == normalized_root


def relative_path_if_within(
    root: str | os.PathLike[str],
    candidate: str | os.PathLike[str],
    *,
    path_module: Any = os.path,
) -> str | None:
    """Return a portable relative path when *candidate* is contained by *root*."""

    if not common_path_is_within(root, candidate, path_module=path_module):
        return None
    try:
        relative = path_module.relpath(
            strip_windows_verbatim_prefix(os.fspath(candidate)),
            strip_windows_verbatim_prefix(os.fspath(root)),
        )
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    return str(relative).replace("\\", "/")


def resolved_path_is_within(candidate: Path, root: Path) -> bool:
    """Containment check for already resolved host paths."""

    return common_path_is_within(root, candidate)


def state_project_root(state: Any) -> Path:
    """Resolve the bridge's authoritative writable project root.

    Request handling must not infer this boundary from the process working
    directory: launchers and tests can change cwd independently of the
    project-root contract.
    """

    missing = object()
    state_root = getattr(state, "project_root_dir", missing)
    candidates: list[tuple[str, Any]] = []
    if state_root is not missing:
        candidates.append(("state.project_root_dir", state_root))
    if "SHINSEKAI_PROJECT_ROOT" in os.environ:
        candidates.append(
            ("SHINSEKAI_PROJECT_ROOT", os.environ["SHINSEKAI_PROJECT_ROOT"])
        )
    elif "EASYAI_PROJECT_ROOT" in os.environ:
        candidates.append(("EASYAI_PROJECT_ROOT", os.environ["EASYAI_PROJECT_ROOT"]))
    for source, candidate in candidates:
        raw = str(candidate) if candidate is not None else ""
        try:
            if raw != raw.strip() or _PATH_CONTROL_RE.search(raw):
                raise ValueError("project root contains non-portable characters")
            from sdk.path_contract import resolve_project_path

            return resolve_project_path(".", root=raw)
        except (OSError, RuntimeError, ValueError) as exc:
            # An explicitly supplied root is authoritative.  Falling through
            # to another environment variable or cwd would silently read and
            # write a second project, which is worse than a controlled error.
            raise ValueError(f"invalid project root from {source}") from exc
    try:
        from sdk.path_contract import project_root

        return project_root()
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeError("stable project root is unavailable and no project root was configured") from exc


def resolve_from_root(value: str | os.PathLike[str], root: Path) -> Path:
    """Resolve a native path while keeping relative values inside *root*.

    Absolute paths are explicit external references.  Relative paths are
    project references and may not escape through ``..`` or a symbolic link.
    """

    from sdk.path_contract import resolve_project_path

    return resolve_project_path(value, root=root)


def project_relative_path(value: str | os.PathLike[str] | Path, root: Path) -> str | None:
    """Return a portable POSIX project-relative value, or ``None`` if external."""

    try:
        base = resolve_from_root(".", root)
        candidate = resolve_from_root(value, base)
    except (OSError, RuntimeError, ValueError):
        return None
    return relative_path_if_within(base, candidate)


def normalize_project_relative_path(value: str | os.PathLike[str]) -> str | None:
    """Validate and portably encode an exact project-relative path.

    Separator conversion is needed so Windows references remain portable.
    Lexical aliases are rejected instead of collapsed: resolving ``a/../b``
    or ``a//b`` as ``b``/``a/b`` would make the stored identity disagree with
    the path selected by the caller (and can differ around symbolic links).
    """

    original = os.fspath(value)
    if original != original.strip():
        return None
    raw = strip_windows_verbatim_prefix(original).replace("\\", "/")
    if (
        not raw
        or _PATH_CONTROL_RE.search(raw)
        or is_absolute_path_text(raw)
        or is_windows_drive_relative_path_text(raw)
    ):
        return None
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    first_component = parts[0]
    if first_component.startswith("~"):
        return None
    try:
        from sdk.path_contract import safe_path_component

        for part in parts:
            safe_path_component(part, field="project-relative path component")
    except ValueError:
        return None
    return "/".join(parts)


def legacy_project_relative_path(
    value: str | os.PathLike[str],
    prefixes: Iterable[Iterable[str]],
) -> str | None:
    """Recover a managed suffix from an absolute path saved before a root move.

    Only explicitly supplied managed prefixes are recognized.  This avoids
    treating arbitrary external files as project data merely because one of
    their parent directories happens to be named ``data``.
    """

    original = display_path(value)
    if original != original.strip() or _PATH_CONTROL_RE.search(original):
        return None
    try:
        from sdk.path_contract import validate_exact_path_text

        validate_exact_path_text(
            original,
            field="legacy project path",
            allow_non_native_absolute=True,
        )
    except (PermissionError, ValueError):
        return None
    raw = original.replace("\\", "/")
    parts = [part for part in raw.split("/") if part not in {"", "."}]
    folded = [part.casefold() for part in parts]
    for prefix_value in prefixes:
        prefix = [
            str(part).strip("/\\")
            for part in prefix_value
            if str(part).strip("/\\")
        ]
        if not prefix:
            continue
        folded_prefix = [part.casefold() for part in prefix]
        for index in range(len(parts) - len(prefix), -1, -1):
            if folded[index : index + len(prefix)] != folded_prefix:
                continue
            return normalize_project_relative_path(
                "/".join((*prefix, *parts[index + len(prefix) :]))
            )
    return None


def _relative_path_with_known_prefix(
    value: str,
    prefixes: Iterable[Iterable[str]],
) -> str | None:
    """Return *value* with a matched prefix's configured canonical spelling."""

    relative = normalize_project_relative_path(value)
    if relative is None:
        return None
    parts = relative.split("/")
    folded = [part.casefold() for part in parts]
    for prefix_value in prefixes:
        prefix = [
            str(part).strip("/\\")
            for part in prefix_value
            if str(part).strip("/\\")
        ]
        if not prefix:
            continue
        folded_prefix = [part.casefold() for part in prefix]
        if folded[: len(prefix)] == folded_prefix:
            return "/".join((*prefix, *parts[len(prefix) :]))
    return None


def _current_resource_relative_path(
    candidate: Path,
    prefixes: Iterable[Iterable[str]],
) -> str | None:
    """Encode a path under a live application root as a resource reference."""

    try:
        from sdk.path_contract import (
            app_root,
            require_symlink_free_absolute_path,
            resource_path,
            source_root,
        )
    except ImportError:
        return None

    roots: list[Path] = []
    for root_getter in (source_root, app_root):
        try:
            root = root_getter()
        except (OSError, RuntimeError, ValueError):
            continue
        if root not in roots:
            roots.append(root)

    for root in roots:
        try:
            require_symlink_free_absolute_path(
                candidate,
                field="application resource reference",
            )
        except (OSError, PermissionError, RuntimeError, ValueError):
            return None
        try:
            lexical_relative = candidate.relative_to(root).as_posix()
        except ValueError:
            continue
        relative = _relative_path_with_known_prefix(lexical_relative, prefixes)
        if relative is None:
            continue
        # Relative resource resolution checks the resolved target remains
        # inside an application root, so an in-tree symbolic link cannot turn
        # an immutable reference into an arbitrary external path.
        resolved_resource = resource_path(relative).resolve(strict=False)
        try:
            resolved_candidate = candidate.resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            continue
        if resolved_resource == resolved_candidate:
            return relative
    return None


def make_path_reference(
    value: str | os.PathLike[str],
    project_root: Path,
    *,
    legacy_project_prefixes: Iterable[Iterable[str]] = (),
    resource_prefixes: Iterable[Iterable[str]] = (),
    recover_legacy_absolute: bool = True,
) -> dict[str, str] | None:
    """Encode a persisted path as resource, project-relative, or external.

    Project-owned references survive installation/data-root moves.  External
    references remain absolute and retain their distinct semantics. Immutable
    application resources keep a separate scope so writable project files can
    never shadow them after the source/data roots diverge.
    """

    raw = os.fspath(value)
    if not raw:
        return None
    if raw != raw.strip() or _PATH_CONTROL_RE.search(raw):
        raise ValueError("path contains surrounding whitespace or control characters")
    from sdk.path_contract import resolve_project_path, validate_exact_path_text

    root = resolve_project_path(".", root=project_root)

    raw = strip_windows_verbatim_prefix(raw)
    try:
        validate_exact_path_text(
            raw,
            field="path",
            allow_non_native_absolute=True,
        )
    except PermissionError as exc:
        raise ValueError("project path must not escape the project root") from exc

    first_component = raw.replace("\\", "/").split("/", 1)[0]
    if first_component.startswith("~"):
        try:
            expanded = Path(raw).expanduser()
        except (KeyError, RuntimeError) as exc:
            raise ValueError("path contains an unknown user-home prefix") from exc
        if not expanded.is_absolute():
            raise ValueError("user-home path could not be expanded absolutely")
        raw = os.fspath(expanded)

    if not is_absolute_path_text(raw):
        relative = normalize_project_relative_path(raw)
        if relative is None:
            raise ValueError("project path must not escape the project root")
        resource_relative = _relative_path_with_known_prefix(
            relative,
            resource_prefixes,
        )
        if resource_relative is not None:
            return {"scope": "resource", "path": resource_relative}
        project_relative = _relative_path_with_known_prefix(
            relative,
            legacy_project_prefixes,
        )
        return {
            "scope": "project",
            "path": project_relative or relative,
        }

    native_path = Path(raw).expanduser()
    if native_path.is_absolute():
        resource_relative = _current_resource_relative_path(
            native_path,
            resource_prefixes,
        )
        if resource_relative is not None:
            return {"scope": "resource", "path": resource_relative}
        try:
            lexical_relative = native_path.relative_to(root)
        except ValueError:
            lexical_relative = None
        if lexical_relative is not None:
            # Ownership comes from the path the caller supplied, not from a
            # resolved target. Otherwise an internal alias escaping the
            # project is mislabeled external, while an external alias pointing
            # back into it is mislabeled managed.
            from sdk.path_contract import resolve_managed_project_path

            managed = resolve_managed_project_path(raw, root=root)
            managed_relative = managed.relative_to(root).as_posix()
            canonical_managed_relative = _relative_path_with_known_prefix(
                managed_relative,
                legacy_project_prefixes,
            )
            return {
                "scope": "project",
                "path": canonical_managed_relative or managed_relative,
            }

    if recover_legacy_absolute:
        legacy_resource_relative = legacy_project_relative_path(
            raw,
            resource_prefixes,
        )
        if legacy_resource_relative is not None:
            source_exists = False
            if native_path.is_absolute():
                try:
                    source_exists = native_path.exists()
                except OSError:
                    source_exists = False
            if not source_exists:
                return {"scope": "resource", "path": legacy_resource_relative}

        legacy_relative = legacy_project_relative_path(
            raw,
            legacy_project_prefixes,
        )
        if legacy_relative is not None:
            source_exists = False
            if native_path.is_absolute():
                try:
                    source_exists = native_path.exists()
                except OSError:
                    source_exists = False
            if not source_exists:
                return {"scope": "project", "path": legacy_relative}

    return {"scope": "external", "path": display_path(raw)}


def path_reference_value(
    reference: Any,
    *,
    project_prefixes: Iterable[Iterable[str]] = (),
    resource_prefixes: Iterable[Iterable[str]] = (),
) -> str | None:
    """Validate a stored path reference and return its scalar compatibility value.

    Older reference objects can retain Windows-only case variants even after
    their scalar compatibility field has been migrated.  Optional known
    prefixes let persistence owners repair that spelling while reading the
    reference, without guessing the case of user-controlled tail components.
    """

    if not isinstance(reference, dict):
        return None
    scope = str(reference.get("scope") or "").strip().lower()
    raw = str(reference.get("path") or "")
    if raw != raw.strip() or _PATH_CONTROL_RE.search(raw):
        return None
    if scope == "project":
        relative = normalize_project_relative_path(raw)
        if relative is None:
            return None
        return (
            _relative_path_with_known_prefix(relative, project_prefixes)
            or relative
        )
    if scope == "resource":
        relative = normalize_project_relative_path(raw)
        if relative is None:
            return None
        return (
            _relative_path_with_known_prefix(relative, resource_prefixes)
            or relative
        )
    if scope == "external" and is_absolute_path_text(raw):
        displayed = display_path(raw)
        try:
            from sdk.path_contract import validate_exact_path_text

            validate_exact_path_text(
                displayed,
                field="external path",
                allow_non_native_absolute=True,
            )
        except (PermissionError, ValueError):
            return None
        return displayed
    return None


def resolve_regular_path(
    value: str | os.PathLike[str],
    *,
    strict: bool = False,
) -> Path:
    r"""Resolve a path, preferring regular Win32 spelling only when safe.

    Rust's ``Path::canonicalize`` may return a verbatim path. Short existing
    paths are converted back only when both spellings identify the same object.
    Long paths retain ``\\?\`` for explicit ``MAX_PATH`` compatibility.
    """

    resolved = Path(os.fspath(value)).expanduser().resolve(strict=strict)
    if os.name == "nt":
        resolved_text = str(resolved)
        regular_text = strip_windows_verbatim_prefix(resolved_text)
        if regular_text != resolved_text and len(regular_text) < 248:
            regular = Path(regular_text)
            try:
                if resolved.exists() and regular.exists() and os.path.samefile(resolved, regular):
                    return regular.resolve(strict=strict)
            except OSError:
                pass
    return resolved
