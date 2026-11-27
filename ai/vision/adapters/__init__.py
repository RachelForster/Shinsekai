"""Built-in concrete vision adapter implementations."""

from ai.vision.adapters.deepseek import (
    DEFAULT_DEEPSEEK_VISION_BASE_URL,
    DEFAULT_DEEPSEEK_VISION_MODEL,
    DeepSeekVisionAdapter,
    DeepseekVisionAdapter,
    DeepseekVisonAdapter,
)
from ai.vision.adapters.moondream import (
    MOONDREAM_MODEL_ASSET,
    MOONDREAM_PLUGIN_ENTRY,
    MOONDREAM_PLUGIN_ID,
    MoondreamPluginUnavailable,
    MoondreamVisionAdapter,
    installed_moondream_directory,
    moondream_model_cached,
)
from ai.vision.adapters.providers import (
    ChatGPTVisionAdapter,
    ClaudeVisionAdapter,
    DoubaoVisionAdapter,
    GeminiVisionAdapter,
    OllamaVisionAdapter,
    OpenAICompatibleVisionAdapter,
    QwenVisionAdapter,
)

__all__ = [
    "ChatGPTVisionAdapter",
    "ClaudeVisionAdapter",
    "DEFAULT_DEEPSEEK_VISION_BASE_URL",
    "DEFAULT_DEEPSEEK_VISION_MODEL",
    "DeepSeekVisionAdapter",
    "DeepseekVisionAdapter",
    "DeepseekVisonAdapter",
    "DoubaoVisionAdapter",
    "GeminiVisionAdapter",
    "MOONDREAM_MODEL_ASSET",
    "MOONDREAM_PLUGIN_ENTRY",
    "MOONDREAM_PLUGIN_ID",
    "MoondreamPluginUnavailable",
    "MoondreamVisionAdapter",
    "OllamaVisionAdapter",
    "OpenAICompatibleVisionAdapter",
    "QwenVisionAdapter",
    "installed_moondream_directory",
    "moondream_model_cached",
]
