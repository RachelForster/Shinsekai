"""
桌面助手主窗口等 UI 的 QSS 集中定义；动态色值与字号通过参数传入。
"""

from __future__ import annotations

FONT_FAMILY = "'Microsoft YaHei', 'SimHei', 'Arial'"

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


def dialog_label_theme_applied(
    font_size: str, theme_color: str, second_color: str
) -> str:
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
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0   {theme_color},
                    stop: 1   {second_color}
                );
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
) -> str:
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
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0   {theme_color},
                    stop: 1   {second_color}
                );
            }}
        """


def text_edit_input(btn_font_size: str) -> str:
    return f"""
            QTextEdit {{
                background-color: rgba(50, 50, 50, 200);
                color: white;
                font-family: {FONT_FAMILY};
                border: 1px solid #555;
                border-radius: 5px;
                padding: 8px 10px;
                font-size: {btn_font_size};
            }}
        """


def send_button_theme(theme_color: str, btn_font_size: str) -> str:
    return f"""
            QPushButton {{
                background-color: {theme_color};
                font-family: {FONT_FAMILY};
                color: white;
                border: none;
                border-radius: 10px;
                padding: 20px;
                font-size: {btn_font_size}
            }}
            QPushButton:hover {{
                background-color: rgba(50, 50, 50, 200);
            }}
        """


def send_button_input_bar_green(btn_font_size: str) -> str:
    return f"""
            QPushButton {{
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 10px;
                padding: 10px;
                font-size: {btn_font_size}
            }}
            QPushButton:hover {{
                background-color: #45a049;
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


def options_widget_container() -> str:
    return f"""
            QWidget {{
                background-color: rgba(50, 50, 50, 200);
                border-radius: 12px;
                border-bottom-left-radius: 0;
                border-bottom-right-radius: 0;
                font-family: {FONT_FAMILY};
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
) -> str:
    return f"""
                QLabel {{
                    background-color: rgba(255, 255, 255, 50);
                    color: white;
                    border-radius: 6px;
                    padding: 9px;
                    text-align: left;
                    font-size: {font_size};
                    min-height: 40px;
                    background: qlineargradient(
                        x1: 0, y1: 0, x2: 1, y2: 0,
                        stop: 0   {theme_color},
                        stop: 1   {second_color}
                    );
                }}
                QLabel:hover {{
                background-color: {low_opacity_theme};
                border-bottom: 5px solid {theme_color};
                color: white;
                padding: 9px 20px 11px 20px;
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
