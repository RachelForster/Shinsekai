"""PyQt 设置界面入口（与 Gradio 的 webui.py 对应）。"""

import os
import sys
from pathlib import Path

current_script = Path(__file__).resolve()
project_root = current_script.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from config.config_manager import ConfigManager
from i18n import init_i18n
from ui.qss import load_pydracula_dark
from ui.settings_ui import create_default_context
from ui.settings_ui.window import FONT_FAMILY_MS_YAHEI, SettingsWindow, settings_window_metrics

def main() -> None:
    # 打包（PyInstaller onedir）：可执行文件在 dist/<发行根>/SettingsUI/ 下，与 main_sprite/ 平级，cwd 需为发行根目录以便 ./data 等相对路径与 launch_chat 一致
    if getattr(sys, "frozen", False):
        try:
            rel = Path(sys.executable).resolve().parent.parent
            os.environ["EASYAI_PROJECT_ROOT"] = str(rel)
            os.chdir(rel)
        except OSError:
            pass

    init_i18n(ConfigManager().config.system_config.ui_language)
    app = QApplication(sys.argv)
    app.setStyleSheet(load_pydracula_dark())
    ctx = create_default_context()
    w, h, font_px, line_h = settings_window_metrics(ctx.config_manager)
    font_px = int(font_px * 0.4)
    line_h = int(line_h * 0.4)
    f = QFont(FONT_FAMILY_MS_YAHEI)
    f.setPixelSize(font_px)
    app.setFont(f)
    win = SettingsWindow(ctx, width=w, height=h, font_pixel_size=font_px)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
