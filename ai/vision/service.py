from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from ai.vision.fallback_registry import active_preferred_fallback
from ai.vision.message_content import local_image_block
from ai.vision.moondream_adapter import MoondreamPluginUnavailable, installed_moondream_directory
from ai.vision.vision_manager import VisionManager
from core.media.chat_attachments import (
    ResolvedChatAttachment,
    chat_attachment_display_text,
)
from llm.tools.file_tools import file_read


DEFAULT_IMAGE_PROMPT = (
    "Describe this image accurately for another language model. Include visible text, "
    "important objects, people, layout, and details relevant to the user's request."
)


@dataclass(frozen=True, slots=True)
class PreparedChatInput:
    content: str | list[dict[str, Any]]
    display_text: str
    mode: str


VisionManagerFactory = Callable[[], VisionManager]
FileReader = Callable[[str], Mapping[str, Any]]
FallbackAvailability = Callable[[], bool]


def _default_fallback_factory() -> VisionManager:
    """Prefer a plugin-registered vision fallback, else the local Moondream plugin."""
    preferred = active_preferred_fallback()
    if preferred is not None:
        return preferred.factory()
    return VisionManager("moondream")


def _default_fallback_available() -> bool:
    """Report whether any built-in fallback (plugin-preferred or Moondream) can run."""
    if active_preferred_fallback() is not None:
        return True
    return installed_moondream_directory() is not None


class ChatVisionService:
    """Prepare image attachments for the active model without provider logic in callers."""

    def __init__(
        self,
        fallback_factory: VisionManagerFactory | None = None,
        *,
        fallback_available: FallbackAvailability | None = None,
        file_reader: FileReader | None = None,
    ) -> None:
        self._fallback_factory = fallback_factory or _default_fallback_factory
        self._fallback_available = fallback_available or (
            _default_fallback_available
            if fallback_factory is None
            else (lambda: True)
        )
        self._file_reader = file_reader or file_read

    @staticmethod
    def supports_native_images(adapter: Any) -> bool:
        capability = getattr(adapter, "supports_native_vision", None)
        return bool(capability)

    @staticmethod
    def _fallback_unavailable_input(
        prompt_parts: list[str],
        images: list[ResolvedChatAttachment],
        display_text: str,
    ) -> PreparedChatInput:
        names = ", ".join(image.name for image in images)
        prompt_parts.append(
            "Image attachments could not be inspected. The current language model does not support "
            "native image input, and no vision fallback is currently available. "
            f"Uninspected attachments: {names}. Explain this to the user and offer these options: "
            "install or enable the local Moondream plugin (本地识图), "
            "enable and configure the Cloud Vision plugin for a cloud vision API (云端识图), "
            "switch to a vision-capable model, or describe the images in text."
        )
        return PreparedChatInput(
            content="\n\n".join(prompt_parts),
            display_text=display_text,
            mode="unavailable",
        )

    def _read_file_attachments(self, attachments: Iterable[ResolvedChatAttachment]) -> str:
        files = [attachment for attachment in attachments if attachment.kind == "file"]
        if not files:
            return ""

        rows = ["Local file attachments (already read by the application):"]
        for attachment in files:
            result = self._file_reader(str(attachment.path))
            rows.append(f"--- BEGIN ATTACHED FILE: {attachment.name} ---")
            if result.get("error"):
                rows.append(f"[Unable to read file: {result['error']}]")
            else:
                rows.append(str(result.get("content") or "[File is empty]"))
                if result.get("truncated"):
                    rows.append("[File content was truncated by the local reader.]")
            rows.append(f"--- END ATTACHED FILE: {attachment.name} ---")
        return "\n".join(rows)

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
        file_contents = self._read_file_attachments(resolved)
        user_text = str(text or "").strip() or "Please inspect the attached items and respond to the user."
        prompt_parts = [user_text]
        if file_contents:
            prompt_parts.append(file_contents)

        if not images:
            return PreparedChatInput(
                content="\n\n".join(prompt_parts),
                display_text=display_text,
                mode="text",
            )

        if self.supports_native_images(adapter):
            prompt_parts.append("Image attachments: " + ", ".join(image.name for image in images))
            content: list[dict[str, Any]] = [{"type": "text", "text": "\n\n".join(prompt_parts)}]
            content.extend(local_image_block(image) for image in images)
            return PreparedChatInput(
                content=content,
                display_text=display_text,
                mode="native",
            )

        try:
            fallback_available = self._fallback_available()
        except Exception:
            fallback_available = False
        if not fallback_available:
            return self._fallback_unavailable_input(prompt_parts, images, display_text)

        try:
            fallback = self._fallback_factory()
        except MoondreamPluginUnavailable:
            return self._fallback_unavailable_input(prompt_parts, images, display_text)
        descriptions: list[str] = []
        for image in images:
            description = fallback.describe(image.path.read_bytes(), DEFAULT_IMAGE_PROMPT).strip()
            descriptions.append(f"Image attachment {image.name}:\n{description or '[No description returned]'}")
        prompt_parts.append("\n\n".join(descriptions))
        return PreparedChatInput(
            content="\n\n".join(prompt_parts),
            display_text=display_text,
            mode="moondream",
        )
