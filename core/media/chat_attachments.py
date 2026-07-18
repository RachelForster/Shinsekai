from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


MAX_CHAT_ATTACHMENTS = 8
MAX_CHAT_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_CHAT_IMAGE_BYTES = 20 * 1024 * 1024
MAX_CHAT_ATTACHMENTS_TOTAL_BYTES = 50 * 1024 * 1024
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
    kind: str
    mime_type: str
    name: str
    path: Path
    size: int

    def to_payload(self) -> dict[str, str | int]:
        return {
            "kind": self.kind,
            "mimeType": self.mime_type,
            "name": self.name,
            "path": str(self.path),
            "size": self.size,
        }


def _reject_control_characters(value: str, *, field: str) -> str:
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field} contains control characters")
    return value


def _attachment_kind(value: Any) -> str:
    kind = str(value or "file").strip().lower()
    if kind not in {"file", "image"}:
        raise ValueError(f"Unsupported chat attachment kind: {kind}")
    return kind


def _resolve_selected_file(raw_path: Any) -> Path:
    value = _reject_control_characters(str(raw_path or "").strip(), field="attachment path")
    if not value:
        raise ValueError("Attachment path cannot be empty")
    if len(value) > 4096:
        raise ValueError("Attachment path is too long")
    selected = Path(value).expanduser()
    if not selected.is_absolute():
        raise ValueError("Attachment path must be absolute")
    # This path is intentionally user-selected and read-only. Resolve it once,
    # then validate the concrete target before any bytes are read.
    resolved = selected.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"Attachment is not a file: {resolved}")
    return resolved


def resolve_chat_attachments(raw_items: Iterable[Mapping[str, Any]] | None) -> list[ResolvedChatAttachment]:
    items = list(raw_items or [])
    if len(items) > MAX_CHAT_ATTACHMENTS:
        raise ValueError(f"A message can include at most {MAX_CHAT_ATTACHMENTS} attachments")

    resolved_items: list[ResolvedChatAttachment] = []
    seen_paths: set[str] = set()
    total_size = 0
    for item in items:
        if not isinstance(item, Mapping):
            raise ValueError("Chat attachments must be objects")
        kind = _attachment_kind(item.get("kind"))
        path = _resolve_selected_file(item.get("path"))
        identity = os.path.normcase(str(path))
        if identity in seen_paths:
            continue
        seen_paths.add(identity)

        name = _reject_control_characters(path.name, field="attachment name")
        size = path.stat().st_size
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
                kind=kind,
                mime_type=mime_type,
                name=name,
                path=path,
                size=size,
            )
        )
    return resolved_items


def chat_attachment_display_text(text: str, attachments: Iterable[ResolvedChatAttachment]) -> str:
    value = str(text or "").strip()
    labels = [f"[{attachment.kind}: {attachment.name}]" for attachment in attachments]
    return "\n".join(part for part in [value, " ".join(labels)] if part).strip()


def chat_file_tool_prompt(attachments: Iterable[ResolvedChatAttachment]) -> str:
    files = [attachment for attachment in attachments if attachment.kind == "file"]
    if not files:
        return ""
    rows = [
        "The user attached local files. Use the file_read tool when their contents are needed:",
        *[f"- {attachment.name}: {attachment.path}" for attachment in files],
    ]
    return "\n".join(rows)
