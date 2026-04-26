"""背景管理标签页（PyQt）。"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from PyQt6.QtCore import Qt, QUrl, pyqtSignal, QSize
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from i18n import tr as tr_i18n
from ui.settings_ui.ai_field_translate import translate_background_fields
from ui.settings_ui.ai_progress import run_ai_task_with_progress
from ui.settings_ui.context import SettingsUIContext
from ui.settings_ui.feedback import feedback_result, message_fail, toast_info, toast_success
from ui.settings_ui.qt_mm import try_create_pair
from ui.settings_ui.utils import path_file_list


class BackgroundSettingsTab(QWidget):
    background_list_changed = pyqtSignal()

    def __init__(self, ctx: SettingsUIContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._player, self._audio = try_create_pair(self)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setSpacing(10)

        self._h2 = QLabel(tr_i18n("bg.h2"))
        lay.addWidget(self._h2)

        # --- 1. 当前背景组与 .bg 文件 ---
        self._box_group = QGroupBox(tr_i18n("bg.file_box"))
        bgl = QVBoxLayout(self._box_group)
        self.selected_bg_group = QComboBox()
        self.selected_bg_group.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        grp_form = QFormLayout()
        self._lbl_sel_grp = QLabel(tr_i18n("bg.row_group"))
        grp_form.addRow(self._lbl_sel_grp, self.selected_bg_group)
        bgl.addLayout(grp_form)
        file_ops = QHBoxLayout()
        self._export_bg_btn = QPushButton(tr_i18n("bg.export"))
        self._export_bg_btn.clicked.connect(self._on_export)
        self._del_bg_btn = QPushButton(tr_i18n("bg.delete"))
        self._del_bg_btn.clicked.connect(self._on_delete_group)
        file_ops.addWidget(self._export_bg_btn)
        file_ops.addWidget(self._del_bg_btn)
        file_ops.addStretch(1)
        bgl.addLayout(file_ops)
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setFrameShadow(QFrame.Shadow.Sunken)
        bgl.addWidget(sep1)
        self._import_lbl = QLabel(tr_i18n("bg.import_lbl"))
        bgl.addWidget(self._import_lbl)
        im_row = QHBoxLayout()
        self.import_bg_path = QLineEdit()
        self.import_bg_path.setReadOnly(True)
        self.import_bg_path.setPlaceholderText(tr_i18n("bg.ph_no_file"))
        self._bip = QPushButton(tr_i18n("bg.pick"))
        self._bip.clicked.connect(self._pick_bg_file)
        im_row.addWidget(self.import_bg_path, stretch=1)
        im_row.addWidget(self._bip)
        bgl.addLayout(im_row)
        self._import_bg_btn = QPushButton(tr_i18n("bg.import"))
        self._import_bg_btn.clicked.connect(self._on_import)
        bgl.addWidget(self._import_bg_btn)
        lay.addWidget(self._box_group)

        # --- 2. 名称与保存 ---
        self._box_meta = QGroupBox(tr_i18n("bg.meta_box"))
        mlay = QVBoxLayout(self._box_meta)
        edit_row = QFormLayout()
        self.bg_name = QLineEdit()
        self.bg_prefix = QLineEdit("temp")
        self._f_bg_name = QLabel(tr_i18n("bg.name"))
        self._f_bg_dir = QLabel(tr_i18n("bg.dir"))
        edit_row.addRow(self._f_bg_name, self.bg_name)
        edit_row.addRow(self._f_bg_dir, self.bg_prefix)
        mlay.addLayout(edit_row)
        tr_row = QHBoxLayout()
        self._bg_translate_btn = QPushButton(tr_i18n("bg.ai_translate"))
        self._bg_translate_btn.setToolTip(tr_i18n("bg.tt_ai_translate"))
        self._bg_translate_btn.clicked.connect(self._on_ai_translate)
        tr_row.addWidget(self._bg_translate_btn)
        tr_row.addStretch(1)
        mlay.addLayout(tr_row)
        self._bg_save_btn = QPushButton(tr_i18n("bg.save"))
        self._bg_save_btn.clicked.connect(self._on_save_group)
        mlay.addWidget(self._bg_save_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self._box_meta)

        # --- 3. 背景图片与说明 ---
        self._box_imgs = QGroupBox(tr_i18n("bg.img_box"))
        imgl = QVBoxLayout(self._box_imgs)
        self._bg_img_paths: list[str] = []
        fl_row = QHBoxLayout()
        self.bg_files_display = QLineEdit()
        self.bg_files_display.setReadOnly(True)
        self.bg_files_display.setPlaceholderText(tr_i18n("bg.ph_no_img"))
        self._bpick = QPushButton(tr_i18n("bg.pick_imgs"))
        self._bpick.clicked.connect(self._pick_bg_imgs)
        fl_row.addWidget(self.bg_files_display, stretch=1)
        fl_row.addWidget(self._bpick)
        imgl.addLayout(fl_row)
        img_btns = QHBoxLayout()
        self._upload_bg_btn = QPushButton(tr_i18n("bg.upload"))
        self._upload_bg_btn.clicked.connect(self._on_upload_imgs)
        self._delete_all_bg_btn = QPushButton(tr_i18n("bg.del_all_img"))
        self._delete_all_bg_btn.clicked.connect(self._on_delete_all_imgs)
        img_btns.addWidget(self._upload_bg_btn)
        img_btns.addWidget(self._delete_all_bg_btn)
        img_btns.addStretch(1)
        imgl.addLayout(img_btns)

        gallery_row = QHBoxLayout()
        mid = QVBoxLayout()
        self.bg_gallery = QListWidget()
        self.bg_gallery.setViewMode(QListWidget.ViewMode.IconMode)
        self.bg_gallery.setIconSize(QSize(100, 100))
        self.bg_gallery.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.bg_gallery.setMinimumHeight(200)
        self.bg_gallery.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._mid_lbl = QLabel(tr_i18n("bg.gal_lbl"))
        mid.addWidget(self._mid_lbl)
        mid.addWidget(self.bg_gallery, stretch=1)
        self._delete_single_bg_btn = QPushButton(tr_i18n("bg.del_one"))
        self._delete_single_bg_btn.clicked.connect(self._on_delete_one_img)
        mid.addWidget(self._delete_single_bg_btn)
        gallery_row.addLayout(mid, stretch=2)

        ir = QVBoxLayout()
        self._ir_lbl = QLabel(tr_i18n("bg.info_lbl"))
        self._ir_lbl.setWordWrap(True)
        ir.addWidget(self._ir_lbl)
        self.bg_info_inputs = QPlainTextEdit()
        self.bg_info_inputs.setMinimumHeight(120)
        self.bg_info_inputs.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        ir.addWidget(self.bg_info_inputs, stretch=1)
        self._upload_bg_info_btn = QPushButton(tr_i18n("bg.save_info"))
        self._upload_bg_info_btn.setToolTip(tr_i18n("bg.tt_info"))
        self._upload_bg_info_btn.clicked.connect(self._on_upload_bg_tags)
        ir.addWidget(self._upload_bg_info_btn)
        gallery_row.addLayout(ir, stretch=1)
        imgl.addLayout(gallery_row)
        lay.addWidget(self._box_imgs)

        # --- 4. 背景音乐 ---
        self._h3_bgm = QLabel(tr_i18n("bg.h3_bgm"))
        lay.addWidget(self._h3_bgm)
        self._box_bgm = QGroupBox(tr_i18n("bg.bgm_box"))
        bgml = QVBoxLayout(self._box_bgm)
        self._bgm_upload_paths: list[str] = []
        bfm = QHBoxLayout()
        self.bgm_files_display = QLineEdit()
        self.bgm_files_display.setReadOnly(True)
        self.bgm_files_display.setPlaceholderText(tr_i18n("bg.ph_bgm"))
        self._bp = QPushButton(tr_i18n("bg.pick_bgm"))
        self._bp.clicked.connect(self._pick_bgm)
        bfm.addWidget(self.bgm_files_display, stretch=1)
        bfm.addWidget(self._bp)
        bgml.addLayout(bfm)
        bgm_up_row = QHBoxLayout()
        self._upload_bgm_btn = QPushButton(tr_i18n("bg.up_bgm"))
        self._upload_bgm_btn.clicked.connect(self._on_upload_bgm)
        self._delete_all_bgm_btn = QPushButton(tr_i18n("bg.del_all_bgm"))
        self._delete_all_bgm_btn.clicked.connect(self._on_delete_all_bgm)
        bgm_up_row.addWidget(self._upload_bgm_btn)
        bgm_up_row.addWidget(self._delete_all_bgm_btn)
        bgm_up_row.addStretch(1)
        bgml.addLayout(bgm_up_row)

        bgm_row = QHBoxLayout()
        b2 = QVBoxLayout()
        self._table_hint = QLabel(tr_i18n("bg.table_hint"))
        self._table_hint.setWordWrap(True)
        b2.addWidget(self._table_hint)
        self.bgm_table = QTableWidget(0, 5)
        self.bgm_table.setHorizontalHeaderLabels(
            [
                tr_i18n("bg.table.sel"),
                tr_i18n("bg.table.idx"),
                tr_i18n("bg.table.fname"),
                tr_i18n("bg.table.path"),
                tr_i18n("bg.table.tag"),
            ]
        )
        self.bgm_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.bgm_table.setMinimumHeight(200)
        self.bgm_table.cellClicked.connect(self._on_bgm_cell)
        b2.addWidget(self.bgm_table, stretch=1)
        b2_btns = QHBoxLayout()
        self._play_btn = QPushButton(tr_i18n("bg.play_sel"))
        self._play_btn.clicked.connect(self._on_play_bgm_row)
        self._delete_sel_bgms = QPushButton(tr_i18n("bg.batch_del"))
        self._delete_sel_bgms.setToolTip(tr_i18n("bg.tt_batch"))
        self._delete_sel_bgms.clicked.connect(self._on_batch_delete_bgm)
        b2_btns.addWidget(self._play_btn)
        b2_btns.addWidget(self._delete_sel_bgms)
        b2.addLayout(b2_btns)
        bgm_row.addLayout(b2, stretch=2)

        b3 = QVBoxLayout()
        self._b3_lbl = QLabel(tr_i18n("bg.desc_lbl"))
        self._b3_lbl.setWordWrap(True)
        b3.addWidget(self._b3_lbl)
        self.bgm_info_inputs = QPlainTextEdit()
        self.bgm_info_inputs.setMinimumHeight(100)
        b3.addWidget(self.bgm_info_inputs, stretch=1)
        self._upload_bgm_info_btn = QPushButton(tr_i18n("bg.save_bgm_desc"))
        self._upload_bgm_info_btn.clicked.connect(self._on_upload_bgm_info)
        b3.addWidget(self._upload_bgm_info_btn)
        bgm_row.addLayout(b3, stretch=1)
        bgml.addLayout(bgm_row)
        lay.addWidget(self._box_bgm)

        root.addWidget(scroll)

        self.selected_bg_group.currentTextChanged.connect(self._on_group_change)
        self._refresh_group_combo()
        self._on_group_change(self.selected_bg_group.currentText())

    def _is_new_bg(self, name: str) -> bool:
        return not name or name == tr_i18n("bg.combo_new")

    def _current_bg(self) -> str:
        t = self.selected_bg_group.currentText()
        if self._is_new_bg(t):
            return ""
        return t

    def _refresh_group_combo(self, select: str | None = None) -> None:
        self.selected_bg_group.blockSignals(True)
        self.selected_bg_group.clear()
        self.selected_bg_group.addItem(tr_i18n("bg.combo_new"))
        for n in self._ctx.background_manager.get_background_name_list():
            self.selected_bg_group.addItem(n)
        if select:
            i = self.selected_bg_group.findText(select)
            if i >= 0:
                self.selected_bg_group.setCurrentIndex(i)
        self.selected_bg_group.blockSignals(False)

    def _on_group_change(self, name: str) -> None:
        if self._is_new_bg(name):
            self.bg_name.clear()
            self.bg_prefix.setText("temp")
        else:
            bg = self._ctx.config_manager.get_background_by_name(name)
            if bg:
                self.bg_name.setText(bg.name)
                self.bg_prefix.setText(bg.sprite_prefix or "temp")
        paths, tags, _ = (
            self._ctx.background_manager.get_background_sprites(name)
            if name and not self._is_new_bg(name)
            else ([], "", [])
        )
        self._load_gallery(paths)
        self.bg_info_inputs.setPlainText(tags if isinstance(tags, str) else "")
        self._bg_img_paths.clear()
        self.bg_files_display.clear()
        if name and not self._is_new_bg(name):
            df, btags = self._ctx.background_manager.load_bgms_and_tags(name)
            self._fill_bgm_table(df)
            self.bgm_info_inputs.setPlainText(btags)
        else:
            self.bgm_table.setRowCount(0)
            self.bgm_info_inputs.clear()
        self.bgm_table.clearSelection()

    def apply_i18n(self) -> None:
        cur = self.selected_bg_group.currentText()
        is_new = self._is_new_bg(cur)
        sel = tr_i18n("bg.combo_new") if is_new else cur
        self._h2.setText(tr_i18n("bg.h2"))
        self._h3_bgm.setText(tr_i18n("bg.h3_bgm"))
        self._box_group.setTitle(tr_i18n("bg.file_box"))
        self._lbl_sel_grp.setText(tr_i18n("bg.row_group"))
        self._export_bg_btn.setText(tr_i18n("bg.export"))
        self._del_bg_btn.setText(tr_i18n("bg.delete"))
        self._import_lbl.setText(tr_i18n("bg.import_lbl"))
        self.import_bg_path.setPlaceholderText(tr_i18n("bg.ph_no_file"))
        self._bip.setText(tr_i18n("bg.pick"))
        self._import_bg_btn.setText(tr_i18n("bg.import"))
        self._box_meta.setTitle(tr_i18n("bg.meta_box"))
        self._f_bg_name.setText(tr_i18n("bg.name"))
        self._f_bg_dir.setText(tr_i18n("bg.dir"))
        self._bg_translate_btn.setText(tr_i18n("bg.ai_translate"))
        self._bg_translate_btn.setToolTip(tr_i18n("bg.tt_ai_translate"))
        self._bg_save_btn.setText(tr_i18n("bg.save"))
        self._box_imgs.setTitle(tr_i18n("bg.img_box"))
        self.bg_files_display.setPlaceholderText(tr_i18n("bg.ph_no_img"))
        self._bpick.setText(tr_i18n("bg.pick_imgs"))
        self._upload_bg_btn.setText(tr_i18n("bg.upload"))
        self._delete_all_bg_btn.setText(tr_i18n("bg.del_all_img"))
        self._mid_lbl.setText(tr_i18n("bg.gal_lbl"))
        self._delete_single_bg_btn.setText(tr_i18n("bg.del_one"))
        self._ir_lbl.setText(tr_i18n("bg.info_lbl"))
        self._upload_bg_info_btn.setText(tr_i18n("bg.save_info"))
        self._upload_bg_info_btn.setToolTip(tr_i18n("bg.tt_info"))
        self._box_bgm.setTitle(tr_i18n("bg.bgm_box"))
        self.bgm_files_display.setPlaceholderText(tr_i18n("bg.ph_bgm"))
        self._bp.setText(tr_i18n("bg.pick_bgm"))
        self._upload_bgm_btn.setText(tr_i18n("bg.up_bgm"))
        self._delete_all_bgm_btn.setText(tr_i18n("bg.del_all_bgm"))
        self._table_hint.setText(tr_i18n("bg.table_hint"))
        self.bgm_table.setHorizontalHeaderLabels(
            [
                tr_i18n("bg.table.sel"),
                tr_i18n("bg.table.idx"),
                tr_i18n("bg.table.fname"),
                tr_i18n("bg.table.path"),
                tr_i18n("bg.table.tag"),
            ]
        )
        self._play_btn.setText(tr_i18n("bg.play_sel"))
        self._delete_sel_bgms.setText(tr_i18n("bg.batch_del"))
        self._delete_sel_bgms.setToolTip(tr_i18n("bg.tt_batch"))
        self._b3_lbl.setText(tr_i18n("bg.desc_lbl"))
        self._upload_bgm_info_btn.setText(tr_i18n("bg.save_bgm_desc"))
        self._refresh_group_combo(sel)
        self._on_group_change(self.selected_bg_group.currentText())

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
            message_fail(
                self, tr_i18n("bg.msg_title_bgm"), tr_i18n("bg.msg_missing", path=path)
            )
            return
        if not self._player:
            message_fail(
                self, tr_i18n("bg.msg_title_bgm"), tr_i18n("common.msg_qtmm_unavailable")
            )
            return
        toast_info(
            self,
            tr_i18n("bg.msg_title_bgm"),
            tr_i18n("bg.toast_playing", name=os.path.basename(path)),
        )
        self._player.setSource(QUrl.fromLocalFile(str(Path(path).absolute())))
        self._player.play()

    def _on_ai_translate(self) -> None:
        tags: list[str] = []
        for r in range(self.bgm_table.rowCount()):
            it = self.bgm_table.item(r, 4)
            tags.append(it.text() if it else "")
        code = str(self._ctx.config_manager.config.system_config.ui_language)
        bg_name = self.bg_name.text().strip()
        bg_info = self.bg_info_inputs.toPlainText()
        bgm_info = self.bgm_info_inputs.toPlainText()

        def work():
            return translate_background_fields(
                self._ctx.config_manager,
                code,
                bg_name,
                bg_info,
                bgm_info,
                tags,
            )

        def on_ok(
            res: tuple[str, str, str, str, list[str]],
        ) -> None:
            self._bg_translate_btn.setEnabled(True)
            err, n, bgi, bgmi, new_tags = res
            if err == "no_content":
                message_fail(
                    self, tr_i18n("bg.msg_translate_title"), tr_i18n("bg.msg_translate_empty")
                )
            elif err == "llm_incomplete":
                message_fail(
                    self, tr_i18n("bg.msg_translate_title"), tr_i18n("bg.msg_translate_llm")
                )
            elif err == "bad_bgm_row_tags":
                message_fail(
                    self,
                    tr_i18n("bg.msg_translate_title"),
                    tr_i18n("bg.msg_translate_tags_mismatch"),
                )
            elif err:
                message_fail(
                    self,
                    tr_i18n("bg.msg_translate_title"),
                    tr_i18n("bg.msg_translate_fail", detail=err),
                )
            else:
                self.bg_name.setText(n)
                self.bg_info_inputs.setPlainText(bgi)
                self.bgm_info_inputs.setPlainText(bgmi)
                for r in range(len(new_tags)):
                    it = self.bgm_table.item(r, 4)
                    if it is None:
                        it = QTableWidgetItem()
                        self.bgm_table.setItem(r, 4, it)
                    it.setText(new_tags[r])
                toast_success(
                    self,
                    tr_i18n("bg.msg_translate_title"),
                    tr_i18n("bg.toast_translate_ok"),
                )

        def on_fail(msg: str) -> None:
            self._bg_translate_btn.setEnabled(True)
            message_fail(
                self,
                tr_i18n("bg.msg_translate_title"),
                tr_i18n("bg.msg_translate_fail", detail=msg),
            )

        self._bg_translate_btn.setEnabled(False)
        run_ai_task_with_progress(
            self,
            tr_i18n("common.ai_working_title"),
            tr_i18n("common.ai_progress_translate"),
            work,
            on_ok,
            on_fail,
        )

    def _on_export(self) -> None:
        msg = self._ctx.background_manager.export_background_file(self._current_bg())
        feedback_result(self, tr_i18n("bg.msg_title"), msg)

    def _on_delete_group(self) -> None:
        msg, _ = self._ctx.background_manager.delete_background(self._current_bg())
        feedback_result(self, tr_i18n("bg.msg_title"), msg)
        self._refresh_group_combo(tr_i18n("bg.combo_new"))
        self.background_list_changed.emit()

    def _pick_bg_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr_i18n("bg.dlg_bg"), "", "Background (*.bg);;All (*)"
        )
        if path:
            self.import_bg_path.setText(path)

    def _on_import(self) -> None:
        p = self.import_bg_path.text().strip()
        if not p:
            message_fail(
                self, tr_i18n("bg.msg_title"), tr_i18n("bg.msg_select_file")
            )
            return
        try:
            msg, _ = self._ctx.background_manager.import_background_file(p)
        except Exception as e:
            message_fail(
                self, tr_i18n("bg.msg_title"), tr_i18n("bg.msg_import_fail", e=e)
            )
            return
        feedback_result(
            self, tr_i18n("bg.msg_title"), str(msg) if msg else tr_i18n("bg.msg_done")
        )
        self._refresh_group_combo(tr_i18n("bg.combo_new"))
        self.background_list_changed.emit()

    def _on_save_group(self) -> None:
        sel = self.selected_bg_group.currentText().strip()
        edit_as: str | None = None
        if not self._is_new_bg(sel):
            edit_as = sel
        msg, _ = self._ctx.background_manager.add_background(
            self.bg_name.text().strip(),
            self.bg_prefix.text().strip() or "temp",
            edit_as_name=edit_as,
        )
        feedback_result(self, tr_i18n("bg.msg_title"), msg)
        n = self.bg_name.text().strip()
        self._refresh_group_combo(n)
        self._on_group_change(n)
        self.background_list_changed.emit()

    def _pick_bg_imgs(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, tr_i18n("bg.dlg_imgs"), "", "Images (*.png *.jpg *.jpeg);;All (*)"
        )
        self._bg_img_paths = list(files)
        self.bg_files_display.setText(
            tr_i18n("bg.msg_n_files", n=len(self._bg_img_paths))
        )

    def _on_upload_imgs(self) -> None:
        if not self._bg_img_paths:
            message_fail(
                self, tr_i18n("bg.msg_title"), tr_i18n("bg.msg_select_imgs")
            )
            return
        msg, paths, tags = self._ctx.background_manager.upload_sprites(
            self._current_bg(), path_file_list(self._bg_img_paths), self.bg_info_inputs.toPlainText()
        )
        feedback_result(self, tr_i18n("bg.msg_title"), msg)
        self._load_gallery(paths)
        self.bg_info_inputs.setPlainText(tags)
        self.background_list_changed.emit()

    def _on_delete_all_imgs(self) -> None:
        msg, paths, t = self._ctx.background_manager.delete_all_sprites(self._current_bg())
        feedback_result(self, tr_i18n("bg.msg_title"), msg)
        self._load_gallery(paths)
        self.bg_info_inputs.setPlainText(t)
        self.background_list_changed.emit()

    def _on_delete_one_img(self) -> None:
        row = self.bg_gallery.currentRow()
        if row < 0:
            return
        msg, paths, t = self._ctx.background_manager.delete_single_sprite(self._current_bg(), row)
        feedback_result(self, tr_i18n("bg.msg_title"), msg)
        self._load_gallery(paths)
        self.bg_info_inputs.setPlainText(t)
        self.background_list_changed.emit()

    def _on_upload_bg_tags(self) -> None:
        msg = self._ctx.background_manager.upload_bg_tags(self._current_bg(), self.bg_info_inputs.toPlainText())
        feedback_result(self, tr_i18n("bg.msg_title"), msg)

    def _pick_bgm(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, tr_i18n("bg.dlg_bgm"), "", "Audio (*);;All (*)"
        )
        self._bgm_upload_paths = list(files)
        self.bgm_files_display.setText(
            tr_i18n("bg.msg_n_files", n=len(self._bgm_upload_paths))
        )

    def _on_upload_bgm(self) -> None:
        if not self._bgm_upload_paths:
            message_fail(
                self, tr_i18n("bg.msg_title_bgm"), tr_i18n("bg.msg_select_bgm")
            )
            return
        msg, df, btags = self._ctx.background_manager.upload_bgms(self._current_bg(), path_file_list(self._bgm_upload_paths))
        feedback_result(self, tr_i18n("bg.msg_title_bgm"), msg)
        self._fill_bgm_table(df)
        self.bgm_info_inputs.setPlainText(btags)
        self.background_list_changed.emit()

    def _on_delete_all_bgm(self) -> None:
        msg, _, _ = self._ctx.background_manager.delete_all_bgms(self._current_bg())
        feedback_result(self, tr_i18n("bg.msg_title_bgm"), msg)
        self.bgm_table.setRowCount(0)
        self.bgm_info_inputs.clear()
        self.background_list_changed.emit()

    def _on_batch_delete_bgm(self) -> None:
        df = self._table_to_bgm_dataframe()
        msg, new_df, tags = self._ctx.background_manager.batch_delete_bgms(
            self._current_bg(), df, self.bgm_info_inputs.toPlainText()
        )
        self._fill_bgm_table(new_df)
        self.bgm_info_inputs.setPlainText(tags)
        feedback_result(self, tr_i18n("bg.msg_title_bgm"), msg)
        self.background_list_changed.emit()

    def _on_upload_bgm_info(self) -> None:
        msg = self._ctx.background_manager.upload_bgm_tags(self._current_bg(), self.bgm_info_inputs.toPlainText())
        feedback_result(self, tr_i18n("bg.msg_title_bgm"), msg)
        self.background_list_changed.emit()
