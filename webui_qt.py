"""PyQt 设置界面入口（与 Gradio 的 webui.py 对应）。"""

import os
import sys
from pathlib import Path

# 打包后：必须在任何会触发 ConfigManager / 读 ./data 的 import 之前切到「发行根」。
# 否则从资源管理器双击时 cwd 常为 exe 所在目录（.../SettingsUI/），模块级
# tools.generate_sprites 里 ConfigManager() 会先把 data/ 解析到 .../SettingsUI/data/，
# 而 main() 里再 chdir 后保存会写到发行根 data/，出现读、写两套目录。
if getattr(sys, "frozen", False):
    try:
        _release = Path(sys.executable).resolve().parent.parent
        os.environ["EASYAI_PROJECT_ROOT"] = str(_release)
        os.chdir(_release)
        # MERGE 多包时公共 DLL/同路径资源在列表中**先**打的 exe 目录（本仓库为 main_sprite）；
        # 仅打 Settings 时此处目录不存在。否则 Settings 进程必须在 import QtMultimedia 前
        # 能访问 main_sprite/_internal，否则会 ModuleNotFoundError / 缺二进位。
        _ms = _release / "main_sprite" / "_internal"
        if _ms.is_dir():
            p = str(_ms.resolve())
            if p not in sys.path:
                sys.path.insert(0, p)
    except OSError:
        pass

current_script = Path(__file__).resolve()
project_root = current_script.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

# QtMultimedia 在 ui.settings_ui 内惰性导入，勿在此顶层 import（MERGE 下 Settings 包常缺此子模块）

if getattr(sys, "frozen", False):
    from core.bootstrap.frozen_log import init_frozen_stdio

    init_frozen_stdio("SettingsUI")

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from config.config_manager import ConfigManager
from i18n import init_i18n
from ui.qss import load_pydracula_dark
from ui.settings_ui import create_default_context
from ui.settings_ui.window import FONT_FAMILY_MS_YAHEI, SettingsWindow, settings_window_metrics

def main() -> None:
    # 冻结时发行根与 cwd 已在模块最上方设置，勿重复 chdir，以免与已初始化的单例不一致
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
    # DWM：Settings 用 RGB 边框色；Chat 在 chat_ui.showEvent 使用 border_color_none（Win11 抑薄边框）
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
