"""Pure in-memory character, sprite, avatar, and relation-graph domain models."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from config.models.common import (
    DefaultIfNone,
    SELF_PERSONA_ID,
    SELF_PERSONA_NAME,
    SELF_PERSONA_SPRITE_PREFIX,
    is_self_persona_id,
    is_self_persona_name,
)


def _coerce_path_str(value: Any) -> Any:
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    return value


def _normalize_entity_id(value: Any) -> str:
    return str(value or "").strip()


class RelationNode(BaseModel):
    """角色关系图谱的节点"""

    model_config = ConfigDict(extra="forbid")
    key: str = Field(..., min_length=1, max_length=200, description="人物名称及图谱节点标识")

    @model_validator(mode="after")
    def validate_relation_node(self):
        if not self.key.strip() or self.key != self.key.strip():
            raise ValueError("Node key must be non-empty and trimmed")
        return self


class RelationEdge(BaseModel):
    """角色关系图谱的有向边"""

    model_config = ConfigDict(extra="forbid")
    source: str = Field(..., description="起点节点标识")
    target: str = Field(..., description="终点节点标识")
    temperature: DefaultIfNone[int] = Field(default=0, ge=-10, le=10, description="关系温度")
    content: DefaultIfNone[str] = Field(default="", max_length=100, description="关系描述")

    @model_validator(mode="after")
    def validate_relation_content(self):
        if self.content and not self.content.strip():
            raise ValueError("Relationship content must not be blank")
        return self


class RelationGraph(BaseModel):
    """所属角色的独立关系图谱"""

    model_config = ConfigDict(extra="forbid")
    nodes: DefaultIfNone[List[RelationNode]] = Field(
        default_factory=list, max_length=100, description="关系节点列表"
    )
    edges: DefaultIfNone[List[RelationEdge]] = Field(
        default_factory=list, max_length=156, description="有向关系列表"
    )

    @model_validator(mode="after")
    def validate_relation_graph(self):
        keys = [n.key for n in self.nodes]
        if len({k.strip().lower() for k in keys}) != len(keys):
            raise ValueError("Node keys must be unique")
        pairs = set()
        for edge in self.edges:
            pair = (edge.source, edge.target)
            if edge.source not in keys or edge.target not in keys or edge.source == edge.target:
                raise ValueError("Edge endpoints must be distinct existing nodes")
            if pair in pairs:
                raise ValueError("Duplicate directed edge")
            pairs.add(pair)
        return self


class PortraitCrop(BaseModel):
    """Normalized square viewport: center in the image and zoom over cover size."""

    x: float = Field(default=0.5, ge=0, le=1)
    y: float = Field(default=0.2, ge=0, le=1)
    zoom: float = Field(default=1.0, ge=1, le=8)


class Sprite(BaseModel):
    """角色的单个立绘/语音配置（纯内存模型，不做磁盘存在性校验）"""

    path: str = Field(..., description="立绘图片的文件路径")
    voice_path: Optional[str] = Field(None, description="对应的语音文件的路径 (可选)")
    voice_text: Optional[str] = Field(None, description="语音对应的文本内容 (可选, 存在于某些条目中)")
    voice_type: Optional[str] = Field(None, description="语音类型: fallback、preset 或 reference")
    portrait_crop: Optional[PortraitCrop] = None
    mouth_sync: Optional[str] = None
    group: Optional[str] = Field(default=None, description="服装分组名称；为空或省略时视为默认组")

    @field_validator("path", mode="before")
    @classmethod
    def _coerce_sprite_path(cls, value: Any) -> Any:
        return _coerce_path_str(value)

    @field_validator("voice_path", mode="before")
    @classmethod
    def _coerce_voice_path(cls, value: Any) -> Any:
        if value is None:
            return None
        return _coerce_path_str(value)

    # Narrow dict-like compatibility helpers for legacy callers/tests migrated from Union[Sprite, dict].
    def get(self, key: str, default: Any = None) -> Any:
        if key in type(self).model_fields:
            return getattr(self, key)
        return default

    def __getitem__(self, key: str) -> Any:
        if key in type(self).model_fields:
            return getattr(self, key)
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if key not in type(self).model_fields:
            raise KeyError(key)
        if key == "path":
            value = _coerce_path_str(value)
        elif key == "voice_path" and value is not None:
            value = _coerce_path_str(value)
        elif key == "portrait_crop" and isinstance(value, dict):
            value = PortraitCrop.model_validate(value)
        setattr(self, key, value)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in type(self).model_fields


class ModelSprites(BaseModel):
    """一个模型形象格式（如 l2d / vrm）的模型路径与它自己的资源列表、标签。

    静态形象继续使用根级 ``sprites`` / ``emotion_tags``，不进入 ``Character.avatars``。
    """

    model_path: DefaultIfNone[str] = Field(default="", description="模型入口文件路径；未配置时为空字符串")
    sprites: DefaultIfNone[List[Sprite]] = Field(
        default_factory=list, description="该格式的状态文件列表（复用 Sprite）"
    )
    emotion_tags: DefaultIfNone[str] = Field(default="", description="该格式的情绪标签")

    @field_validator("model_path", mode="before")
    @classmethod
    def _coerce_model_path(cls, value: Any) -> Any:
        return _coerce_path_str(value)


class SpriteTransition(BaseModel):
    """A directed clip tied to the exact source assets, including legacy five-frame clips."""

    from_path: str
    to_path: str
    path: str
    from_fingerprint: str
    to_fingerprint: str
    frame_count: int = Field(default=5, ge=1)
    h3_resolution: Literal["workflow", "hd", "native"] = "workflow"


class Character(BaseModel):
    """单个角色配置的实体模型"""

    id: DefaultIfNone[str] = Field(
        default_factory=lambda: uuid4().hex,
        description="角色稳定唯一标识（内置「自设」固定为 '__self__'）",
    )
    name: str = Field(..., description="角色名称")
    display_name: DefaultIfNone[str] = Field(default="", max_length=24, description="内置自设的显示名")
    color: str = Field(..., description="角色对话框或名字的颜色")
    sprite_prefix: str = Field(..., description="立绘文件名的通用前缀")

    sprites: DefaultIfNone[List[Sprite]] = Field(
        default_factory=list, description="角色的立绘和对应语音的列表"
    )
    sprite_transitions: DefaultIfNone[List[SpriteTransition]] = Field(default_factory=list)
    character_brief: DefaultIfNone[str] = Field(
        default="",
        description="用于次要角色精简提示词的角色简介",
    )
    relation_graph: DefaultIfNone[RelationGraph] = Field(
        default_factory=RelationGraph, description="角色独立的关系图谱"
    )
    character_setting: DefaultIfNone[str] = Field(
        default="", description="角色背景、性格和语言习惯的详细描述"
    )
    sprite_scale: DefaultIfNone[float] = Field(default=1.0, description="立绘的缩放比例 (默认值 1.0)")
    portrait_crop: DefaultIfNone[PortraitCrop] = Field(default_factory=PortraitCrop)
    portrait_sprite_index: DefaultIfNone[int] = Field(
        default=0,
        ge=0,
        description="角色作为主控人物时的默认头像立绘索引",
    )
    emotion_tags: DefaultIfNone[str] = Field(default="", description="情绪标签和对应的立绘编号描述")
    sprite_groups: DefaultIfNone[List[str]] = Field(
        default_factory=list,
        description="自定义服装分组名称列表（保序）",
    )
    default_sprite_group: DefaultIfNone[str] = Field(
        default="",
        description="角色初始默认服装组名称；留空时使用默认组",
    )
    fallback_to_default_group: DefaultIfNone[bool] = Field(
        default=True,
        description="当前服装组无匹配立绘时是否回退到默认组",
    )
    is_builtin: DefaultIfNone[bool] = Field(
        default=False,
        description="是否为系统内置人物槽位（如「自设」）",
    )
    pinned: DefaultIfNone[bool] = Field(
        default=False,
        description="是否在人物列表中置顶显示",
    )
    undeletable: DefaultIfNone[bool] = Field(
        default=False,
        description="是否禁止删除与重命名",
    )
    avatar_type: DefaultIfNone[str] = Field(
        default="static", description="当前选择的形象类型：static 或已注册的模型格式 id"
    )
    avatars: DefaultIfNone[Dict[str, ModelSprites]] = Field(
        default_factory=dict,
        description="模型格式 id → 该格式的模型路径与资源列表；static 不在其中",
    )

    # gpt-sovits 相关的配置
    gpt_model_path: Optional[str] = Field("", description="角色 GPT 模型的路径 (可选)")
    sovits_model_path: Optional[str] = Field("", description="角色的 SoVITS 语音模型路径 (可选)")
    refer_audio_path: Optional[str] = Field("", description="用于语音克隆的参考音频路径 (可选)")
    prompt_text: Optional[str] = Field("", description="角色的初始 Prompt/台词 (可选)")
    prompt_lang: Optional[str] = Field("", description="Prompt 语言，例如: ja (可选)")
    speech_speed: DefaultIfNone[float] = Field(default=1.0, description="角色TTS语速倍率 (默认值 1.0)")
    speech_volume: DefaultIfNone[float] = Field(default=1.0, description="角色TTS语音音量 (0.0-2.0, 默认 1.0)")
    pronunciation_map: DefaultIfNone[Dict[str, str]] = Field(
        default_factory=dict, description="角色名 → 日语读音映射（用于 TTS 发音替换）"
    )

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, value: Any) -> str:
        return _normalize_entity_id(value)

    @field_validator("avatar_type")
    @classmethod
    def normalize_avatar_type(cls, value: str) -> str:
        return value.strip().lower() or "static"

    @field_validator("avatars", mode="before")
    @classmethod
    def normalize_avatar_keys(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = {}
        for key, assets in value.items():
            format_id = str(key).strip().lower()
            if not format_id or format_id == "static" or format_id in normalized:
                raise ValueError(f"invalid or duplicate avatar format: {key!r}")
            normalized[format_id] = assets
        return normalized

    @model_validator(mode="after")
    def _enforce_self_persona_invariants(self):
        explicit_id = "id" in self.model_fields_set and bool((self.id or "").strip())
        is_self = (
            is_self_persona_id(self.id)
            or bool(self.is_builtin)
            or (not explicit_id and is_self_persona_name(self.name))
        )
        if is_self:
            self.id = SELF_PERSONA_ID
            self.is_builtin = True
            self.pinned = True
            self.undeletable = True
            if not (self.sprite_prefix or "").strip():
                self.sprite_prefix = SELF_PERSONA_SPRITE_PREFIX
        elif not (self.id or "").strip():
            self.id = uuid4().hex
        return self


class CharacterSummary(BaseModel):
    """Lightweight read-only character projection used by lists and sidebar indexes."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    display_name: str = ""
    color: str = ""
    sprite_prefix: str = ""
    avatar_type: str = "static"
    is_builtin: bool = False
    pinned: bool = False
    undeletable: bool = False
    portrait_sprite_index: int = 0
    portrait_crop: PortraitCrop = Field(default_factory=PortraitCrop)

    @classmethod
    def from_character(cls, character: Character) -> "CharacterSummary":
        """Build a lightweight summary projection from a full Character entity."""
        return cls(
            id=character.id,
            name=character.name,
            display_name=character.display_name,
            color=character.color,
            sprite_prefix=character.sprite_prefix,
            avatar_type=character.avatar_type,
            is_builtin=character.is_builtin,
            pinned=character.pinned,
            undeletable=character.undeletable,
            portrait_sprite_index=character.portrait_sprite_index,
            portrait_crop=character.portrait_crop.model_copy(deep=True),
        )


def build_default_self_persona() -> Character:
    """Construct the default built-in pinned ``自设`` character entity."""
    return Character(
        id=SELF_PERSONA_ID,
        name=SELF_PERSONA_NAME,
        color="#94A3B8",
        sprite_prefix=SELF_PERSONA_SPRITE_PREFIX,
        is_builtin=True,
        pinned=True,
        undeletable=True,
    )


__all__ = [
    "Character",
    "CharacterSummary",
    "ModelSprites",
    "PortraitCrop",
    "RelationEdge",
    "RelationGraph",
    "RelationNode",
    "Sprite",
    "SpriteTransition",
    "build_default_self_persona",
]
