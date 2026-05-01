"""设置界面共享依赖（管理器、路径），供各标签页使用。"""

from __future__ import annotations

from dataclasses import dataclass

from config.background_manager import BackgroundManager
from config.character_manager import CharacterManager
from config.config_manager import ConfigManager
from llm.template_generator import TemplateGenerator
from tools.generate_sprites import ImageGenerator


@dataclass(frozen=True)
class SettingsUIContext:
    config_manager: ConfigManager
    character_manager: CharacterManager
    background_manager: BackgroundManager
    image_generator: ImageGenerator
    template_generator: TemplateGenerator
    template_dir_path: str
    history_dir: str


# 与旧 WebUI 命名兼容，供 services.chat_template_handlers 等使用
WebUIContext = SettingsUIContext
