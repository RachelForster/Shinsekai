"""原 Gradio 标签页已迁移至 `ui.settings_ui`（PySide6）。此处保留兼容导入。"""

from ui.settings_ui import (
    SettingsUIContext,
    SettingsWindow,
    WebUIContext,
    create_default_context,
)

__all__ = [
    "SettingsUIContext",
    "WebUIContext",
    "SettingsWindow",
    "create_default_context",
]
