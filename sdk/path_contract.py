from __future__ import annotations

import os
import re
import secrets
import stat
import sys
from pathlib import Path
from urllib.parse import SplitResult, unquote_to_bytes, urlsplit


_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_WINDOWS_DRIVE_RELATIVE_RE = re.compile(r"^[A-Za-z]:[^\\/]")
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CLOCK$", "CONIN$", "CONOUT$"}
    | {
        f"{prefix}{suffix}"
        for prefix in ("COM", "LPT")
        for suffix in (*map(str, range(1, 10)), "¹", "²", "³")
    }
)
_PATH_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f\ud800-\udfff]")
_ENCODED_PATH_SEPARATOR_RE = re.compile(r"%(?:2f|5c)", re.IGNORECASE)
_INVALID_PERCENT_ESCAPE_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_MAX_PORTABLE_COMPONENT_UTF8_BYTES = 255


def truncate_utf8_bytes(value: str, max_bytes: int) -> str:
    """Truncate text at a Unicode boundary without exceeding ``max_bytes``."""

    if max_bytes < 0:
        raise ValueError("maximum UTF-8 byte length must not be negative")
    raw = str(value)
    try:
        encoded = raw.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("value contains invalid Unicode") from exc
    if len(encoded) <= max_bytes:
        return raw
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _split_unambiguous_media_url(raw: str, *, field: str) -> SplitResult:
    """Parse one direct media URL whose authority has one browser identity."""

    if "\\" in raw:
        raise ValueError(f"{field} contains an ambiguous path separator")
    try:
        parsed = urlsplit(raw)
        # ``urlsplit`` defers invalid/non-numeric and out-of-range port
        # validation until this property is read, while the browser URL parser
        # rejects such values immediately.
        parsed.port
    except ValueError as exc:
        raise ValueError(f"{field} is malformed") from exc
    if "%" in parsed.netloc or any(character.isspace() for character in parsed.netloc):
        # A browser can decode an escaped HTTP hostname to a different textual
        # identity (for example an encoded loopback address).  Unicode may be
        # supplied directly; only authority encodings and whitespace are
        # ambiguous here.
        raise ValueError(f"{field} contains an ambiguous authority")
    return parsed


def _validate_windows_namespace_text(raw: str, *, field: str) -> None:
    r"""Allow only filesystem-shaped Windows verbatim paths.

    ``\\.\`` addresses devices, while verbatim namespaces such as
    ``\\?\GLOBALROOT`` do not name an ordinary drive/UNC file.  Treating
    either as a normal path can change ownership and containment semantics.
    """

    portable = raw.replace("\\", "/")
    if portable.startswith("//./") or portable.startswith("/??/"):
        raise ValueError(f"{field} uses a Windows device namespace")
    if not portable.startswith("//?/"):
        return
    tail = portable[len("//?/") :]
    if re.match(r"^[A-Za-z]:/", tail):
        return
    if tail.upper().startswith("UNC/"):
        unc_parts = tail[len("UNC/") :].split("/")
        if len(unc_parts) >= 2 and unc_parts[0] and unc_parts[1]:
            return
    raise ValueError(f"{field} uses an unsupported Windows verbatim namespace")


def _resolve(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _configured_environment_path(name: str) -> str | None:
    """Return an explicitly configured path without normalizing its identity.

    Presence is authoritative.  In particular, an empty current variable must
    not silently fall through to a legacy variable or a different default
    root: that would recreate the split-root behavior this module prevents.
    """

    return os.environ[name] if name in os.environ else None


def user_home_directory() -> Path:
    """Return one exact, absolute user-home identity.

    ``Path.home()`` accepts platform environment variables directly.  Validate
    the resulting text before callers append cache, download, or configuration
    paths so an invalid ``HOME``/``USERPROFILE`` cannot create a second path
    interpretation in Python while the desktop shell rejects it.
    """

    try:
        home = Path.home()
    except (KeyError, RuntimeError) as exc:
        raise ValueError("user home directory is unavailable") from exc
    return _explicit_absolute_root(home, field="user home directory")


def path_is_within(candidate: Path, root: Path) -> bool:
    """Return whether a host path is contained by the requested boundary."""

    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def safe_path_component(value: str, *, field: str = "path component") -> str:
    """Validate a portable single directory or file-name component."""

    raw = str(value or "")
    if (
        not raw
        or raw != raw.strip()
        or raw in {".", ".."}
        or _PATH_CONTROL_RE.search(raw)
        or any(character in '<>:"/\\|?*' for character in raw)
        or raw.endswith((" ", "."))
        or len(raw.encode("utf-8")) > _MAX_PORTABLE_COMPONENT_UTF8_BYTES
    ):
        raise ValueError(f"{field} is not a portable path component")
    if raw.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        raise ValueError(f"{field} is a reserved Windows device name")
    return raw


def safe_path_component_with_suffix(
    base: str,
    suffix: str,
    *,
    field: str = "path component",
) -> str:
    """Fit a derived component while preserving its semantic suffix.

    Callers commonly validate a source name and then append a collision
    counter, digest, extension, or timestamp. Reserve the suffix bytes first
    so that the final on-disk component—not only its input—satisfies the
    portable 255-byte limit.
    """

    suffix_text = str(suffix)
    try:
        suffix_size = len(suffix_text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field} contains invalid Unicode") from exc
    available = _MAX_PORTABLE_COMPONENT_UTF8_BYTES - suffix_size
    if available <= 0:
        raise ValueError(f"{field} suffix is too long")
    fitted_base = truncate_utf8_bytes(str(base), available)
    if not fitted_base:
        raise ValueError(f"{field} base is too long for its suffix")
    return safe_path_component(f"{fitted_base}{suffix_text}", field=field)


def portable_path_component_prefix(
    value: str,
    *,
    reserved_suffix_bytes: int,
    field: str = "path component prefix",
) -> str:
    """Fit a temporary-name prefix while reserving bytes added by its creator.

    ``tempfile`` accepts a prefix and then appends a private random token (and
    sometimes a caller-provided suffix). Validate the eventual component with
    an ASCII placeholder, then return only the fitted prefix.
    """

    if reserved_suffix_bytes <= 0:
        raise ValueError("reserved suffix bytes must be positive")
    placeholder = "x" * reserved_suffix_bytes
    candidate = safe_path_component_with_suffix(
        str(value),
        placeholder,
        field=field,
    )
    return candidate[:-reserved_suffix_bytes]


def _exact_relative_parts(raw: str, *, field: str) -> tuple[str, ...]:
    """Parse a portable relative path before ``Path`` can erase aliases."""

    portable = raw.replace("\\", "/")
    parts = tuple(portable.split("/"))
    if ".." in parts:
        raise PermissionError(f"{field} escapes its project boundary")
    if not parts or any(part in {"", "."} for part in parts):
        raise ValueError(f"{field} must use exact relative components")
    if parts[0].startswith("~"):
        raise ValueError(f"{field} must not use a user-home alias")
    for component in parts:
        safe_path_component(component, field=f"{field} component")
    return parts


def canonical_relative_path_with_prefix(
    value: str | os.PathLike[str],
    prefixes: tuple[tuple[str, ...], ...],
    *,
    field: str = "path",
) -> str | None:
    """Return an exact relative path with a matched prefix's canonical spelling.

    Prefix matching is intentionally case-insensitive so persisted Windows
    paths remain recognizable after migration.  Returning the caller's
    original prefix spelling would then make the same reference fail on a
    case-sensitive filesystem, so every matched component is replaced with
    the configured canonical spelling while the unclassified tail is kept
    byte-for-byte.
    """

    raw = os.fspath(value)
    if not raw or raw != raw.strip() or _PATH_CONTROL_RE.search(raw):
        raise ValueError(
            f"{field} is empty or contains surrounding whitespace or control characters"
        )
    if (
        _WINDOWS_ABSOLUTE_RE.match(raw)
        or _WINDOWS_DRIVE_RELATIVE_RE.match(raw)
        or raw.startswith(("\\\\", "//"))
        or Path(raw).is_absolute()
    ):
        raise ValueError(f"{field} must be relative")
    parts = _exact_relative_parts(raw, field=field)
    folded = tuple(part.casefold() for part in parts)
    for prefix_value in prefixes:
        prefix = tuple(str(part) for part in prefix_value)
        if not prefix:
            continue
        for component in prefix:
            safe_path_component(component, field=f"{field} prefix component")
        if folded[: len(prefix)] == tuple(part.casefold() for part in prefix):
            return "/".join((*prefix, *parts[len(prefix) :]))
    return None


def relative_path_has_prefix(
    value: str | os.PathLike[str],
    prefixes: tuple[tuple[str, ...], ...],
    *,
    field: str = "path",
) -> bool:
    """Classify an exact portable relative path without normalizing aliases."""

    return (
        canonical_relative_path_with_prefix(
            value,
            prefixes,
            field=field,
        )
        is not None
    )


def _validate_exact_absolute_text(
    raw: str,
    *,
    field: str,
    allow_non_native: bool = False,
) -> None:
    """Reject aliases and non-portable components before native resolution."""

    _validate_windows_namespace_text(raw, field=field)
    if os.name != "nt" and Path(raw).is_absolute() and "\\" in raw:
        # POSIX permits a literal backslash in a filename, while persisted
        # project paths and the Windows launcher interpret it as a separator.
        # Accepting it here would give the Python and Node/Tauri layers two
        # different identities for the same path text.
        raise ValueError(f"{field} contains a non-portable path component")
    portable = raw.replace("\\", "/")
    if portable.startswith("//?/"):
        namespace_tail = portable[len("//?/") :]
        if re.match(r"^[A-Za-z]:/", namespace_tail):
            portable = namespace_tail
        elif namespace_tail.upper().startswith("UNC/"):
            portable = f"//{namespace_tail[len('UNC/') :]}"

    if re.match(r"^[A-Za-z]:/", portable):
        components = portable[3:].split("/") if portable[3:] else []
    elif portable.startswith("//"):
        if os.name != "nt" and not allow_non_native:
            raise ValueError(f"{field} uses non-native UNC syntax")
        unc_parts = portable[2:].split("/")
        if len(unc_parts) < 2 or not unc_parts[0] or not unc_parts[1]:
            raise ValueError(f"{field} uses invalid UNC syntax")
        if len(unc_parts) == 3 and unc_parts[2] == "":
            unc_parts = unc_parts[:2]
        components = unc_parts
    elif portable.startswith("/"):
        components = portable[1:].split("/") if portable[1:] else []
    else:
        return
    if any(part in {"", ".", ".."} for part in components):
        raise ValueError(f"{field} must not contain lexical path aliases")
    for component in components:
        safe_path_component(component, field=f"{field} component")


def _expand_exact_path(raw: str, *, field: str) -> tuple[Path, bool]:
    """Expand a path while retaining enough raw text to reject aliases."""

    _validate_windows_namespace_text(raw, field=field)
    portable = raw.replace("\\", "/")
    first_component, _, home_tail = portable.partition("/")
    if first_component.startswith("~") and first_component != "~":
        raise ValueError(f"{field} must use only the current user-home alias")
    try:
        unexpanded = Path(raw)
        candidate = unexpanded.expanduser()
    except (KeyError, RuntimeError) as exc:
        raise ValueError(f"{field} contains an unknown user-home prefix") from exc
    if (
        _WINDOWS_ABSOLUTE_RE.match(raw) or raw.startswith(("\\\\", "//"))
    ) and not candidate.is_absolute():
        raise ValueError(
            f"{field} uses non-native absolute syntax that is not native to this platform"
        )

    home_alias = first_component.startswith("~")
    if home_alias:
        if home_tail and any(part in {"", ".", ".."} for part in home_tail.split("/")):
            raise ValueError(f"{field} must not contain lexical path aliases")
        if not candidate.is_absolute():
            raise ValueError(f"{field} contains an unknown user-home prefix")
        _validate_exact_absolute_text(os.fspath(candidate), field=field)
        return candidate, True

    if unexpanded.is_absolute():
        _validate_exact_absolute_text(raw, field=field)
    return candidate, candidate.is_absolute()


def validate_exact_path_text(
    value: str | os.PathLike[str],
    *,
    field: str = "path",
    allow_dot_root: bool = False,
    allow_non_native_absolute: bool = False,
) -> str:
    """Validate path identity before :class:`Path` can normalize it.

    This helper is for boundaries that must inspect or preserve the caller's
    lexical path (for example persisted cross-platform references).  Normal
    project I/O should use :func:`resolve_project_path` or one of the managed
    resolvers directly.
    """

    raw = os.fspath(value)
    if not raw or raw != raw.strip() or _PATH_CONTROL_RE.search(raw):
        raise ValueError(
            f"{field} is empty or contains surrounding whitespace or control characters"
        )
    _validate_windows_namespace_text(raw, field=field)
    if _WINDOWS_DRIVE_RELATIVE_RE.match(raw):
        raise ValueError(f"{field} uses ambiguous Windows drive-relative syntax")
    if raw == ".":
        if allow_dot_root:
            return raw
        raise ValueError(f"{field} must use exact path components")

    native_candidate = Path(raw)
    absolute_text = (
        native_candidate.is_absolute()
        or bool(_WINDOWS_ABSOLUTE_RE.match(raw))
        or raw.startswith(("\\\\", "//"))
    )
    if absolute_text:
        _validate_exact_absolute_text(
            raw,
            field=field,
            allow_non_native=allow_non_native_absolute,
        )
        if not allow_non_native_absolute:
            _expand_exact_path(raw, field=field)
        return raw

    if raw.replace("\\", "/").split("/", 1)[0].startswith("~"):
        _expand_exact_path(raw, field=field)
        return raw

    _exact_relative_parts(raw, field=field)
    return raw


def _metadata_is_link_or_reparse_point(metadata: os.stat_result) -> bool:
    """Recognize POSIX links and Windows junction/reparse-point aliases."""

    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x00000400)
    return bool(attributes & reparse_point)


def path_is_link_or_reparse_point(value: str | os.PathLike[str]) -> bool:
    """Return whether one existing leaf is a symlink, junction, or reparse point."""

    path = Path(value)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise PermissionError(f"path metadata cannot be inspected: {path}") from exc
    return _metadata_is_link_or_reparse_point(metadata)


def require_symlink_free_absolute_path(
    value: str | os.PathLike[str],
    *,
    field: str = "path",
    include_leaf: bool = True,
    allow_filesystem_root: bool = False,
) -> Path:
    """Return one exact absolute path after rejecting every existing link component."""

    raw = validate_exact_path_text(value, field=field)
    try:
        candidate = Path(raw).expanduser()
    except (KeyError, RuntimeError) as exc:
        raise ValueError(f"{field} contains an unknown user-home prefix") from exc
    if not candidate.is_absolute():
        raise ValueError(f"{field} must be an absolute path")
    if candidate == Path(candidate.anchor) and not allow_filesystem_root:
        raise PermissionError(f"{field} must not be a filesystem root")

    parts = candidate.parts
    cursor = Path(candidate.anchor)
    for index, component in enumerate(parts[1:], start=1):
        cursor = cursor / component
        if not include_leaf and index == len(parts) - 1:
            break
        try:
            metadata = cursor.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise PermissionError(f"{field} component cannot be inspected: {cursor}") from exc
        if _metadata_is_link_or_reparse_point(metadata):
            raise PermissionError(
                f"{field} contains a symbolic link component or reparse point: {cursor}"
            )
    return candidate


def require_regular_file_without_links(
    value: str | os.PathLike[str],
    *,
    field: str = "file",
) -> Path:
    """Return one exact regular file after rejecting every path alias.

    This is the execution/open-by-path counterpart to the descriptor-based
    helpers in :mod:`core.file_transactions`.  Process launchers cannot hand
    an already-open descriptor to every supported platform, so they must at
    least derive both readiness and the final command from this same strict
    path identity.
    """

    candidate = require_symlink_free_absolute_path(value, field=field)
    try:
        metadata = candidate.lstat()
    except FileNotFoundError:
        raise FileNotFoundError(candidate) from None
    if (
        _metadata_is_link_or_reparse_point(metadata)
        or not stat.S_ISREG(metadata.st_mode)
    ):
        raise FileNotFoundError(candidate)
    return candidate


def require_directory_without_links(
    value: str | os.PathLike[str],
    *,
    field: str = "directory",
    allow_filesystem_root: bool = False,
) -> Path:
    """Return one exact existing directory after rejecting every path alias."""

    candidate = require_symlink_free_absolute_path(
        value,
        field=field,
        allow_filesystem_root=allow_filesystem_root,
    )
    try:
        metadata = candidate.lstat()
    except FileNotFoundError:
        raise NotADirectoryError(candidate) from None
    if (
        _metadata_is_link_or_reparse_point(metadata)
        or not stat.S_ISDIR(metadata.st_mode)
    ):
        raise NotADirectoryError(candidate)
    return candidate


def resolve_executable_file(
    value: str | os.PathLike[str],
    *,
    field: str = "executable",
) -> Path:
    """Resolve one executable leaf alias to a stable regular-file identity.

    POSIX virtual environments commonly expose ``bin/python`` as a symbolic
    link, so rejecting every executable leaf link would break legitimate local
    runtimes.  The containing path must still be link-free; only the final
    executable component may be an alias.  Launchers receive the resolved
    regular file rather than the alias spelling, keeping discovery and process
    execution on the same identity.
    """

    candidate = require_symlink_free_absolute_path(
        value,
        field=field,
        include_leaf=False,
    )
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        raise FileNotFoundError(candidate) from None
    resolved = require_regular_file_without_links(resolved, field=field)
    if not os.access(resolved, os.X_OK):
        raise PermissionError(f"{field} is not executable: {resolved}")
    return resolved


def _explicit_absolute_root(value: str | Path, *, field: str) -> Path:
    raw = os.fspath(value)
    if not raw or raw != raw.strip() or _PATH_CONTROL_RE.search(raw):
        raise ValueError(f"{field} is empty or contains non-portable characters")
    first_component = raw.replace("\\", "/").split("/", 1)[0]
    if first_component.startswith("~"):
        raise ValueError(f"{field} must be an exact absolute path, not a user-home alias")
    try:
        candidate = Path(raw).expanduser()
    except (KeyError, RuntimeError) as exc:
        raise ValueError(f"{field} contains an unknown user-home prefix") from exc
    if not candidate.is_absolute():
        raise ValueError(f"{field} must be an absolute path")
    _validate_exact_absolute_text(raw, field=field)
    if candidate == Path(candidate.anchor):
        raise ValueError(f"{field} must not be a filesystem root")
    # Root values are ownership boundaries, not ordinary aliases.  Inspect
    # the spelling supplied by the caller before ``resolve()`` can erase a
    # symlink or Windows reparse-point component.  Missing leaf directories
    # remain valid here because project-root activation may create them later.
    require_symlink_free_absolute_path(candidate, field=field)
    resolved = _resolve(candidate)
    if resolved == Path(resolved.anchor):
        raise ValueError(f"{field} must not be a filesystem root")
    _validate_exact_absolute_text(os.fspath(resolved), field=f"resolved {field}")
    return resolved


def resolve_project_path(
    value: str | os.PathLike[str],
    *,
    root: str | Path | None = None,
) -> Path:
    """Resolve a native path under the project-root contract.

    Relative references are project-owned and therefore must remain inside the
    authoritative root after normalization and symlink resolution.  An
    explicitly absolute reference retains its external-path meaning.
    """

    project = (
        _explicit_absolute_root(root, field="project root")
        if root is not None
        else project_root()
    )
    raw = os.fspath(value)
    if not raw or raw != raw.strip() or _PATH_CONTROL_RE.search(raw):
        raise ValueError(
            "path is empty or contains surrounding whitespace or control characters"
        )
    if _WINDOWS_DRIVE_RELATIVE_RE.match(raw):
        raise ValueError("Windows drive-relative paths are ambiguous")
    candidate, explicitly_absolute = _expand_exact_path(raw, field="path")
    if not explicitly_absolute:
        if raw == ".":
            candidate = project
        else:
            try:
                parts = _exact_relative_parts(raw, field="path")
            except PermissionError as exc:
                raise PermissionError("relative path escapes project root") from exc
            candidate = project.joinpath(*parts)
    resolved = candidate.resolve(strict=False)
    if not explicitly_absolute and not path_is_within(resolved, project):
        raise PermissionError("relative path escapes project root")
    return resolved


def resolve_runtime_asset_path(
    value: str | os.PathLike[str],
    *,
    root: str | Path | None = None,
    resource_prefixes: tuple[tuple[str, ...], ...] = (("assets",),),
) -> Path:
    """Resolve an exact persisted runtime asset reference.

    Known relative resource prefixes belong to the immutable application
    roots, other relative references belong to the authoritative writable
    project root, and explicit native absolute paths retain their external
    read semantics.  A shared classifier keeps desktop and React/Tauri media
    consumers from interpreting the same stored value against different roots.
    """

    project = (
        _explicit_absolute_root(root, field="project root")
        if root is not None
        else project_root()
    )
    raw = validate_exact_path_text(value, field="runtime asset path")
    candidate = Path(raw).expanduser()
    explicitly_absolute = (
        candidate.is_absolute()
        or bool(_WINDOWS_ABSOLUTE_RE.match(raw))
        or raw.startswith(("\\\\", "//"))
        or raw.replace("\\", "/").split("/", 1)[0].startswith("~")
    )
    canonical_resource = (
        canonical_relative_path_with_prefix(
            raw,
            resource_prefixes,
            field="runtime asset path",
        )
        if not explicitly_absolute
        else None
    )
    if canonical_resource is not None:
        return resource_path(canonical_resource)
    if not explicitly_absolute:
        return resolve_managed_project_path(raw, root=project)
    try:
        candidate.relative_to(project)
    except ValueError:
        return resolve_project_path(raw, root=project)
    return resolve_managed_project_path(raw, root=project)


def resolve_runtime_asset_read_path(
    value: str | os.PathLike[str],
    *,
    root: str | Path | None = None,
    resource_prefixes: tuple[tuple[str, ...], ...] = (("assets",),),
) -> Path:
    """Resolve a runtime input while preserving and checking its exact identity.

    This is the strict counterpart to :func:`resolve_runtime_asset_path`.
    Runtime asset references still use the same application-resource,
    project-data, and explicit-external classification, but no caller-supplied
    component may be a symbolic link or Windows reparse point.  In particular,
    the path is never canonicalized before link inspection, so an alias cannot
    be laundered into an apparently safe target before a no-follow reader sees
    it.

    General model/cache consumers may intentionally rely on symlinked files
    and should continue using :func:`resolve_runtime_asset_path`.  Import,
    conversion, archive, and workflow boundaries should use this function.
    """

    project = (
        _explicit_absolute_root(root, field="project root")
        if root is not None
        else project_root()
    )
    raw = validate_exact_path_text(value, field="runtime asset input path")
    candidate, explicitly_absolute = _expand_exact_path(
        raw,
        field="runtime asset input path",
    )

    canonical_resource = (
        canonical_relative_path_with_prefix(
            raw,
            resource_prefixes,
            field="runtime asset input path",
        )
        if not explicitly_absolute
        else None
    )
    if canonical_resource is not None:
        parts = _exact_relative_parts(
            canonical_resource,
            field="runtime asset input path",
        )
        resource_roots: list[Path] = []
        for candidate_root in (source_root(), app_root()):
            if candidate_root not in resource_roots:
                resource_roots.append(candidate_root)
        for resource_root in resource_roots:
            exact_resource = require_symlink_free_absolute_path(
                resource_root.joinpath(*parts),
                field="runtime asset input path",
            )
            if exact_resource.exists():
                return exact_resource
        return require_symlink_free_absolute_path(
            resource_roots[0].joinpath(*parts),
            field="runtime asset input path",
        )

    if not explicitly_absolute:
        return resolve_managed_project_path(raw, root=project)
    try:
        candidate.relative_to(project)
    except ValueError:
        return require_symlink_free_absolute_path(
            candidate,
            field="runtime asset input path",
        )
    return resolve_managed_project_path(raw, root=project)


def validate_runtime_media_reference(
    value: str | os.PathLike[str] | None,
    *,
    allow_empty: bool = True,
) -> str:
    """Validate a local-media reference before URL encoding or ``Path`` use."""

    raw = "" if value is None else os.fspath(value)
    if not raw:
        if allow_empty:
            return ""
        raise ValueError("media path is empty")
    if raw != raw.strip() or _PATH_CONTROL_RE.search(raw):
        raise ValueError("media path contains non-portable characters")
    lowered = raw.lower()
    if lowered.startswith(("http://", "https://")):
        parsed = _split_unambiguous_media_url(raw, field="media URL")
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("media URL must be an absolute HTTP(S) URL without credentials")
        return raw
    if lowered.startswith("asset:"):
        parsed = _split_unambiguous_media_url(raw, field="asset media URL")
        if (
            parsed.scheme.lower() != "asset"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("asset media URL must be absolute and omit credentials")
        return raw
    if lowered.startswith("blob:"):
        if not raw[len("blob:") :]:
            raise ValueError("blob media URL is empty")
        return raw
    if lowered.startswith("data:"):
        if "," not in raw[len("data:") :]:
            raise ValueError("data media URL is malformed")
        return raw
    if raw.startswith("/assets/"):
        path_end = min(
            (index for index in (raw.find("?"), raw.find("#")) if index >= 0),
            default=len(raw),
        )
        encoded_path = raw[:path_end]
        if (
            _ENCODED_PATH_SEPARATOR_RE.search(encoded_path)
            or _INVALID_PERCENT_ESCAPE_RE.search(encoded_path)
        ):
            raise ValueError("application media URL contains ambiguous encoding")
        try:
            decoded_path = unquote_to_bytes(encoded_path).decode(
                "utf-8",
                errors="strict",
            )
        except UnicodeDecodeError as exc:
            raise ValueError("application media URL contains invalid UTF-8") from exc
        if not decoded_path.startswith("/assets/") or "\\" in decoded_path:
            raise ValueError("application media URL is outside application assets")
        try:
            validate_exact_path_text(
                decoded_path[1:],
                field="application media path",
            )
        except PermissionError as exc:
            raise ValueError(
                "application media URL escapes application assets"
            ) from exc
        return raw
    validate_exact_path_text(raw, field="media path")
    return raw


def runtime_media_reference_is_direct(value: str) -> bool:
    """Return whether a validated media reference is already browser-addressable."""

    raw = validate_runtime_media_reference(value)
    lowered = raw.lower()
    return (
        lowered.startswith(("http://", "https://", "blob:", "data:", "asset:"))
        or raw.startswith("/assets/")
    )


def managed_child_path(base: Path, component: str, *, field: str = "path component") -> Path:
    """Resolve one portable child while refusing symlink or traversal escapes."""

    resolved_base = require_symlink_free_absolute_path(
        base,
        field=f"{field} base",
    )
    name = safe_path_component(component, field=field)
    unresolved = resolved_base / name
    target = require_symlink_free_absolute_path(
        unresolved,
        field=field,
    )
    if target == resolved_base or not path_is_within(target, resolved_base):
        raise PermissionError(f"{field} is outside managed storage")
    return target


def resolve_managed_project_path(
    value: str | os.PathLike[str],
    *,
    root: str | Path | None = None,
) -> Path:
    """Resolve a project-owned path without following any symbolic-link component."""

    project = (
        _explicit_absolute_root(root, field="project root")
        if root is not None
        else project_root()
    )
    raw = os.fspath(value)
    if not raw or raw != raw.strip() or _PATH_CONTROL_RE.search(raw):
        raise ValueError(
            "managed path is empty or contains surrounding whitespace or control characters"
        )
    if _WINDOWS_DRIVE_RELATIVE_RE.match(raw):
        raise ValueError("Windows drive-relative managed paths are ambiguous")
    native_candidate, explicitly_absolute = _expand_exact_path(
        raw,
        field="managed path",
    )
    candidate = native_candidate
    if not explicitly_absolute:
        try:
            parts = _exact_relative_parts(raw, field="managed path")
        except PermissionError as exc:
            raise PermissionError("managed path escapes project root") from exc
        candidate = project.joinpath(*parts)
    try:
        relative = candidate.relative_to(project)
    except ValueError as exc:
        raise PermissionError(
            "managed path is outside project root (escapes project root)"
        ) from exc
    if not relative.parts or any(part in {".", ".."} for part in relative.parts):
        raise PermissionError(
            "managed path is outside project root (escapes project root)"
        )

    cursor = project
    for component in relative.parts:
        safe_path_component(component, field="managed path component")
        cursor = cursor / component
        try:
            metadata = cursor.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise PermissionError(
                f"managed path component cannot be inspected: {cursor}"
            ) from exc
        if _metadata_is_link_or_reparse_point(metadata):
            raise PermissionError(
                "managed path contains symbolic links or reparse points and escapes project root "
                f"boundary: {cursor}"
            )
    resolved = candidate.resolve(strict=False)
    if resolved == project or not path_is_within(resolved, project):
        raise PermissionError(
            "managed path is outside project root (escapes project root)"
        )
    return resolved


def resolve_project_read_path(
    value: str | os.PathLike[str],
    *,
    root: str | Path | None = None,
    allow_filesystem_root: bool = False,
) -> Path:
    """Resolve one project-relative or explicit external input without links.

    Relative inputs are project-owned and use the managed-path contract.
    Explicit absolute inputs retain their external location, but every
    existing component is inspected before callers open the file or traverse
    the directory.  Unlike :func:`resolve_project_path`, this function never
    calls ``resolve()`` on the caller's leaf and therefore cannot erase the
    evidence that the supplied path was a symlink or junction.
    """

    project = (
        _explicit_absolute_root(root, field="project root")
        if root is not None
        else project_root()
    )
    try:
        raw = validate_exact_path_text(value, field="project input path")
    except PermissionError as exc:
        raise PermissionError("project input path escapes project root") from exc
    candidate, explicitly_absolute = _expand_exact_path(
        raw,
        field="project input path",
    )
    if explicitly_absolute:
        return require_symlink_free_absolute_path(
            candidate,
            field="project input path",
            allow_filesystem_root=allow_filesystem_root,
        )
    return resolve_managed_project_path(raw, root=project)


def resolve_project_output_path(
    value: str | os.PathLike[str],
    *,
    root: str | Path | None = None,
) -> Path:
    """Resolve a writable path under the project ownership contract.

    Relative paths and absolute paths that point back into the active project
    are project-managed and may not traverse symbolic links.  Only an explicit
    absolute path outside the project retains external-output semantics.
    """

    project = (
        _explicit_absolute_root(root, field="project root")
        if root is not None
        else project_root()
    )
    raw = os.fspath(value)
    if not raw or raw != raw.strip() or _PATH_CONTROL_RE.search(raw):
        raise ValueError(
            "output path is empty or contains surrounding whitespace or control characters"
        )
    try:
        candidate = Path(raw).expanduser()
    except (KeyError, RuntimeError) as exc:
        raise ValueError("output path contains an unknown user-home prefix") from exc

    # Every relative output is project-owned by definition.  Validate its
    # unresolved components first so a linked project directory is reported
    # (and rejected) as such instead of being flattened into a generic escape
    # after ``Path.resolve()`` follows the link.
    if not candidate.is_absolute():
        return resolve_managed_project_path(value, root=project)

    resolved = resolve_project_path(value, root=project)
    try:
        candidate.relative_to(project)
        lexically_inside_project = True
    except ValueError:
        lexically_inside_project = False
    if lexically_inside_project or path_is_within(resolved, project):
        return resolve_managed_project_path(value, root=project)
    return resolved


def _managed_storage_root(project: Path, relative_root: str | os.PathLike[str]) -> tuple[Path, Path]:
    """Resolve a fixed managed root without following storage-directory links."""

    raw = os.fspath(relative_root)
    if not raw or raw != raw.strip() or _PATH_CONTROL_RE.search(raw):
        raise ValueError(
            "managed storage path is empty or contains surrounding whitespace or control characters"
        )
    raw = raw.replace("\\", "/")
    storage_relative = Path(raw)
    if storage_relative.is_absolute():
        _validate_exact_absolute_text(raw, field="managed storage path")
        try:
            storage_relative = storage_relative.relative_to(project)
        except ValueError as exc:
            raise PermissionError("managed storage is outside project root") from exc
    else:
        storage_relative = Path(
            *_exact_relative_parts(raw, field="managed storage path")
        )
    storage = resolve_managed_project_path(storage_relative, root=project)
    return storage_relative, storage


def managed_project_storage(
    relative_root: str | os.PathLike[str],
    *,
    root: str | Path | None = None,
) -> Path:
    """Return a symlink-free project-managed storage directory path."""

    project = (
        _explicit_absolute_root(root, field="project root")
        if root is not None
        else project_root()
    )
    return _managed_storage_root(project, relative_root)[1]


def managed_project_directory(
    relative_root: str | os.PathLike[str],
    component: str,
    *,
    root: str | Path | None = None,
) -> Path:
    """Return a strict child of a fixed project-managed storage directory."""

    project = (
        _explicit_absolute_root(root, field="project root")
        if root is not None
        else project_root()
    )
    _, storage = _managed_storage_root(project, relative_root)
    return managed_child_path(storage, component)


def managed_project_file(
    value: str | os.PathLike[str],
    relative_root: str | os.PathLike[str],
    *,
    root: str | Path | None = None,
) -> Path | None:
    """Resolve a persisted asset only when it belongs to known managed storage.

    Absolute paths saved by an older installation are rebased only when they
    contain the exact managed suffix (for example ``data/sprite``).  The
    returned target is always inside the current project and symbolic links
    are rejected, so callers can safely use it for deletion.
    """

    project = (
        _explicit_absolute_root(root, field="project root")
        if root is not None
        else project_root()
    )
    storage_relative, storage = _managed_storage_root(project, relative_root)

    raw = os.fspath(value)
    if (
        not raw
        or raw != raw.strip()
        or _PATH_CONTROL_RE.search(raw)
        or _WINDOWS_DRIVE_RELATIVE_RE.match(raw)
    ):
        return None
    normalized = raw.replace("\\", "/")
    candidate = Path(normalized).expanduser()
    absolute_text = (
        candidate.is_absolute()
        or bool(_WINDOWS_ABSOLUTE_RE.match(normalized))
        or normalized.startswith("//")
    )

    try:
        validate_exact_path_text(
            raw,
            field="managed asset path",
            allow_non_native_absolute=True,
        )
    except (PermissionError, ValueError):
        return None

    unresolved: Path | None = None
    if candidate.is_absolute():
        unresolved = candidate
    elif not absolute_text:
        unresolved = project / candidate

    if unresolved is not None:
        try:
            relative_to_project = unresolved.relative_to(project)
            project_owned = not any(
                part in {".", ".."} for part in relative_to_project.parts
            )
        except ValueError:
            project_owned = False
        resolved = None
        if project_owned:
            try:
                # Destructive callers need every component below the storage
                # root checked too. Resolving first would flatten an alias
                # such as ``data/sprite/A -> data/sprite/B`` and could delete
                # B's file while removing A's config entry.
                resolved = resolve_managed_project_path(unresolved, root=project)
            except (OSError, RuntimeError, ValueError):
                resolved = None
        if resolved is not None and path_is_within(resolved, storage):
            return resolved

    # An existing absolute path outside managed storage is an external asset,
    # even if its parent names happen to contain a legacy suffix such as
    # ``data/sprite`` or it resolves through an alias back into the project.
    # Legacy rebasing is only safe after the old target has disappeared;
    # destructive callers must never redirect a live external reference onto
    # a same-named current-project file.
    if unresolved is not None and os.path.lexists(unresolved):
        return None

    if not absolute_text:
        return None

    raw_parts = [part for part in normalized.split("/") if part not in {"", "."}]
    prefix_parts = [part for part in storage_relative.as_posix().split("/") if part]
    folded = [part.casefold() for part in raw_parts]
    folded_prefix = [part.casefold() for part in prefix_parts]
    for index in range(len(raw_parts) - len(prefix_parts), -1, -1):
        if folded[index : index + len(prefix_parts)] != folded_prefix:
            continue
        mapped = project.joinpath(*raw_parts[index:])
        try:
            resolved = resolve_managed_project_path(mapped, root=project)
        except (OSError, RuntimeError, ValueError):
            return None
        return resolved if path_is_within(resolved, storage) else None
    return None


def portable_project_path(
    value: str | os.PathLike[str],
    *,
    root: str | Path | None = None,
) -> str:
    """Serialize a current-project path with portable forward slashes."""

    project = (
        _explicit_absolute_root(root, field="project root")
        if root is not None
        else project_root()
    )
    raw = validate_exact_path_text(value, field="path")
    candidate = Path(raw).expanduser()

    if not candidate.is_absolute():
        managed = resolve_managed_project_path(raw, root=project)
        return managed.relative_to(project).as_posix()

    try:
        candidate.relative_to(project)
    except ValueError:
        # Keep an explicitly external alias absolute. Resolving it first could
        # turn an external symlink into a project-owned scalar reference and
        # silently change ownership when the value is loaded again.
        return Path(os.path.abspath(candidate)).as_posix()

    managed = resolve_managed_project_path(raw, root=project)
    return managed.relative_to(project).as_posix()


def prepare_and_activate_project_root(
    value: str | Path,
    *,
    field: str = "project root",
) -> Path:
    """Create, validate, and activate one identity-bound writable root.

    The legacy startup sequence validated a path and later passed its text to
    ``chdir``.  A rename between those operations could make the process cwd,
    environment root, and validated data directory refer to different
    objects.  Keep creation, the write probe, and cwd activation on one
    captured root/data identity instead.
    """

    from .file_transactions import (
        capture_directory_identity,
        open_binary_write_exclusive_without_links,
        remove_file_without_links,
        require_directory_identity,
    )

    try:
        unresolved_root = Path(os.fspath(value)).expanduser()
    except (KeyError, RuntimeError) as exc:
        raise ValueError(f"{field} contains an unknown user-home prefix") from exc
    require_symlink_free_absolute_path(unresolved_root, field=field)
    root = _explicit_absolute_root(value, field=field)
    root.mkdir(parents=True, exist_ok=True)
    data_root = root / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    require_symlink_free_absolute_path(
        data_root,
        field=f"{field} data directory",
    )
    root, root_identity = capture_directory_identity(root, field=field)
    data_root, data_root_identity = capture_directory_identity(
        data_root,
        field=f"{field} data directory",
    )
    if not path_is_within(data_root, root):
        raise PermissionError(f"{field} data directory escapes its root")

    probe = data_root / (
        f".shinsekai-write-test-{os.getpid()}-{secrets.token_hex(8)}"
    )
    probe_identity: os.stat_result | None = None
    probe_errors: list[str] = []
    try:
        with open_binary_write_exclusive_without_links(
            probe,
            expected_parent_identity=data_root_identity,
        ) as probe_file:
            probe_identity = os.fstat(probe_file.fileno())
            probe_file.write(b"ok")
            probe_file.flush()
            os.fsync(probe_file.fileno())
    except OSError as exc:
        probe_errors.append(f"write: {exc}")
    finally:
        if probe_identity is not None:
            try:
                remove_file_without_links(
                    probe,
                    expected_identity=probe_identity,
                    expected_parent_identity=data_root_identity,
                    missing_ok=True,
                )
            except (OSError, ValueError) as exc:
                probe_errors.append(f"cleanup: {exc}")
    try:
        require_directory_identity(root, root_identity, field=field)
        require_directory_identity(
            data_root,
            data_root_identity,
            field=f"{field} data directory",
        )
    except (OSError, ValueError) as exc:
        probe_errors.append(f"identity: {exc}")
    if probe_errors:
        raise PermissionError(
            f"{field} is not safely writable: {root}: {'; '.join(probe_errors)}"
        )

    _change_working_directory_to_identity(
        root,
        root_identity,
        field=field,
    )
    require_directory_identity(root, root_identity, field=field)
    require_directory_identity(
        data_root,
        data_root_identity,
        field=f"{field} data directory",
    )
    return root


def _change_working_directory_to_identity(
    root: Path,
    expected_identity: os.stat_result,
    *,
    field: str,
) -> None:
    """Change cwd to the captured directory, restoring the old cwd on error."""

    from .file_transactions import require_directory_identity

    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    can_use_directory_fd = hasattr(os, "fchdir") and hasattr(os, "O_DIRECTORY")
    previous_fd: int | None = None
    target_fd: int | None = None
    previous_path: Path | None = None
    changed = False
    try:
        if can_use_directory_fd:
            previous_fd = os.open(".", directory_flags)
            target_fd = os.open(root, directory_flags)
            target_identity = os.fstat(target_fd)
            if (
                not stat.S_ISDIR(target_identity.st_mode)
                or not os.path.samestat(expected_identity, target_identity)
            ):
                raise PermissionError(f"{field} identity changed before activation")
            require_directory_identity(root, expected_identity, field=field)
            os.fchdir(target_fd)
        else:
            previous_path = Path.cwd()
            require_directory_identity(root, expected_identity, field=field)
            os.chdir(root)
        changed = True
        cwd_identity = os.stat(".")
        if (
            not stat.S_ISDIR(cwd_identity.st_mode)
            or not os.path.samestat(expected_identity, cwd_identity)
        ):
            raise PermissionError(f"{field} cwd identity changed during activation")
        require_directory_identity(root, expected_identity, field=field)
    except BaseException:
        if changed:
            try:
                if previous_fd is not None:
                    os.fchdir(previous_fd)
                elif previous_path is not None:
                    os.chdir(previous_path)
            except OSError:
                pass
        raise
    finally:
        if target_fd is not None:
            os.close(target_fd)
        if previous_fd is not None:
            os.close(previous_fd)


def activate_project_root(default_root: str | Path) -> Path:
    """Select and activate one authoritative project root for this process.

    Legacy Python entry points used to import configuration modules before
    agreeing on a working directory.  That made reads and writes diverge when
    an executable was started from a shortcut, a different shell directory,
    or with only one of the project-root environment variables set.

    Explicit environment roots must be absolute: resolving a relative value
    against an arbitrary launcher cwd would recreate the ambiguity this helper
    is intended to remove.  The selected value is written back to both the
    current and legacy environment names before callers import data modules.
    """

    configured_value = ""
    configured_source = ""
    for name in ("SHINSEKAI_PROJECT_ROOT", "EASYAI_PROJECT_ROOT"):
        raw = _configured_environment_path(name)
        if raw is not None:
            configured_value = raw
            configured_source = name
            break

    candidate: Path | None = None
    try:
        if not configured_source and getattr(sys, "frozen", False):
            raise ValueError(
                "frozen runtimes require an explicit SHINSEKAI_PROJECT_ROOT"
            )
        selected = configured_value if configured_source else default_root
        candidate = Path(selected)
        source = configured_source or "default project root"
        root = prepare_and_activate_project_root(selected, field=source)
    except (OSError, RuntimeError, ValueError) as exc:
        source = configured_source or "default project root"
        display_candidate = candidate if candidate is not None else configured_value or default_root
        raise RuntimeError(
            f"{source} cannot be activated: {display_candidate!s}: {exc}"
        ) from exc

    resolved = str(root)
    os.environ["SHINSEKAI_PROJECT_ROOT"] = resolved
    os.environ["EASYAI_PROJECT_ROOT"] = resolved
    return root


def source_root() -> Path:
    raw = _configured_environment_path("SHINSEKAI_SOURCE_ROOT")
    if raw is not None:
        path = _explicit_absolute_root(raw, field="SHINSEKAI_SOURCE_ROOT")
        if not path.is_dir():
            raise NotADirectoryError(f"configured source root is not a directory: {path}")
        return path
    return _explicit_absolute_root(
        _resolve(Path(__file__).parent.parent),
        field="source root",
    )


def project_root() -> Path:
    """Return the authoritative writable root, independent of process cwd.

    Standard entry points always publish an explicit project-root environment
    value.  The stable app/source fallback is retained for direct library and
    developer-tool use, but an arbitrary launcher working directory is never
    promoted to application data ownership.
    """

    raw = _configured_environment_path("SHINSEKAI_PROJECT_ROOT")
    if raw is None:
        raw = _configured_environment_path("EASYAI_PROJECT_ROOT")
    if raw is not None:
        return _explicit_absolute_root(raw, field="configured project root")
    if getattr(sys, "frozen", False):
        raise RuntimeError(
            "frozen runtime requires an explicit SHINSEKAI_PROJECT_ROOT"
        )
    return app_root()


def app_root() -> Path:
    raw = _configured_environment_path("SHINSEKAI_APP_ROOT")
    if raw is not None:
        path = _explicit_absolute_root(raw, field="configured app root")
        if not path.is_dir():
            raise NotADirectoryError(f"configured app root is not a directory: {path}")
        return path
    if getattr(sys, "frozen", False):
        return _explicit_absolute_root(
            _resolve(Path(sys.executable).parent.parent),
            field="frozen app root",
        )
    return source_root()


def resource_path(path: str | Path) -> Path:
    """Resolve immutable application resources, never writable project data."""

    raw = os.fspath(path)
    if not raw or raw != raw.strip() or _PATH_CONTROL_RE.search(raw):
        raise ValueError(
            "resource path is empty or contains surrounding whitespace or control characters"
        )
    if _WINDOWS_DRIVE_RELATIVE_RE.match(raw):
        raise ValueError("Windows drive-relative resource paths are ambiguous")
    candidate, explicitly_absolute = _expand_exact_path(raw, field="resource path")
    if explicitly_absolute:
        return _resolve(candidate)
    try:
        parts = _exact_relative_parts(raw, field="resource path")
    except PermissionError as exc:
        raise PermissionError("relative resource path escapes application roots") from exc
    candidate = Path(*parts)

    for root in (source_root(), app_root()):
        resolved = _resolve(root / candidate)
        if not path_is_within(resolved, root):
            raise PermissionError("relative resource path escapes application roots")
        if resolved.exists():
            return resolved
    fallback_root = source_root()
    resolved = _resolve(fallback_root / candidate)
    if not path_is_within(resolved, fallback_root):
        raise PermissionError("relative resource path escapes application roots")
    return resolved
