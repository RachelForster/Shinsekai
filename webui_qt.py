"""PyQt 设置界面入口（与 Gradio 的 webui.py 对应）。"""

import sys
from pathlib import Path

current_script = Path(__file__).resolve()
project_root = current_script.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from ui.settings_ui import create_default_context
from ui.settings_ui.window import FONT_FAMILY_MS_YAHEI, SettingsWindow, settings_window_metrics

# qt-material 主题（可改为 dark_teal.xml、light_cyan_500.xml 等；见 qt_material.themes 列表）
_QT_MATERIAL_THEME = "light_cyan_500.xml"


def main() -> None:
    app = QApplication(sys.argv)
    ctx = create_default_context()
    w, h, font_px, line_h = settings_window_metrics(ctx.config_manager)
    from qt_material import apply_stylesheet

    factor = 0.4
    font_size = int(font_px*factor)
    line_height = int(line_h*factor)
    apply_stylesheet(
        app,
        theme=_QT_MATERIAL_THEME,
        extra={
            "font_size": font_size,
            "line_height": line_height,
            "font_family": FONT_FAMILY_MS_YAHEI,
        },
    )
    f = QFont(FONT_FAMILY_MS_YAHEI)
    f.setPixelSize(font_px)
    app.setFont(f)
    win = SettingsWindow(ctx, width=w, height=h, font_pixel_size=font_px)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
