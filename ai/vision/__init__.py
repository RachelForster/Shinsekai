"""Host-side image understanding abstractions."""

from .vision_adapter import VisionAdapter

__all__ = ["ChatVisionService", "PreparedChatInput", "VisionAdapter", "VisionManager"]


def __getattr__(name: str):
    # Keep provider/plugin imports lazy so LLM adapters can import the neutral
    # message encoders without creating a plugin-host import cycle.
    if name == "VisionManager":
        from .vision_manager import VisionManager

        return VisionManager
    if name in {"ChatVisionService", "PreparedChatInput"}:
        from .service import ChatVisionService, PreparedChatInput

        return {"ChatVisionService": ChatVisionService, "PreparedChatInput": PreparedChatInput}[name]
    raise AttributeError(name)
