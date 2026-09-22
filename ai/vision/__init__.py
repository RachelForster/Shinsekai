"""Host-side image understanding abstractions."""

from .vision_adapter import VisionAdapter

__all__ = [
    "ChatVisionService",
    "configured_vision_available",
    "configured_vision_manager",
    "DeepSeekVisionAdapter",
    "DeepseekVisonAdapter",
    "DeepseekVisionAdapter",
    "PreparedChatInput",
    "VisionAdapter",
    "VisionManager",
]


def __getattr__(name: str):
    # Keep provider/plugin imports lazy so LLM adapters can import the neutral
    # message encoders without creating a plugin-host import cycle.
    if name == "VisionManager":
        from .vision_manager import VisionManager

        return VisionManager
    if name in {"ChatVisionService", "PreparedChatInput", "configured_vision_available", "configured_vision_manager"}:
        from .service import (
            ChatVisionService,
            PreparedChatInput,
            configured_vision_available,
            configured_vision_manager,
        )

        return {
            "ChatVisionService": ChatVisionService,
            "PreparedChatInput": PreparedChatInput,
            "configured_vision_available": configured_vision_available,
            "configured_vision_manager": configured_vision_manager,
        }[name]
    if name in {"DeepSeekVisionAdapter", "DeepseekVisonAdapter", "DeepseekVisionAdapter"}:
        from .deepseek_vision_adapter import (
            DeepSeekVisionAdapter,
            DeepseekVisonAdapter,
            DeepseekVisionAdapter,
        )

        return {
            "DeepSeekVisionAdapter": DeepSeekVisionAdapter,
            "DeepseekVisonAdapter": DeepseekVisonAdapter,
            "DeepseekVisionAdapter": DeepseekVisionAdapter,
        }[name]
    raise AttributeError(name)
