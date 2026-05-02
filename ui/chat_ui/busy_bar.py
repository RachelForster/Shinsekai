"""聊天主窗口底栏上方的短时加载条：纵向渐变底（上淡、中重、下淡）+ skeleton 呼吸文案。"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from ui.chat_ui.styles import FONT_FAMILY
from ui.chat_ui.theme_chrome import sanitize_chrome_declarations


class BusyBar(QWidget):
    """平时隐藏；圆角衬底为竖直方向中间略重的半透明色带；文字 skeleton 呼吸。"""

    _RADIUS_PX = 7.0

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("BusyBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#BusyBar { background: transparent; border: none; }")

        self._label_fs = "12px;"
        self._label_chrome_extra = ""
        self._breathe_phase = 0.0
        self._breathe_timer = QTimer(self)
        self._breathe_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._breathe_timer.timeout.connect(self._tick_breathe)
        self._breathe_timer.setInterval(40)

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(8)
        self._label = QLabel(self)
        self._label.setWordWrap(True)
        self._label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        row.addWidget(self._label, 1)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide_bar)
        self.hide()

    def _tick_breathe(self) -> None:
        self._breathe_phase = (self._breathe_phase + 0.014) % 1.0
        self._apply_label_skeleton_style()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        """上淡 — 中重 — 下淡：平滑钟形剖面 + 中间略亮，避免色阶断层。"""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = self.rect()
        r = m.adjusted(1, 1, -1, -1)
        if r.width() < 2 or r.height() < 2:
            return

        path = QPainterPath()
        path.addRoundedRect(r, self._RADIUS_PX, self._RADIUS_PX)

        grad = QLinearGradient(r.left(), r.top(), r.left(), r.bottom())
        # u∈[0,1] 自上至下；k 为距竖直中心的「隆起」权重（边缘 0、中线 1）
        n_stops = 23
        for i in range(n_stops):
            u = i / (n_stops - 1)
            d = abs(u - 0.5) * 2.0
            k = 0.5 * (1.0 + math.cos(min(1.0, d) * math.pi))
            a = int(28 + 94 * k)
            rr = int(14 + 8 * k)
            gg = int(18 + 10 * k)
            bb = int(28 + 13 * k)
            grad.setColorAt(u, QColor(rr, gg, bb, a))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawPath(path)

    def height_for_bar_width(self, bar_width: int) -> int:
        """在固定条宽下按换行规则计算所需高度（供外部分配 geometry 使用）。"""
        lay = self.layout()
        if lay is None:
            return max(26, self.sizeHint().height())
        m = lay.contentsMargins()
        inner_w = max(1, int(bar_width) - m.left() - m.right())
        h_text = self._label.heightForWidth(inner_w)
        return max(26, h_text + m.top() + m.bottom())

    def _apply_label_skeleton_style(self) -> None:
        """Skeleton：灰阶占位色 + 透明度随相位起伏，模拟加载占位条明暗周期。"""
        ph = self._breathe_phase
        wave = 0.5 + 0.5 * math.sin(ph * math.pi * 2.0 * 0.88)
        # 略快一点的次要分量，让观感接近常见 skeleton shimmer（非横扫，仅亮度微差拍）
        shim = 0.5 + 0.5 * math.sin(ph * math.pi * 2.0 * 1.55 + 0.4)
        t = 0.42 + 0.58 * wave + 0.06 * (shim - 0.5)
        t = max(0.0, min(1.0, t))
        r = int(148 + 82 * t)
        g = int(158 + 78 * t)
        b = int(176 + 68 * t)
        a = int(100 + 155 * t)
        fs = self._label_fs
        cx = sanitize_chrome_declarations(self._label_chrome_extra)
        cx_line = f" {cx}" if cx else ""
        self._label.setStyleSheet(
            f"QLabel {{ color: rgba({r},{g},{b},{a}); font-family: {FONT_FAMILY}; "
            f"font-size: {fs} font-weight: 400; background: transparent; "
            f"padding: 0; letter-spacing: 0.35px; line-height: 148%;"
            f"{cx_line} }}"
        )

    def set_label_chrome_extra(self, extra: str) -> None:
        """合并自 chat_ui_theme.json 的 QLabel 片段（sanitize 会去掉字号/宽高等）。"""
        self._label_chrome_extra = (extra or "").strip()
        if self._breathe_timer.isActive() or self.isVisible():
            self._apply_label_skeleton_style()

    def apply_theme_font(self, font_size_css: str) -> None:
        """与主窗 ``apply_font_styles`` 同步字号。"""
        try:
            px_raw = font_size_css.replace("px", "").replace(";", "").strip()
            # 明显小于对话正文，避免与主窗同档字号显得笨重（约主字号 70%，下限 10px、上限 16px）
            body = int(px_raw)
            px = max(10, min(16, int(body * 8 // 10)))
            self._label_fs = f"{px}px;"
        except (ValueError, TypeError):
            raw = font_size_css.strip()
            self._label_fs = raw if raw.endswith(";") else f"{raw};"
        if self._breathe_timer.isActive() or self.isVisible():
            self._apply_label_skeleton_style()

    def show_with(self, text: str, duration_seconds: float) -> None:
        """duration_seconds > 0 时自动隐藏；<= 0 则直到 ``hide_bar``。"""
        self._timer.stop()
        self._label.setText(text)
        self._apply_label_skeleton_style()
        self.show()
        if not self._breathe_timer.isActive():
            self._breathe_timer.start()
        self.raise_()
        if duration_seconds > 0:
            self._timer.start(int(max(0.05, duration_seconds) * 1000))

    def hide_bar(self) -> None:
        self._timer.stop()
        self._breathe_timer.stop()
        self.hide()
