from __future__ import annotations

import base64
import copy
from collections.abc import Mapping
from typing import Any

from core.media.chat_attachments import ResolvedChatAttachment, resolve_chat_attachments


LOCAL_IMAGE_BLOCK_TYPE = "local_image"


def local_image_block(attachment: ResolvedChatAttachment) -> dict[str, Any]:
    if attachment.kind != "image":
        raise ValueError("Only image attachments can become image content blocks")
    return {
        "type": LOCAL_IMAGE_BLOCK_TYPE,
        "media_type": attachment.mime_type,
        "name": attachment.name,
        "path": str(attachment.path),
    }


def _resolved_block_image(block: Mapping[str, Any]) -> ResolvedChatAttachment:
    return resolve_chat_attachments([{"kind": "image", "path": block.get("path")}])[0]


def _image_data(attachment: ResolvedChatAttachment) -> str:
    return base64.b64encode(attachment.path.read_bytes()).decode("ascii")


def _openai_image_block(block: Mapping[str, Any]) -> dict[str, Any]:
    attachment = _resolved_block_image(block)
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:{attachment.mime_type};base64,{_image_data(attachment)}",
        },
    }


def normalize_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = copy.deepcopy(messages)
    for message in normalized:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        next_content: list[Any] = []
        for block in content:
            if isinstance(block, Mapping) and block.get("type") == LOCAL_IMAGE_BLOCK_TYPE:
                next_content.append(_openai_image_block(block))
            else:
                next_content.append(block)
        message["content"] = next_content
    return normalized


def normalize_anthropic_user_content(content: Any) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or "")
    normalized: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, Mapping):
            text = str(block or "").strip()
            if text:
                normalized.append({"type": "text", "text": text})
            continue
        if block.get("type") == LOCAL_IMAGE_BLOCK_TYPE:
            attachment = _resolved_block_image(block)
            normalized.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": attachment.mime_type,
                        "data": _image_data(attachment),
                    },
                }
            )
            continue
        if block.get("type") == "text":
            text = str(block.get("text") or "").strip()
            if text:
                normalized.append({"type": "text", "text": text})
    return normalized
