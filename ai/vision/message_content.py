from __future__ import annotations

import base64
import binascii
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
        # Keep a recoverable copy in persisted message history. The path remains
        # useful for display and reroll, but later model requests no longer rely
        # on the user-selected source file still existing.
        "data": base64.b64encode(attachment.path.read_bytes()).decode("ascii"),
    }


def _resolved_block_image(block: Mapping[str, Any]) -> ResolvedChatAttachment:
    return resolve_chat_attachments([{"kind": "image", "path": block.get("path")}])[0]


def _image_data(attachment: ResolvedChatAttachment) -> str:
    return base64.b64encode(attachment.path.read_bytes()).decode("ascii")


def _recover_image(block: Mapping[str, Any]) -> tuple[str, str] | None:
    embedded = str(block.get("data") or "").strip()
    media_type = str(block.get("media_type") or "image/png").strip() or "image/png"
    if embedded:
        try:
            base64.b64decode(embedded, validate=True)
        except (binascii.Error, ValueError):
            pass
        else:
            return media_type, embedded

    try:
        attachment = _resolved_block_image(block)
        return attachment.mime_type, _image_data(attachment)
    except (IndexError, OSError, ValueError):
        return None


def _historical_image_placeholder(block: Mapping[str, Any], *, unsupported: bool) -> dict[str, str]:
    name = str(block.get("name") or "image").strip() or "image"
    reason = "current model does not support image input" if unsupported else "source is no longer available"
    return {"type": "text", "text": f"[Historical image attachment omitted: {name} ({reason})]"}


def _openai_image_block(media_type: str, data: str) -> dict[str, Any]:
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:{media_type};base64,{data}",
        },
    }


def _flatten_text_blocks(content: list[Any]) -> str:
    rows: list[str] = []
    for block in content:
        if isinstance(block, Mapping) and block.get("type") == "text":
            text = str(block.get("text") or "").strip()
            if text:
                rows.append(text)
        elif isinstance(block, str) and block.strip():
            rows.append(block.strip())
    return "\n\n".join(rows)


def normalize_openai_messages(
    messages: list[dict[str, Any]],
    *,
    supports_native_vision: bool = False,
) -> list[dict[str, Any]]:
    normalized = copy.deepcopy(messages)
    for message in normalized:
        # These fields are application-only replay/display metadata and are not
        # part of the OpenAI-compatible message schema.
        message.pop("display_content", None)
        message.pop("input_text", None)
        message.pop("attachments", None)
        content = message.get("content")
        if not isinstance(content, list):
            continue
        next_content: list[Any] = []
        had_local_image = False
        for block in content:
            if isinstance(block, Mapping) and block.get("type") == LOCAL_IMAGE_BLOCK_TYPE:
                had_local_image = True
                if not supports_native_vision:
                    next_content.append(_historical_image_placeholder(block, unsupported=True))
                else:
                    recovered = _recover_image(block)
                    if recovered is not None:
                        next_content.append(_openai_image_block(*recovered))
                    else:
                        next_content.append(_historical_image_placeholder(block, unsupported=False))
                continue
            next_content.append(block)
        # Text-only OpenAI-compatible providers commonly reject multimodal
        # content arrays altogether, even when those arrays contain only text.
        message["content"] = (
            _flatten_text_blocks(next_content)
            if had_local_image and not supports_native_vision
            else next_content
        )
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
            recovered = _recover_image(block)
            if recovered is None:
                normalized.append(_historical_image_placeholder(block, unsupported=False))
            else:
                media_type, data = recovered
                normalized.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": data,
                        },
                    }
                )
            continue
        if block.get("type") == "text":
            text = str(block.get("text") or "").strip()
            if text:
                normalized.append({"type": "text", "text": text})
    return normalized
