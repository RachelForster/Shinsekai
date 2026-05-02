"""聊天主窗口底栏上方的短时加载条（文本 + 扫光动画条）。"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QBrush,
    QLinearGradient,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from ui.chat_ui.styles import FONT_FAMILY


class ShimmerBar(QWidget):
    """细轨道 + 循环扫过的亮光。

    注意：勿为本条单独套 ``QGraphicsDropShadowEffect``（套在父级整包上也会导致子控件重绘被缓存，动画看起来停住）。
    主线程长时间阻塞（如同步加载模型）时，事件循环不跑，定时器不会触发，动画也会停——属单线程限制。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._phase = 0.0
        self.setFixedHeight(7)
        self.setMinimumWidth(108)
        self.setMaximumWidth(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._tick = QTimer(self)
        self._tick.setTimerType(Qt.TimerType.CoarseTimer)
        self._tick.timeout.connect(self._advance)
        self._tick.setInterval(24)

    def _advance(self) -> None:
        self._phase = (self._phase + 0.022) % 1.0
        self.update()
        # 父级若有样式/合成层，一并请求重绘，避免子控件单独 update 被合并掉
        pw = self.parentWidget()
        if pw is not None:
            pw.update()

    def start_animation(self) -> None:
        if not self._tick.isActive():
            self._tick.start()

    def stop_animation(self) -> None:
        self._tick.stop()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        m = self.contentsRect()
        r = m.adjusted(1, 1, -1, -1)
        radius = 3.5
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)

        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.setBrush(QBrush(QColor(255, 255, 255, 38)))
        p.drawPath(path)

        p.setClipPath(path)

        w = max(1.0, float(r.width()))
        sweep = w + 72.0
        x_center = r.left() + self._phase * sweep - 36.0

        grad = QLinearGradient(x_center, 0.0, x_center + 72.0, 0.0)
        grad.setColorAt(0.0, QColor(130, 210, 255, 0))
        grad.setColorAt(0.42, QColor(150, 230, 255, 110))
        grad.setColorAt(0.5, QColor(220, 245, 255, 255))
        grad.setColorAt(0.58, QColor(150, 230, 255, 110))
        grad.setColorAt(1.0, QColor(130, 210, 255, 0))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(r, radius, radius)


class BusyBar(QWidget):
    """平时隐藏；``show_with`` 显示文案与动画条，可选若干秒后自动隐藏。"""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("BusyBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # 用细描边 + 底色渐变代替 QGraphicsDropShadowEffect，避免子控件动画不重绘
        self.setStyleSheet(
            """
            #BusyBar {
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(52, 58, 74, 248),
                    stop:1 rgba(34, 38, 48, 238)
                );
                border-radius: 10px;
                border: 1px solid rgba(255, 255, 255, 70);
            }
            """
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(12)
        self._label = QLabel(self)
        self._label.setWordWrap(True)
        self._label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._shimmer = ShimmerBar(self)
        row.addWidget(self._label, 1)
        row.addWidget(self._shimmer, 0)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide_bar)
        self.hide()

    def apply_theme_font(self, font_size_css: str) -> None:
        """与主窗 ``apply_font_styles`` 同步字号。"""
        self._label.setStyleSheet(
            f"QLabel {{ color: #eef5fc; font-family: {FONT_FAMILY}; "
            f"font-size: {font_size_css}; font-weight: 500; "
            f"background: transparent; padding: 0; letter-spacing: 0.3px; }}"
        )

    def show_with(self, text: str, duration_seconds: float) -> None:
        """duration_seconds > 0 时自动隐藏；<= 0 则直到 ``hide_bar``。"""
        self._timer.stop()
        self._label.setText(text)
        self.show()
        self._shimmer.start_animation()
        self.raise_()
        if duration_seconds > 0:
            self._timer.start(int(max(0.05, duration_seconds) * 1000))

    def hide_bar(self) -> None:
        self._timer.stop()
        self._shimmer.stop_animation()
        self.hide()
