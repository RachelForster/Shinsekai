from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from ai.vision.message_content import local_image_block
from ai.vision.vision_manager import VisionManager
from core.media.chat_attachments import (
    ResolvedChatAttachment,
    chat_attachment_display_text,
    chat_file_tool_prompt,
)


DEFAULT_IMAGE_PROMPT = (
    "Describe this image accurately for another language model. Include visible text, "
    "important objects, people, layout, and details relevant to the user's request."
)


@dataclass(frozen=True, slots=True)
class PreparedChatInput:
    content: str | list[dict[str, Any]]
    display_text: str
    mode: str
    uses_file_tool: bool


VisionManagerFactory = Callable[[], VisionManager]


class ChatVisionService:
    """Prepare image attachments for the active model without provider logic in callers."""

    def __init__(self, fallback_factory: VisionManagerFactory | None = None) -> None:
        self._fallback_factory = fallback_factory or (lambda: VisionManager("moondream"))

    @staticmethod
    def supports_native_images(adapter: Any) -> bool:
        capability = getattr(adapter, "supports_native_vision", None)
        return True if capability is None else bool(capability)

    def prepare(
        self,
        text: str,
        attachments: Iterable[ResolvedChatAttachment],
        *,
        adapter: Any,
    ) -> PreparedChatInput:
        resolved = list(attachments)
        images = [attachment for attachment in resolved if attachment.kind == "image"]
        display_text = chat_attachment_display_text(text, resolved)
        file_prompt = chat_file_tool_prompt(resolved)
        user_text = str(text or "").strip() or "Please inspect the attached items and respond to the user."
        prompt_parts = [user_text]
        if file_prompt:
            prompt_parts.append(file_prompt)

        if not images:
            return PreparedChatInput(
                content="\n\n".join(prompt_parts),
                display_text=display_text,
                mode="text",
                uses_file_tool=bool(file_prompt),
            )

        if self.supports_native_images(adapter):
            content: list[dict[str, Any]] = [{"type": "text", "text": "\n\n".join(prompt_parts)}]
            content.extend(local_image_block(image) for image in images)
            return PreparedChatInput(
                content=content,
                display_text=display_text,
                mode="native",
                uses_file_tool=bool(file_prompt),
            )

        fallback = self._fallback_factory()
        descriptions: list[str] = []
        for image in images:
            description = fallback.describe(image.path.read_bytes(), DEFAULT_IMAGE_PROMPT).strip()
            descriptions.append(f"Image attachment {image.name}:\n{description or '[No description returned]'}")
        prompt_parts.append("\n\n".join(descriptions))
        return PreparedChatInput(
            content="\n\n".join(prompt_parts),
            display_text=display_text,
            mode="moondream",
            uses_file_tool=bool(file_prompt),
        )
