"""设置界面小工具。"""

from __future__ import annotations

from PyQt6.QtWidgets import QAbstractItemView, QListWidget, QPlainTextEdit

# 立绘/背景/小工具 画廊中缩略图边长（与 QListWidget::iconSize 及 QIcon 缩放一致）
GALLERY_THUMB_PX = 200


def sync_gallery_to_tag_cursor(
    gallery: QListWidget, tag_edit: QPlainTextEdit
) -> None:
    """标注框里光标在第几行，画廊就选中第几张（行号从 0 起与列表下标一致；超出行数时落在最后一张）。"""
    n = gallery.count()
    if n <= 0:
        return
    line = tag_edit.textCursor().block().blockNumber()
    idx = min(max(0, line), n - 1)
    gallery.setCurrentRow(idx)
    it = gallery.item(idx)
    if it is not None:
        gallery.scrollToItem(it, QAbstractItemView.ScrollHint.EnsureVisible)


class PathFile:
    """与 Gradio 文件对象相同，供 character_manager / background_manager 使用 .name 字段。"""

    __slots__ = ("name",)

    def __init__(self, path: str) -> None:
        self.name = path


def path_file_list(paths: list[str]) -> list[PathFile]:
    return [PathFile(p) for p in paths if p]
