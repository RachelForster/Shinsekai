"""Composite top-level application configuration model."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from config.models.api_settings import ApiConfig
from config.models.character import Character
from config.models.common import DefaultIfNone
from config.models.media_catalog import Background, Effect
from config.models.system_settings import SystemConfig


class AppConfig(BaseModel):
    """应用的整体配置模型，包含角色列表、API 配置和系统配置"""

    characters: List[Character] = Field(..., description="角色配置列表")
    background_list: List[Background] = Field(..., description="背景组设置")
    effect_list: DefaultIfNone[List[Effect]] = Field(default_factory=list, description="特效方案列表")
    api_config: ApiConfig = Field(..., description="API 相关配置")
    system_config: SystemConfig = Field(..., description="系统相关配置")


__all__ = ["AppConfig"]
