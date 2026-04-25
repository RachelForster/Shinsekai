"""背景管理标签页（PyQt）。"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from PyQt6.QtCore import Qt, QUrl, pyqtSignal, QSize
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.settings_ui.context import SettingsUIContext
from ui.settings_ui.utils import path_file_list


class BackgroundSettingsTab(QWidget):
    background_list_changed = pyqtSignal()

    def __init__(self, ctx: SettingsUIContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner)

        lay.addWidget(QLabel("<h2>背景管理</h2>"))
        top = QHBoxLayout()
        c1 = QVBoxLayout()
        c1.addWidget(QLabel("选择背景组"))
        self.selected_bg_group = QComboBox()
        c1.addWidget(self.selected_bg_group)
        export_bg_btn = QPushButton("导出到 ./output 文件夹")
        export_bg_btn.clicked.connect(self._on_export)
        del_bg_btn = QPushButton("删除背景组")
        del_bg_btn.clicked.connect(self._on_delete_group)
        c1.addWidget(export_bg_btn)
        c1.addWidget(del_bg_btn)
        top.addLayout(c1)

        c2 = QVBoxLayout()
        c2.addWidget(QLabel("从文件导入 .bg"))
        im_row = QHBoxLayout()
        self.import_bg_path = QLineEdit()
        self.import_bg_path.setReadOnly(True)
        bip = QPushButton("选择文件…")
        bip.clicked.connect(self._pick_bg_file)
        im_row.addWidget(self.import_bg_path)
        im_row.addWidget(bip)
        c2.addLayout(im_row)
        import_bg_btn = QPushButton("从文件导入背景组")
        import_bg_btn.clicked.connect(self._on_import)
        c2.addWidget(import_bg_btn)
        self.import_bg_output = QPlainTextEdit()
        self.import_bg_output.setReadOnly(True)
        self.import_bg_output.setMaximumHeight(80)
        c2.addWidget(self.import_bg_output)
        top.addLayout(c2)
        lay.addLayout(top)

        edit_row = QFormLayout()
        self.bg_name = QLineEdit()
        self.bg_prefix = QLineEdit("temp")
        edit_row.addRow("背景组名称", self.bg_name)
        edit_row.addRow("上传数据目录名（英文）", self.bg_prefix)
        lay.addLayout(edit_row)
        bg_save_btn = QPushButton("添加/保存背景组")
        bg_save_btn.clicked.connect(self._on_save_group)
        lay.addWidget(bg_save_btn)

        img_row = QHBoxLayout()
        il = QVBoxLayout()
        fl_row = QHBoxLayout()
        self.bg_files_display = QLineEdit()
        self.bg_files_display.setReadOnly(True)
        self._bg_img_paths: list[str] = []
        bpick = QPushButton("选择背景图片…")
        bpick.clicked.connect(self._pick_bg_imgs)
        fl_row.addWidget(self.bg_files_display)
        fl_row.addWidget(bpick)
        il.addLayout(fl_row)
        upload_bg_btn = QPushButton("上传图片")
        upload_bg_btn.clicked.connect(self._on_upload_imgs)
        il.addWidget(upload_bg_btn)
        delete_all_bg_btn = QPushButton("删除所有背景图片")
        delete_all_bg_btn.clicked.connect(self._on_delete_all_imgs)
        il.addWidget(delete_all_bg_btn)
        self.upload_bg_output = QPlainTextEdit()
        self.upload_bg_output.setReadOnly(True)
        self.upload_bg_output.setMaximumHeight(60)
        il.addWidget(self.upload_bg_output)
        img_row.addLayout(il)

        mid = QVBoxLayout()
        self.bg_gallery = QListWidget()
        self.bg_gallery.setViewMode(QListWidget.ViewMode.IconMode)
        self.bg_gallery.setIconSize(QSize(100, 100))
        self.bg_gallery.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.bg_gallery.setMinimumHeight(180)
        mid.addWidget(QLabel("已上传的背景图片"))
        mid.addWidget(self.bg_gallery)
        delete_single_bg_btn = QPushButton("删除选中背景图片")
        delete_single_bg_btn.clicked.connect(self._on_delete_one_img)
        mid.addWidget(delete_single_bg_btn)
        img_row.addLayout(mid)

        ir = QVBoxLayout()
        ir.addWidget(QLabel("描述背景"))
        self.bg_info_inputs = QPlainTextEdit()
        self.bg_info_inputs.setMinimumHeight(120)
        ir.addWidget(self.bg_info_inputs)
        upload_bg_info_btn = QPushButton("上传背景信息")
        upload_bg_info_btn.clicked.connect(self._on_upload_bg_tags)
        ir.addWidget(upload_bg_info_btn)
        img_row.addLayout(ir)
        lay.addLayout(img_row)

        lay.addWidget(QLabel("<h3>背景音乐</h3>"))
        bgm_top = QHBoxLayout()
        b1 = QVBoxLayout()
        bfm = QHBoxLayout()
        self.bgm_files_display = QLineEdit()
        self.bgm_files_display.setReadOnly(True)
        self._bgm_upload_paths: list[str] = []
        bp = QPushButton("选择音乐…")
        bp.clicked.connect(self._pick_bgm)
        bfm.addWidget(self.bgm_files_display)
        bfm.addWidget(bp)
        b1.addLayout(bfm)
        upload_bgm_btn = QPushButton("上传音乐")
        upload_bgm_btn.clicked.connect(self._on_upload_bgm)
        b1.addWidget(upload_bgm_btn)
        delete_all_bgm_btn = QPushButton("删除所有背景音乐")
        delete_all_bgm_btn.clicked.connect(self._on_delete_all_bgm)
        b1.addWidget(delete_all_bgm_btn)
        self.upload_bgm_output = QPlainTextEdit()
        self.upload_bgm_output.setReadOnly(True)
        self.upload_bgm_output.setMaximumHeight(50)
        b1.addWidget(self.upload_bgm_output)
        bgm_top.addLayout(b1)

        b2 = QVBoxLayout()
        self.bgm_table = QTableWidget(0, 5)
        self.bgm_table.setHorizontalHeaderLabels(["选", "序号", "文件名", "路径", "标签描述"])
        self.bgm_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.bgm_table.cellClicked.connect(self._on_bgm_cell)
        b2.addWidget(QLabel("背景音乐列表（点行播放；勾选后批量删除）"))
        b2.addWidget(self.bgm_table)
        self.bgm_output_message = QLineEdit()
        self.bgm_output_message.setReadOnly(True)
        b2.addWidget(self.bgm_output_message)
        play_btn = QPushButton("播放当前选中行")
        play_btn.clicked.connect(self._on_play_bgm_row)
        b2.addWidget(play_btn)
        delete_sel_bgms = QPushButton("批量删除选中的音乐条")
        delete_sel_bgms.clicked.connect(self._on_batch_delete_bgm)
        b2.addWidget(delete_sel_bgms)
        b3 = QVBoxLayout()
        b3.addWidget(QLabel("背景音乐文字描述（每行对应一条）"))
        self.bgm_info_inputs = QPlainTextEdit()
        self.bgm_info_inputs.setMinimumHeight(100)
        b3.addWidget(self.bgm_info_inputs)
        upload_bgm_info_btn = QPushButton("上传背景音乐描述")
        upload_bgm_info_btn.clicked.connect(self._on_upload_bgm_info)
        b3.addWidget(upload_bgm_info_btn)
        bgm_top.addLayout(b2)
        bgm_top.addLayout(b3)
        lay.addLayout(bgm_top)

        root.addWidget(scroll)

        self.selected_bg_group.currentTextChanged.connect(self._on_group_change)
        self._refresh_group_combo()
        self._on_group_change(self.selected_bg_group.currentText())

    def _current_bg(self) -> str:
        t = self.selected_bg_group.currentText()
        if not t or t == "新背景":
            return ""
        return t

    def _refresh_group_combo(self, select: str | None = None) -> None:
        self.selected_bg_group.blockSignals(True)
        self.selected_bg_group.clear()
        self.selected_bg_group.addItem("新背景")
        for n in self._ctx.background_manager.get_background_name_list():
            self.selected_bg_group.addItem(n)
        if select:
            i = self.selected_bg_group.findText(select)
            if i >= 0:
                self.selected_bg_group.setCurrentIndex(i)
        self.selected_bg_group.blockSignals(False)

    def _on_group_change(self, name: str) -> None:
        if not name or name == "新背景":
            self.bg_name.clear()
            self.bg_prefix.setText("temp")
        else:
            bg = self._ctx.config_manager.get_background_by_name(name)
            if bg:
                self.bg_name.setText(bg.name)
                self.bg_prefix.setText(bg.sprite_prefix or "temp")
        paths, tags, _ = (
            self._ctx.background_manager.get_background_sprites(name) if name and name != "新背景" else ([], "", [])
        )
        self._load_gallery(paths)
        self.bg_info_inputs.setPlainText(tags if isinstance(tags, str) else "")
        self._bg_img_paths.clear()
        self.bg_files_display.clear()
        if name and name != "新背景":
            df, btags = self._ctx.background_manager.load_bgms_and_tags(name)
            self._fill_bgm_table(df)
            self.bgm_info_inputs.setPlainText(btags)
        else:
            self.bgm_table.setRowCount(0)
            self.bgm_info_inputs.clear()
        self.bgm_table.clearSelection()

    def _load_gallery(self, paths: list) -> None:
        self.bg_gallery.clear()
        for p in paths:
            if not p or not Path(p).exists():
                continue
            pix = QPixmap(str(p))
            if not pix.isNull():
                it = QListWidgetItem(
                    QIcon(
                        pix.scaled(
                            100,
                            100,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    ),
                    Path(p).name,
                )
                it.setData(Qt.ItemDataRole.UserRole, p)
                self.bg_gallery.addItem(it)

    def _fill_bgm_table(self, df: pd.DataFrame) -> None:
        self.bgm_table.setRowCount(0)
        if df is None or df.empty:
            return
        for _, row in df.iterrows():
            r = self.bgm_table.rowCount()
            self.bgm_table.insertRow(r)
            c0 = QTableWidgetItem()
            c0.setFlags(c0.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            c0.setCheckState(Qt.CheckState.Unchecked)
            c1 = QTableWidgetItem(str(int(row.get("序号", r + 1))))
            c2 = QTableWidgetItem(str(row.get("文件名", "")))
            c3 = QTableWidgetItem(str(row.get("路径", "")))
            c4 = QTableWidgetItem(str(row.get("标签描述", "")))
            self.bgm_table.setItem(r, 0, c0)
            self.bgm_table.setItem(r, 1, c1)
            self.bgm_table.setItem(r, 2, c2)
            self.bgm_table.setItem(r, 3, c3)
            self.bgm_table.setItem(r, 4, c4)
        self.bgm_table.resizeColumnsToContents()

    def _table_to_bgm_dataframe(self) -> pd.DataFrame:
        rows = []
        for r in range(self.bgm_table.rowCount()):
            c0 = self.bgm_table.item(r, 0)
            c1 = self.bgm_table.item(r, 1)
            c2 = self.bgm_table.item(r, 2)
            c3 = self.bgm_table.item(r, 3)
            c4 = self.bgm_table.item(r, 4)
            rows.append(
                {
                    "选择": c0.checkState() == Qt.CheckState.Checked if c0 else False,
                    "序号": int(c1.text()) if c1 and c1.text().isdigit() else r + 1,
                    "文件名": c2.text() if c2 else "",
                    "路径": c3.text() if c3 else "",
                    "标签描述": c4.text() if c4 else "",
                }
            )
        return pd.DataFrame(rows)

    def _on_bgm_cell(self, row: int, _col: int) -> None:
        self._play_bgm_at_row(row)

    def _on_play_bgm_row(self) -> None:
        r = self.bgm_table.currentRow()
        if r >= 0:
            self._play_bgm_at_row(r)

    def _play_bgm_at_row(self, row: int) -> None:
        it = self.bgm_table.item(row, 3)
        if not it:
            return
        path = it.text()
        if not path or not Path(path).is_file():
            self.bgm_output_message.setText(f"文件不存在: {path}")
            return
        self.bgm_output_message.setText(f"正在播放: {os.path.basename(path)}")
        self._player.setSource(QUrl.fromLocalFile(str(Path(path).absolute())))
        self._player.play()

    def _on_export(self) -> None:
        msg = self._ctx.background_manager.export_background_file(self._current_bg())
        self.import_bg_output.setPlainText(msg)

    def _on_delete_group(self) -> None:
        msg, _ = self._ctx.background_manager.delete_background(self._current_bg())
        self.import_bg_output.setPlainText(msg)
        self._refresh_group_combo("新背景")
        self.background_list_changed.emit()

    def _pick_bg_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 .bg 文件", "", "Background (*.bg);;All (*)")
        if path:
            self.import_bg_path.setText(path)

    def _on_import(self) -> None:
        p = self.import_bg_path.text().strip()
        if not p:
            self.import_bg_output.setPlainText("请选择文件")
            return
        try:
            msg, _ = self._ctx.background_manager.import_background_file(p)
        except Exception as e:
            msg = f"导入失败: {e}"
        self.import_bg_output.setPlainText(str(msg) if msg else "完成")
        self._refresh_group_combo("新背景")
        self.background_list_changed.emit()

    def _on_save_group(self) -> None:
        msg, _ = self._ctx.background_manager.add_background(self.bg_name.text().strip(), self.bg_prefix.text().strip() or "temp")
        self.upload_bg_output.setPlainText(msg)
        n = self.bg_name.text().strip()
        self._refresh_group_combo(n)
        self._on_group_change(n)
        self.background_list_changed.emit()

    def _pick_bg_imgs(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "背景图片", "", "Images (*.png *.jpg *.jpeg);;All (*)")
        self._bg_img_paths = list(files)
        self.bg_files_display.setText(f"{len(self._bg_img_paths)} 个文件")

    def _on_upload_imgs(self) -> None:
        if not self._bg_img_paths:
            self.upload_bg_output.setPlainText("请选择图片")
            return
        msg, paths, tags = self._ctx.background_manager.upload_sprites(
            self._current_bg(), path_file_list(self._bg_img_paths), self.bg_info_inputs.toPlainText()
        )
        self.upload_bg_output.setPlainText(msg)
        self._load_gallery(paths)
        self.bg_info_inputs.setPlainText(tags)
        self.background_list_changed.emit()

    def _on_delete_all_imgs(self) -> None:
        msg, paths, t = self._ctx.background_manager.delete_all_sprites(self._current_bg())
        self.upload_bg_output.setPlainText(msg)
        self._load_gallery(paths)
        self.bg_info_inputs.setPlainText(t)
        self.background_list_changed.emit()

    def _on_delete_one_img(self) -> None:
        row = self.bg_gallery.currentRow()
        if row < 0:
            return
        msg, paths, t = self._ctx.background_manager.delete_single_sprite(self._current_bg(), row)
        self.upload_bg_output.setPlainText(msg)
        self._load_gallery(paths)
        self.bg_info_inputs.setPlainText(t)
        self.background_list_changed.emit()

    def _on_upload_bg_tags(self) -> None:
        msg = self._ctx.background_manager.upload_bg_tags(self._current_bg(), self.bg_info_inputs.toPlainText())
        self.upload_bg_output.setPlainText(msg)

    def _pick_bgm(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "背景音乐", "", "Audio (*);;All (*)")
        self._bgm_upload_paths = list(files)
        self.bgm_files_display.setText(f"{len(self._bgm_upload_paths)} 个文件")

    def _on_upload_bgm(self) -> None:
        if not self._bgm_upload_paths:
            self.upload_bgm_output.setPlainText("请选择音乐文件")
            return
        msg, df, btags = self._ctx.background_manager.upload_bgms(self._current_bg(), path_file_list(self._bgm_upload_paths))
        self.upload_bgm_output.setPlainText(msg)
        self._fill_bgm_table(df)
        self.bgm_info_inputs.setPlainText(btags)
        self.background_list_changed.emit()

    def _on_delete_all_bgm(self) -> None:
        msg, _, _ = self._ctx.background_manager.delete_all_bgms(self._current_bg())
        self.bgm_output_message.setText(msg)
        self.bgm_table.setRowCount(0)
        self.bgm_info_inputs.clear()
        self.background_list_changed.emit()

    def _on_batch_delete_bgm(self) -> None:
        df = self._table_to_bgm_dataframe()
        msg, new_df, tags = self._ctx.background_manager.batch_delete_bgms(
            self._current_bg(), df, self.bgm_info_inputs.toPlainText()
        )
        self.bgm_output_message.setText(msg)
        self._fill_bgm_table(new_df)
        self.bgm_info_inputs.setPlainText(tags)
        QMessageBox.information(self, "背景音乐", msg)
        self.background_list_changed.emit()

    def _on_upload_bgm_info(self) -> None:
        msg = self._ctx.background_manager.upload_bgm_tags(self._current_bg(), self.bgm_info_inputs.toPlainText())
        self.bgm_output_message.setText(msg)
        self.background_list_changed.emit()
