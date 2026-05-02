"""发送键 / 麦克风的圆角与描边：用 QPainter 绘制，避免 QSS 在部分平台对 QPushButton 无效。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QPushButton

from ui.chat_ui.theme_chrome import sanitize_chrome_declarations


@dataclass
class ChromePaintParts:
    background: str | None = None
    text_color: str | None = None
    border_width: int = 0
    border_color: str | None = None
    corner_radius_px: int | None = None


def parse_chrome_paint(sanitized_qss: str) -> ChromePaintParts:
    """从 sanitize 后的 QSS 片段解析绘图用字段（纯色与 ``border: Npx solid``）。"""
    cp = ChromePaintParts()
    if not (sanitized_qss or "").strip():
        return cp
    for raw in sanitized_qss.split(";"):
        piece = raw.strip()
        if not piece:
            continue
        pl = piece.lower()
        if pl.startswith("background-color:"):
            cp.background = piece.split(":", 1)[1].strip()
        elif pl.startswith("color:"):
            cp.text_color = piece.split(":", 1)[1].strip()
        elif pl.startswith("border-radius:"):
            m = re.search(r":\s*(\d+(?:\.\d+)?)\s*px", piece, re.I)
            if m:
                cp.corner_radius_px = int(float(m.group(1)))
        elif re.match(r"(?i)border:\s*none\s*$", piece):
            cp.border_width = 0
            cp.border_color = None
        else:
            m = re.search(r"(?i)^border:\s*(\d+)px\s+solid\s+(.+)$", piece)
            if m:
                cp.border_width = int(m.group(1))
                cp.border_color = m.group(2).strip()
    return cp


class ChromeSendButton(QPushButton):
    """底栏发送键：主题 chrome 由 QPainter 画圆角填充，不依赖 QSS border-radius。"""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoDefault(False)
        self.setDefault(False)
        self._san_extra = ""
        self._base_fill = "#4CAF50"
        self._base_text = "#FFFFFF"
        self._def_corner = 10
        self._font_px = 14

    def apply_visual(
        self,
        chrome_extra: str,
        base_fill: str,
        base_text: str,
        *,
        default_corner_px: int = 10,
        font_px: int = 14,
    ) -> None:
        self._san_extra = sanitize_chrome_declarations(chrome_extra)
        self._base_fill = base_fill
        self._base_text = base_text
        self._def_corner = max(0, int(default_corner_px))
        self._font_px = max(8, int(font_px))
        self.setStyleSheet("")
        f = QFont(self.font())
        f.setPixelSize(self._font_px)
        f.setBold(bool(re.search(r"(?i)font-weight:\s*bold", self._san_extra)))
        self.setFont(f)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        parts = parse_chrome_paint(self._san_extra)
        fill_s = parts.background or self._base_fill
        tcol_s = parts.text_color or self._base_text
        bw = parts.border_width
        bc_s = parts.border_color
        w, h = self.width(), self.height()
        max_r = min(w, h) / 2.0
        if parts.corner_radius_px is not None:
            r = min(float(parts.corner_radius_px), max_r)
        else:
            r = min(float(self._def_corner), max_r)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = max(0, bw)
        rect = QRectF(inset, inset, w - 2 * inset, h - 2 * inset)
        if rect.width() < 1 or rect.height() < 1:
            rect = QRectF(0, 0, float(w), float(h))
        r = min(r, rect.width() / 2.0, rect.height() / 2.0)
        path = QPainterPath()
        path.addRoundedRect(rect, r, r)

        fill = QColor(fill_s)
        if not fill.isValid():
            fill = QColor(self._base_fill)
        if self.isDown():
            fill = fill.darker(118)
        elif self.underMouse():
            fill = fill.lighter(108)
        p.fillPath(path, fill)

        if bw > 0 and bc_s:
            pen = QPen(QColor(bc_s), float(bw))
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

        tc = QColor(tcol_s)
        if not tc.isValid():
            tc = QColor(self._base_text)
        p.setPen(tc)
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
