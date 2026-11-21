"""Pure in-memory domain and settings Pydantic models."""

from config.models.api_settings import ApiConfig, normalize_api_config_dict
from config.models.app_config import AppConfig
from config.models.character import (
    Character,
    CharacterSummary,
    ModelSprites,
    PortraitCrop,
    RelationEdge,
    RelationGraph,
    RelationNode,
    Sprite,
    SpriteTransition,
    build_default_self_persona,
)
from config.models.common import (
    COMPACT_TARGET_RATIO_MIN_GAP,
    DEFAULT_SPRITE_GROUP,
    DefaultIfNone,
    SELF_PERSONA_ID,
    SELF_PERSONA_NAME,
    SELF_PERSONA_SPRITE_PREFIX,
    clamp_compact_target_ratio,
    default_if_none,
    is_self_persona_name,
)
from config.models.mcp_settings import McpConfig
from config.models.media_catalog import Background, Effect
from config.models.system_settings import SystemConfig, normalize_system_config_dict
from config.models.ui_state import UiRuntimeState

__all__ = [
    "ApiConfig",
    "AppConfig",
    "Background",
    "COMPACT_TARGET_RATIO_MIN_GAP",
    "Character",
    "CharacterSummary",
    "DEFAULT_SPRITE_GROUP",
    "DefaultIfNone",
    "Effect",
    "McpConfig",
    "ModelSprites",
    "PortraitCrop",
    "RelationEdge",
    "RelationGraph",
    "RelationNode",
    "SELF_PERSONA_ID",
    "SELF_PERSONA_NAME",
    "SELF_PERSONA_SPRITE_PREFIX",
    "Sprite",
    "SpriteTransition",
    "SystemConfig",
    "UiRuntimeState",
    "build_default_self_persona",
    "clamp_compact_target_ratio",
    "default_if_none",
    "is_self_persona_name",
    "normalize_api_config_dict",
    "normalize_system_config_dict",
]
