"""
桌面助手主窗口等 UI 的 QSS 集中定义；动态色值与字号通过参数传入。

可由 ``data/chat_ui_theme.json`` 提供额外声明（见 :mod:`ui.chat_ui.theme_chrome`）。
"""

from __future__ import annotations

import re

from ui.chat_ui.theme_chrome import (
    extract_border_radius_from_chrome,
    sanitize_chrome_declarations,
)

FONT_FAMILY = "'Microsoft YaHei', 'SimHei', 'Arial'"


def _chrome_x(extra: str) -> str:
    s = sanitize_chrome_declarations(extra)
    return f"\n                {s}" if s else ""

# --- 工具栏 ---


def toolbar_host(border_radius_px: int = 20) -> str:
    return f"background-color: rgba(50, 50, 50, 150); border-radius: {border_radius_px}px;"


def toolbar_action_button(
    font_size: str = "28px", border_radius_px: int = 24
) -> str:
    return f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 100);
                border: 2px solid rgba(255, 255, 255, 150);
                border-radius: {border_radius_px}px;
                color: white;
                font-size: {font_size};
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 150);
            }}
            QPushButton:pressed {{
                background-color: rgba(255, 255, 255, 200);
            }}
        """


# --- 对话框 / 输入区 ---


def dialog_label_initial(font_size: str, dialog_frame_path: str) -> str:
    return f"""
            QLabel {{
                background-color: rgba(50, 50, 50, 200);
                color: #f0f0f0;
                font-size: {font_size};
                font-family: {FONT_FAMILY};
                padding: 40px;
                border-radius: 12px;
                border-bottom-left-radius: 0;
                border-bottom-right-radius: 0;
                line-height: 200%;
                letter-spacing: 2px;
                border-image: url({dialog_frame_path}) 40 40 40 40 stretch;
                border-width: 40px;
            }}
        """


def _chrome_has_background_image(extra: str) -> bool:
    """chrome 中含 background-image 时，勿再写 background 渐变，否则 Qt 会盖住印花。"""
    return bool(re.search(r"(?i)background-image\s*:", extra or ""))


def dialog_label_theme_applied(
    font_size: str,
    theme_color: str,
    second_color: str,
    chrome_extra: str = "",
) -> str:
    cx = _chrome_x(chrome_extra)
    if _chrome_has_background_image(chrome_extra):
        grad = ""
    else:
        grad = f"""background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0   {theme_color},
                    stop: 1   {second_color}
                );"""
    return f"""
            QLabel {{
                background-color: rgba(50, 50, 50, 200);
                color: #f0f0f0;
                font-size: {font_size};
                font-family: {FONT_FAMILY};
                padding: 16px;
                border-radius: 16px;
                border-bottom-left-radius: 0;
                line-height: 200%;
                letter-spacing: 2px;
                {grad}
                {cx}
            }}
        """


def numeric_info_label_initial(font_size: str) -> str:
    return f"""
            QLabel {{
                background-color: rgba(0, 0, 0, 100);
                padding: 12px;
                font-family: {FONT_FAMILY};
                font-size: {font_size};
                line-height: 150%;
                border-radius: 16px;
                color: white;
            }}
        """


def numeric_info_label_theme_applied(
    font_size: str,
    theme_color: str,
    second_color: str,
    dialog_frame_border_url: str,
    chrome_extra: str = "",
) -> str:
    cx = _chrome_x(chrome_extra)
    if _chrome_has_background_image(chrome_extra):
        grad = ""
    else:
        grad = f"""background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0   {theme_color},
                    stop: 1   {second_color}
                );"""
    return f"""
            QLabel {{
                background-color: rgba(0, 0, 0, 100);
                padding: 12px;
                font-family: {FONT_FAMILY};
                font-size: {font_size};
                line-height: 150%;
                border-radius: 16px;
                color: white;
                border-image: url({dialog_frame_border_url}) 15 15 15 15 stretch;
                border-width: 15px;
                {grad}
                {cx}
            }}
        """


def text_edit_input(btn_font_size: str, chrome_extra: str = "") -> str:
    cx = _chrome_x(chrome_extra)
    return f"""
            QTextEdit {{
                background-color: rgba(50, 50, 50, 200);
                color: white;
                font-family: {FONT_FAMILY};
                border: 1px solid #555;
                border-radius: 5px;
                padding: 8px 10px;
                font-size: {btn_font_size};
                {cx}
            }}
        """


def send_button_theme(
    theme_color: str, btn_font_size: str, chrome_extra: str = ""
) -> str:
    raw = sanitize_chrome_declarations(chrome_extra)
    rest, user_r = extract_border_radius_from_chrome(raw)
    cx = f"\n                {rest}" if rest.strip() else ""
    radius = user_r if user_r else "10px"
    rtail = f"\n                border-radius: {radius};"
    common = f"""
                font-family: {FONT_FAMILY};
                color: white;
                border: none;
                outline: none;
                padding: 20px;
                font-size: {btn_font_size};
                {cx}{rtail}"""
    return f"""
            QPushButton {{
                background-color: {theme_color};
                {common}
            }}
            QPushButton:hover {{
                background-color: rgba(50, 50, 50, 200);
                {common}
            }}
            QPushButton:pressed {{
                background-color: rgba(45, 45, 45, 230);
                {common}
            }}
        """


def send_button_input_bar_green(
    btn_font_size: str, chrome_extra: str = ""
) -> str:
    raw = sanitize_chrome_declarations(chrome_extra)
    rest, user_r = extract_border_radius_from_chrome(raw)
    cx = f"\n                {rest}" if rest.strip() else ""
    radius = user_r if user_r else "10px"
    rtail = f"\n                border-radius: {radius};"
    common = f"""
                color: white;
                border: none;
                outline: none;
                padding: 10px;
                font-size: {btn_font_size};
                {cx}{rtail}"""
    return f"""
            QPushButton {{
                background-color: #4CAF50;
                {common}
            }}
            QPushButton:hover {{
                background-color: #45a049;
                {common}
            }}
            QPushButton:pressed {{
                background-color: #3d8b40;
                {common}
            }}
        """


def skip_speech_button(font_size: str = "16px") -> str:
    return f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 0);
                color: white;
                border: none;
                border-radius: 24px;
                font-size: {font_size};
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 100, 100, 100);
            }}
        """


def options_widget_container(chrome_extra: str = "") -> str:
    cx = _chrome_x(chrome_extra)
    return f"""
            QWidget {{
                background-color: rgba(50, 50, 50, 200);
                border-radius: 12px;
                border-bottom-left-radius: 0;
                border-bottom-right-radius: 0;
                font-family: {FONT_FAMILY};
                {cx}
            }}
        """


def option_row_list_refresh(font_size: str) -> str:
    return f"""
                    QLabel {{
                        background-color: rgba(255, 255, 255, 50);
                        color: white;
                        border-radius: 6px;
                        padding: 5px;
                        text-align: left;
                        font-size: {font_size};
                        min-height: 40px;
                    }}
                    QLabel:hover {{
                        background-color: rgba(255, 255, 255, 30);
                        border: 1px solid;
                    }}
                """


def option_choice_button(
    font_size: str,
    theme_color: str,
    second_color: str,
    low_opacity_theme: str,
    chrome_extra: str = "",
    chrome_hover_extra: str = "",
) -> str:
    cx = _chrome_x(chrome_extra)
    hx = _chrome_x(chrome_hover_extra)
    if _chrome_has_background_image(chrome_extra):
        grad = ""
    else:
        grad = f"""background: qlineargradient(
                        x1: 0, y1: 0, x2: 1, y2: 0,
                        stop: 0   {theme_color},
                        stop: 1   {second_color}
                    );"""
    return f"""
                QLabel {{
                    background-color: rgba(255, 255, 255, 50);
                    color: white;
                    border-radius: 6px;
                    padding: 9px;
                    text-align: left;
                    font-size: {font_size};
                    min-height: 40px;
                    {grad}
                    {cx}
                }}
                QLabel:hover {{
                background-color: {low_opacity_theme};
                border-bottom: 5px solid {theme_color};
                color: white;
                padding: 9px 20px 11px 20px;
                {hx}
            }}

            QLabel:pressed {{
                background-color: {theme_color};
                color: white;
            }}
            """


# --- 背景 ---


def background_label_load_failed() -> str:
    return "background-color: white;"


def background_label_qlabel_image(url_path: str) -> str:
    return f"""
            QLabel {{
                background-image: url({url_path});
                background-repeat: no-repeat;
                background-position: center;
                background-color: #333333;
                border-radius: 24px;
            }}
        """
