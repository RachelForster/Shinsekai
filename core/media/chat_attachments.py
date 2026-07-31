from __future__ import annotations

import mimetypes
import os
import re
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from core.file_transactions import (
    copy_file_exclusive_with_identity,
    open_binary_read_without_links,
    remove_directory_without_links,
)
from core.paths import (
    managed_project_storage,
    path_is_within,
    require_directory_without_links,
    require_symlink_free_absolute_path,
    resolve_project_path,
    resolve_project_read_path,
    safe_path_component,
    validate_exact_path_text,
)


MAX_CHAT_ATTACHMENTS = 8
MAX_CHAT_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_CHAT_IMAGE_BYTES = 20 * 1024 * 1024
MAX_CHAT_ATTACHMENTS_TOTAL_BYTES = 50 * 1024 * 1024
CHAT_ATTACHMENTS_ROOT_ENV = "SHINSEKAI_CHAT_ATTACHMENTS_ROOT"
SUPPORTED_CHAT_IMAGE_MIME_TYPES = frozenset(
    {
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
    }
)


@dataclass(frozen=True, slots=True)
class ResolvedChatAttachment:
    identity: os.stat_result
    kind: str
    mime_type: str
    name: str
    path: Path
    size: int
    reference: str = ""

    def to_payload(self) -> dict[str, str | int]:
        return {
            "kind": self.kind,
            "mimeType": self.mime_type,
            "name": self.name,
            "path": self.reference or str(self.path),
            "size": self.size,
        }


def _reject_control_characters(value: str, *, field: str) -> str:
    if any(
        ord(character) < 32
        or ord(character) == 127
        or 0xD800 <= ord(character) <= 0xDFFF
        for character in value
    ):
        raise ValueError(f"{field} contains non-portable characters")
    return value


def _attachment_kind(value: Any) -> str:
    kind = str(value or "file").strip().lower()
    if kind not in {"file", "image"}:
        raise ValueError(f"Unsupported chat attachment kind: {kind}")
    return kind


@lru_cache(maxsize=1)
def _chat_attachment_root() -> Path:
    root_value = os.environ.get(CHAT_ATTACHMENTS_ROOT_ENV, "")
    if not root_value:
        raise ValueError(f"{CHAT_ATTACHMENTS_ROOT_ENV} must be configured")
    if root_value != root_value.strip():
        raise ValueError(f"{CHAT_ATTACHMENTS_ROOT_ENV} contains non-portable characters")
    _reject_control_characters(root_value, field=CHAT_ATTACHMENTS_ROOT_ENV)
    validate_exact_path_text(root_value, field=CHAT_ATTACHMENTS_ROOT_ENV)
    unresolved = Path(root_value)
    if not unresolved.is_absolute():
        raise ValueError(f"{CHAT_ATTACHMENTS_ROOT_ENV} must be an absolute path")
    root = require_symlink_free_absolute_path(
        unresolved,
        field=CHAT_ATTACHMENTS_ROOT_ENV,
    )
    if not root.is_dir():
        raise ValueError(f"{CHAT_ATTACHMENTS_ROOT_ENV} must point to an existing directory")
    return root


def _explicit_chat_attachment_root(
    value: str | os.PathLike[str],
) -> Path:
    raw = os.fspath(value)
    if raw != raw.strip():
        raise ValueError("attachment root contains non-portable characters")
    _reject_control_characters(raw, field="attachment root")
    validate_exact_path_text(raw, field="attachment root")
    unresolved = Path(raw)
    if not unresolved.is_absolute():
        raise ValueError("attachment root must be an absolute path")
    root = require_symlink_free_absolute_path(
        unresolved,
        field="attachment root",
    )
    if not root.is_dir():
        raise ValueError("attachment root must point to an existing directory")
    return root


def _resolve_selected_file(
    raw_path: Any,
    *,
    root: Path,
) -> tuple[Path, os.stat_result, str]:
    value = str(raw_path or "")
    if not value:
        raise ValueError("Attachment path cannot be empty")
    if value != value.strip():
        raise ValueError("Attachment path contains surrounding whitespace")
    value = _reject_control_characters(value, field="attachment path")
    if len(value) > 4096:
        raise ValueError("Attachment path is too long")
    if "\x00" in value:
        raise ValueError("Attachment path contains null bytes")
    if any(part in {".", ".."} for part in value.replace("\\", "/").split("/")):
        raise ValueError("Attachment path contains invalid traversal segments")
    validate_exact_path_text(value, field="attachment path")
    selected = resolve_project_read_path(value, root=root)
    if selected != root and not path_is_within(selected, root):
        # Pre-contract histories stored the absolute staging path. Recover
        # only the exact application-owned shape and only when its matching
        # file exists under the current attachment root. Arbitrary missing
        # external paths are never guessed into the sandbox.
        portable_parts = value.replace("\\", "/").split("/")
        folded = [part.casefold() for part in portable_parts]
        marker = ["data", "chat_attachments"]
        migrated_reference = None
        for index in range(len(folded) - len(marker), -1, -1):
            if folded[index : index + len(marker)] != marker:
                continue
            tail = portable_parts[index + len(marker) :]
            if (
                len(tail) == 2
                and re.fullmatch(r"[0-9a-fA-F]{32}", tail[0])
            ):
                candidate = resolve_project_read_path(
                    "/".join(tail),
                    root=root,
                )
                if candidate.is_file():
                    selected = candidate
                    migrated_reference = candidate.relative_to(root).as_posix()
            break
        if migrated_reference is None:
            raise ValueError("Attachment path is outside the allowed directory")
    if selected == root or not path_is_within(selected, root):
        raise ValueError("Attachment path is outside the allowed directory")
    if not selected.is_file():
        raise ValueError(f"Attachment is not a file: {selected}")
    with open_binary_read_without_links(selected) as source:
        identity = os.fstat(source.fileno())
    return selected, identity, selected.relative_to(root).as_posix()


def resolve_chat_attachments(
    raw_items: Iterable[Mapping[str, Any]] | None,
    *,
    root: str | os.PathLike[str] | None = None,
) -> list[ResolvedChatAttachment]:
    """Resolve attachment references against one explicit sandbox root.

    New payloads use portable paths relative to this root so chat history
    remains valid when the project is moved. Absolute paths from older
    histories remain accepted only when they identify the same sandbox.
    """

    items = list(raw_items or [])
    if len(items) > MAX_CHAT_ATTACHMENTS:
        raise ValueError(f"A message can include at most {MAX_CHAT_ATTACHMENTS} attachments")
    if not items:
        return []

    attachment_root = (
        _chat_attachment_root()
        if root is None
        else _explicit_chat_attachment_root(root)
    )

    resolved_items: list[ResolvedChatAttachment] = []
    seen_paths: set[str] = set()
    total_size = 0
    for item in items:
        if not isinstance(item, Mapping):
            raise ValueError("Chat attachments must be objects")
        kind = _attachment_kind(item.get("kind"))
        path, file_identity, reference = _resolve_selected_file(
            item.get("path"),
            root=attachment_root,
        )
        path_identity = os.path.normcase(str(path))
        if path_identity in seen_paths:
            continue
        seen_paths.add(path_identity)

        name = _reject_control_characters(path.name, field="attachment name")
        size = file_identity.st_size
        limit = MAX_CHAT_IMAGE_BYTES if kind == "image" else MAX_CHAT_ATTACHMENT_BYTES
        if size > limit:
            raise ValueError(f"Attachment is too large: {name}")
        total_size += size
        if total_size > MAX_CHAT_ATTACHMENTS_TOTAL_BYTES:
            raise ValueError("Chat attachments exceed the total size limit")

        mime_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if kind == "image" and mime_type not in SUPPORTED_CHAT_IMAGE_MIME_TYPES:
            raise ValueError(f"Unsupported chat image type: {name}")
        resolved_items.append(
            ResolvedChatAttachment(
                identity=file_identity,
                kind=kind,
                mime_type=mime_type,
                name=name,
                path=path,
                size=size,
                reference=reference,
            )
        )
    return resolved_items


def chat_attachment_display_text(text: str, attachments: Iterable[ResolvedChatAttachment]) -> str:
    value = str(text or "").strip()
    labels = [f"[{attachment.kind}: {attachment.name}]" for attachment in attachments]
    return "\n".join(part for part in [value, " ".join(labels)] if part).strip()


CHAT_ATTACHMENT_STAGE_SUBDIR = ("data", "chat_attachments")


@dataclass(frozen=True, slots=True)
class _UploadedAttachmentCandidate:
    identity: os.stat_result
    source: Path
    kind: str
    mime_type: str
    name: str
    size: int


def stage_uploaded_chat_attachments(
    source_paths: Iterable[Any],
    *,
    project_root: str | os.PathLike[str] | None = None,
) -> list[dict[str, str | int]]:
    """Copy uploaded files into the attachment root and return payloads.

    Files dropped or uploaded from the browser arrive in a temporary directory
    that lives outside the allowed attachment root, so sending them directly is
    rejected by :func:`resolve_chat_attachments`. This copies each file under
    ``<root>/data/chat_attachments/<uuid>/<name>`` and returns a portable path
    relative to that attachment sandbox. Supported images are tagged
    ``kind="image"``; every other file is tagged ``kind="file"``.
    """
    sources: list[Path] = []
    for value in source_paths:
        raw = validate_exact_path_text(value, field="uploaded attachment path")
        source = Path(raw)
        if not source.is_absolute():
            raise ValueError("Uploaded attachment path must be absolute")
        try:
            source = require_symlink_free_absolute_path(
                source,
                field="uploaded attachment",
            )
        except PermissionError as exc:
            raise PermissionError(
                "Uploaded attachment must not use a symbolic link or reparse point"
            ) from exc
        sources.append(source)
    if not sources:
        raise ValueError("No attachments were uploaded")
    if len(sources) > MAX_CHAT_ATTACHMENTS:
        raise ValueError(f"A message can include at most {MAX_CHAT_ATTACHMENTS} attachments")

    candidates: list[_UploadedAttachmentCandidate] = []
    total_size = 0
    for source in sources:
        if not source.is_file():
            raise ValueError(f"Uploaded attachment is not a file: {source.name}")
        with open_binary_read_without_links(source) as source_file:
            source_identity = os.fstat(source_file.fileno())
        name = safe_path_component(
            _reject_control_characters(source.name, field="attachment name"),
            field="attachment name",
        )
        mime_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        is_image = mime_type in SUPPORTED_CHAT_IMAGE_MIME_TYPES
        kind = "image" if is_image else "file"
        size = source_identity.st_size
        limit = MAX_CHAT_IMAGE_BYTES if is_image else MAX_CHAT_ATTACHMENT_BYTES
        if size > limit:
            raise ValueError(f"Attachment is too large: {name}")
        total_size += size
        if total_size > MAX_CHAT_ATTACHMENTS_TOTAL_BYTES:
            raise ValueError("Chat attachments exceed the total size limit")
        candidates.append(
            _UploadedAttachmentCandidate(
                identity=source_identity,
                source=source,
                kind=kind,
                mime_type=mime_type,
                name=name,
                size=size,
            )
        )

    if project_root is None:
        root = _chat_attachment_root()
    else:
        root = resolve_project_path(".", root=project_root)
        if not root.is_dir():
            raise NotADirectoryError(root)
    stage_root = managed_project_storage(
        Path(*CHAT_ATTACHMENT_STAGE_SUBDIR),
        root=root,
    )
    stage_root.mkdir(parents=True, exist_ok=True)
    stage_root = require_directory_without_links(
        stage_root,
        field="chat attachment staging root",
    )
    created_dirs: list[tuple[Path, os.stat_result]] = []
    results: list[dict[str, str | int]] = []
    copied_total_size = 0
    try:
        for candidate in candidates:
            dest_dir = stage_root / uuid.uuid4().hex
            dest_dir.mkdir(parents=True, exist_ok=False)
            dest_dir = require_directory_without_links(
                dest_dir,
                field="chat attachment staging directory",
            )
            created_dirs.append((dest_dir, dest_dir.lstat()))
            dest, destination_identity = copy_file_exclusive_with_identity(
                candidate.source,
                dest_dir,
                candidate.name,
                field="attachment filename",
                expected_source_identity=candidate.identity,
            )
            copied_size = destination_identity.st_size
            copied_limit = (
                MAX_CHAT_IMAGE_BYTES
                if candidate.kind == "image"
                else MAX_CHAT_ATTACHMENT_BYTES
            )
            if copied_size > copied_limit:
                raise ValueError(f"Attachment is too large: {candidate.name}")
            copied_total_size += copied_size
            if copied_total_size > MAX_CHAT_ATTACHMENTS_TOTAL_BYTES:
                raise ValueError("Chat attachments exceed the total size limit")
            results.append(
                {
                    "kind": candidate.kind,
                    "mimeType": candidate.mime_type,
                    "name": candidate.name,
                    "path": dest.relative_to(stage_root).as_posix(),
                    "size": copied_size,
                }
            )
    except Exception:
        for created_dir, identity in reversed(created_dirs):
            try:
                remove_directory_without_links(
                    created_dir,
                    expected_identity=identity,
                )
            except (OSError, ValueError):
                pass
        raise

    return results
