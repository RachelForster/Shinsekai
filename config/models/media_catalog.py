"""Pure in-memory Background and Effect catalog entity models."""

from __future__ import annotations

from typing import Any, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from config.models.character import Sprite
from config.models.common import DefaultIfNone


def _normalize_id(value: Any) -> str:
    cleaned = str(value or "").strip()
    return cleaned or uuid4().hex


class Background(BaseModel):
    """单个背景配置的实体模型"""

    id: DefaultIfNone[str] = Field(
        default_factory=lambda: uuid4().hex,
        description="背景组稳定唯一标识",
    )
    name: str = Field(..., description="背景组名称")
    sprite_prefix: str = Field(..., description="背景图片的上传目录名")
    sprites: DefaultIfNone[List[Sprite]] = Field(default_factory=list, description="背景图片列表")
    bg_tags: DefaultIfNone[str] = Field(default="", description="背景图片的信息")
    bgm_list: Optional[List[str]] = Field(default_factory=list, description="背景音乐列表")
    bgm_tags: DefaultIfNone[str] = Field(default="", description="背景音乐描述")

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, value: Any) -> str:
        return _normalize_id(value)


class Effect(BaseModel):
    """单个特效方案的实体模型"""

    id: DefaultIfNone[str] = Field(
        default_factory=lambda: uuid4().hex,
        description="特效方案稳定唯一标识",
    )
    name: str = Field(..., description="特效方案名称")
    color: str = Field(default="#5b8def", description="特效方案标识颜色")
    prompt_text: DefaultIfNone[str] = Field(default="", description="通用提示词")
    audio_list: Optional[List[str]] = Field(default_factory=list, description="特效音频列表")
    audio_tags: DefaultIfNone[str] = Field(default="", description="特效音频信息")
    image_list: Optional[List[str]] = Field(default_factory=list, description="特效图片列表")
    image_tags: DefaultIfNone[str] = Field(default="", description="特效图片信息")
    image_audio_list: Optional[List[str]] = Field(
        default_factory=list,
        description="图片特效绑定音频列表",
    )

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, value: Any) -> str:
        return _normalize_id(value)


__all__ = ["Background", "Effect"]
