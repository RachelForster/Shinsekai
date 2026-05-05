"""人物设定标签页（PySide6）。"""

from __future__ import annotations

import os
import re
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
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
    QVBoxLayout,
    QWidget,
)

import tools.file_util as fu
from config.character_config import CharacterConfig
from i18n import tr as tr_i18n
from ui.settings_ui.context import SettingsUIContext
from ui.settings_ui.feedback import (
    feedback_result,
    is_failure_message,
    message_fail,
    toast_success,
)
from ui.settings_ui.ai_field_translate import translate_character_name_and_tags
from ui.settings_ui.ai_progress import run_ai_task_with_progress
from ui.settings_ui.qt_mm import try_create_pair
from ui.settings_ui.utils import GALLERY_THUMB_PX, path_file_list, sync_gallery_to_tag_cursor

_DEFAULT_NAME_COLOR = "#d07d7d"


def _rgb_from_floats(rf: float, gf: float, bf: float) -> tuple[int, int, int]:
    """将 rgb 分量转为 0~255 整数。同一括号内：若任一分量 >1 则整段按 0~255；否则按 0~1。"""
    m = max(rf, gf, bf, 0.0)
    if m > 1.0 + 1e-6:
        return (
            int(max(0, min(255, round(rf)))),
            int(max(0, min(255, round(gf)))),
            int(max(0, min(255, round(bf)))),
        )
    return (
        int(max(0, min(255, round(rf * 255.0)))),
        int(max(0, min(255, round(gf * 255.0)))),
        int(max(0, min(255, round(bf * 255.0)))),
    )


def _parse_color_text(s: str) -> QColor:
    """
    解析 #RRGGBB / #AARRGGBB / 颜色名、以及 ``rgba(r,g,b,a)`` / ``rgb(r,g,b)``。
    裸的 ``QColor("rgba(...)")`` 在 Qt 里会无效，故单独处理。
    r/g/b 允许 **带小数**（如 217.99,…），与调色板或外部写入的浮点一致。
    """
    t = (s or "").strip()
    if not t:
        return QColor(_DEFAULT_NAME_COLOR)
    if hasattr(QColor, "fromString"):
        c = QColor.fromString(t)  # type: ignore[attr-defined]
        if c.isValid():
            return c
    c0 = QColor(t)
    if c0.isValid():
        return c0
    m = re.search(
        r"rgba?\s*\(\s*([0-9.eE+.\- ]+)\s*,\s*([0-9.eE+.\- ]+)\s*,\s*([0-9.eE+.\- ]+)(?:\s*,\s*([0-9.eE+.\- ]+))?\s*\)",
        t,
        re.IGNORECASE,
    )
    if m:
        try:
            rf, gf, bf = float(m.group(1).strip()), float(
                m.group(2).strip()
            ), float(m.group(3).strip())
        except ValueError:
            return QColor(_DEFAULT_NAME_COLOR)
        r, g, b = _rgb_from_floats(rf, gf, bf)
        c2 = QColor(r, g, b, 255)
        a_raw = m.group(4)
        if a_raw is not None:
            try:
                av = float(a_raw.strip())
            except ValueError:
                return c2
            if 0.0 <= av <= 1.0 + 1e-6:
                c2.setAlphaF(max(0.0, min(1.0, av)))
            else:
                c2.setAlpha(int(max(0, min(255, round(av)))))
        return c2
    return QColor(_DEFAULT_NAME_COLOR)


def _format_color_text(c: QColor) -> str:
    """不透明度为 255 时用 #RRGGBB，否则用 rgba(整数,整数,整数,a) 与 _parse 一致且避免长小数。"""
    if not c.isValid():
        return _DEFAULT_NAME_COLOR
    if c.alpha() >= 255:
        return c.name()
    a = c.alphaF()
    a_s = f"{a:.3f}".rstrip("0").rstrip(".")
    if not a_s:
        a_s = "0"
    return f"rgba({c.red()},{c.green()},{c.blue()},{a_s})"


class CharacterSettingsTab(QWidget):
    character_list_changed = Signal()

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

        self._h2 = QLabel(tr_i18n("char.h2"))
        lay.addWidget(self._h2)

        # --- 1. 角色选择、导入/导出、文件结果 ---
        self._box_files = QGroupBox(tr_i18n("char.file_box"))
        bl = QVBoxLayout(self._box_files)
        self.selected_character = QComboBox()
        self.selected_character.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        char_row = QFormLayout()
        self._lbl_current_char = QLabel(tr_i18n("char.row_current"))
        char_row.addRow(self._lbl_current_char, self.selected_character)
        bl.addLayout(char_row)
        file_ops = QHBoxLayout()
        self._export_btn = QPushButton(tr_i18n("char.export"))
        self._export_btn.clicked.connect(self._on_export)
        self._del_char_btn = QPushButton(tr_i18n("char.delete"))
        self._del_char_btn.clicked.connect(self._on_delete)
        file_ops.addWidget(self._export_btn)
        file_ops.addWidget(self._del_char_btn)
        file_ops.addStretch(1)
        bl.addLayout(file_ops)
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setFrameShadow(QFrame.Shadow.Sunken)
        bl.addWidget(sep1)
        self._import_lbl = QLabel(tr_i18n("char.import_lbl"))
        bl.addWidget(self._import_lbl)
        self._import_paths: list[str] = []
        imp_row = QHBoxLayout()
        self.import_files_display = QLineEdit()
        self.import_files_display.setReadOnly(True)
        self.import_files_display.setPlaceholderText(tr_i18n("char.ph_no_file"))
        self._pick_files_btn = QPushButton(tr_i18n("char.pick_file"))
        self._pick_files_btn.clicked.connect(self._pick_import_files)
        imp_row.addWidget(self.import_files_display, stretch=1)
        imp_row.addWidget(self._pick_files_btn)
        bl.addLayout(imp_row)
        self._import_btn = QPushButton(tr_i18n("char.import"))
        self._import_btn.clicked.connect(self._on_import)
        bl.addWidget(self._import_btn)
        lay.addWidget(self._box_files)

        # --- 2. 人物信息（表单 + 设定长文本）---
        self._box_info = QGroupBox(tr_i18n("char.info_box"))
        bi = QVBoxLayout(self._box_info)
        info_row = QHBoxLayout()
        left_info = QFormLayout()
        self.char_name = QLineEdit()
        self.char_color = QLineEdit()
        self.char_color.setPlaceholderText(tr_i18n("char.ph_color"))
        self.char_color.textChanged.connect(self._on_char_color_text_changed)
        _color_row = QWidget()
        _cr = QHBoxLayout(_color_row)
        _cr.setContentsMargins(0, 0, 0, 0)
        _cr.setSpacing(6)
        _cr.addWidget(self.char_color, stretch=1)
        self._color_swatch = QFrame()
        self._color_swatch.setFixedSize(36, 24)
        self._color_swatch.setFrameShape(QFrame.Shape.StyledPanel)
        self._b_pick_color = QPushButton(tr_i18n("char.pick_color"))
        self._b_pick_color.setToolTip(tr_i18n("char.tt_pick_color"))
        self._b_pick_color.clicked.connect(self._on_pick_color)
        _cr.addWidget(self._color_swatch, alignment=Qt.AlignmentFlag.AlignRight)
        _cr.addWidget(self._b_pick_color)
        self.sprite_prefix = QLineEdit("temp")
        self._f_name = QLabel(tr_i18n("char.name"))
        self._f_color = QLabel(tr_i18n("char.color"))
        self._f_prefix = QLabel(tr_i18n("char.sprite_dir"))
        left_info.addRow(self._f_name, self.char_name)
        left_info.addRow(self._f_color, _color_row)
        left_info.addRow(self._f_prefix, self.sprite_prefix)
        info_row.addLayout(left_info, stretch=0)
        right_info = QVBoxLayout()
        self._setting_lbl = QLabel(tr_i18n("char.setting_lbl"))
        right_info.addWidget(self._setting_lbl)
        self.character_setting = QPlainTextEdit()
        self.character_setting.setMinimumHeight(120)
        self.character_setting.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._ai_btn = QPushButton(tr_i18n("char.ai_write"))
        self._ai_btn.clicked.connect(self._on_ai_help)
        self._ai_translate_btn = QPushButton(tr_i18n("char.ai_translate"))
        self._ai_translate_btn.setToolTip(tr_i18n("char.tt_ai_translate"))
        self._ai_translate_btn.clicked.connect(self._on_ai_translate)
        right_info.addWidget(self.character_setting, stretch=1)
        ai_row = QHBoxLayout()
        ai_row.addWidget(self._ai_btn)
        ai_row.addWidget(self._ai_translate_btn)
        ai_row.addStretch(1)
        right_info.addLayout(ai_row)
        info_row.addLayout(right_info, stretch=1)
        bi.addLayout(info_row)
        lay.addWidget(self._box_info)

        # --- 3. 语音参考路径（TTS 侧）---
        self._voice_box = QGroupBox(tr_i18n("char.voice_box"))
        vf = QFormLayout(self._voice_box)
        self.gpt_model_path = QLineEdit()
        self.sovits_model_path = QLineEdit()
        self.refer_audio_path = QLineEdit()
        self.prompt_text = QLineEdit()
        self.prompt_lang = QLineEdit()
        self.speech_speed = QDoubleSpinBox()
        self.speech_speed.setRange(0.1, 5.0)
        self.speech_speed.setSingleStep(0.05)
        self.speech_speed.setValue(1.0)
        self._v_gpt = QLabel(tr_i18n("char.gpt_path"))
        self._v_sov = QLabel(tr_i18n("char.sovits_path"))
        self._v_ref = QLabel(tr_i18n("char.ref_audio"))
        self._v_pt = QLabel(tr_i18n("char.ref_text"))
        self._v_pl = QLabel(tr_i18n("char.prompt_lang"))
        self._v_sp = QLabel(tr_i18n("char.speech_speed_lbl"))
        vf.addRow(self._v_gpt, self.gpt_model_path)
        vf.addRow(self._v_sov, self.sovits_model_path)
        vf.addRow(self._v_ref, self.refer_audio_path)
        vf.addRow(self._v_pt, self.prompt_text)
        vf.addRow(self._v_pl, self.prompt_lang)
        vf.addRow(self._v_sp, self.speech_speed)
        lay.addWidget(self._voice_box)

        # --- 4. 立绘：先上传与缩放，再「画廊+情绪」并列，最下为当前立绘语音 ---（可滚动；保存见底部栏）
        self._h2s = QLabel(tr_i18n("char.h2_sprites"))
        lay.addWidget(self._h2s)
        self._box_sprites = QGroupBox(tr_i18n("char.sprite_box"))
        bsp = QVBoxLayout(self._box_sprites)
        up_row = QHBoxLayout()
        self.sprite_files_display = QLineEdit()
        self.sprite_files_display.setReadOnly(True)
        self._sprite_paths: list[str] = []
        self._b_up = QPushButton(tr_i18n("char.pick_sprites"))
        self._b_up.clicked.connect(self._pick_sprites)
        up_row.addWidget(self.sprite_files_display, stretch=1)
        up_row.addWidget(self._b_up)
        bsp.addLayout(up_row)
        up_btns = QHBoxLayout()
        self._upload_sprites_btn = QPushButton(tr_i18n("char.upload_img"))
        self._upload_sprites_btn.clicked.connect(self._on_upload_sprites)
        up_btns.addWidget(self._upload_sprites_btn)
        self._scale_lbl = QLabel(tr_i18n("char.scale_lbl"))
        up_btns.addWidget(self._scale_lbl)
        self.sprite_scale = QDoubleSpinBox()
        self.sprite_scale.setRange(0, 3)
        self.sprite_scale.setSingleStep(0.05)
        self.sprite_scale.setValue(1.0)
        up_btns.addWidget(self.sprite_scale)
        self._scale_save = QPushButton(tr_i18n("char.save_scale"))
        self._scale_save.setToolTip(tr_i18n("char.tt_scale"))
        self._scale_save.clicked.connect(self._on_save_scale)
        up_btns.addWidget(self._scale_save)
        self._del_all_sp = QPushButton(tr_i18n("char.del_all_sp"))
        self._del_all_sp.clicked.connect(self._on_delete_all_sprites)
        up_btns.addWidget(self._del_all_sp)
        up_btns.addStretch(1)
        bsp.addLayout(up_btns)

        gallery_row = QHBoxLayout()
        sp_mid = QVBoxLayout()
        self.sprites_gallery = QListWidget()
        self.sprites_gallery.setViewMode(QListWidget.ViewMode.IconMode)
        self.sprites_gallery.setIconSize(QSize(GALLERY_THUMB_PX, GALLERY_THUMB_PX))
        self.sprites_gallery.setSpacing(8)
        self.sprites_gallery.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.sprites_gallery.setMinimumHeight(400)
        self.sprites_gallery.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.sprites_gallery.currentRowChanged.connect(self._on_sprite_row)
        self._gal_lbl = QLabel(tr_i18n("char.gal_lbl"))
        sp_mid.addWidget(self._gal_lbl)
        sp_mid.addWidget(self.sprites_gallery, stretch=1)
        self._del_one = QPushButton(tr_i18n("char.del_one"))
        self._del_one.clicked.connect(self._on_delete_one_sprite)
        sp_mid.addWidget(self._del_one)
        gallery_row.addLayout(sp_mid, stretch=2)

        sp_right = QVBoxLayout()
        self._emo_lbl = QLabel(tr_i18n("char.emo_lbl"))
        self._emo_lbl.setWordWrap(True)
        sp_right.addWidget(self._emo_lbl)
        self.emotion_inputs = QPlainTextEdit()
        self.emotion_inputs.setMinimumHeight(150)
        self.emotion_inputs.cursorPositionChanged.connect(
            self._on_emotion_tag_cursor_moved
        )
        sp_right.addWidget(self.emotion_inputs, stretch=1)
        self._tag_btn = QPushButton(tr_i18n("char.upload_tags"))
        self._tag_btn.clicked.connect(self._on_upload_tags)
        sp_right.addWidget(self._tag_btn)
        gallery_row.addLayout(sp_right, stretch=1)
        bsp.addLayout(gallery_row)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        bsp.addWidget(sep2)

        self._voice_title = QLabel(tr_i18n("char.voice_title"))
        bsp.addWidget(self._voice_title)
        self.selected_sprite_info = QLineEdit()
        self.selected_sprite_info.setReadOnly(True)
        bsp.addWidget(self.selected_sprite_info)
        self._play_v = QPushButton(tr_i18n("char.play_voice"))
        self._play_v.clicked.connect(self._on_play_voice)
        bsp.addWidget(self._play_v, alignment=Qt.AlignmentFlag.AlignLeft)
        self.sprite_voice_path = QLineEdit()
        self.sprite_voice_path.setPlaceholderText(tr_i18n("char.ph_vpath"))
        self.sprite_voice_path.setReadOnly(True)
        bsp.addWidget(self.sprite_voice_path)
        self.sprite_voice_text = QLineEdit()
        self.sprite_voice_text.setPlaceholderText(tr_i18n("char.ph_vtext"))
        bsp.addWidget(self.sprite_voice_text)
        vr = QHBoxLayout()
        self.voice_upload_path = QLineEdit()
        self._bvw = QPushButton(tr_i18n("char.pick_voice"))
        self._bvw.clicked.connect(self._pick_voice)
        vr.addWidget(self.voice_upload_path, stretch=1)
        vr.addWidget(self._bvw)
        bsp.addLayout(vr)
        self._upload_voice_btn = QPushButton(tr_i18n("char.upload_voice"))
        self._upload_voice_btn.clicked.connect(self._on_upload_voice)
        bsp.addWidget(self._upload_voice_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self._box_sprites)

        scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(scroll, 1)

        # --- 底部固定栏：保存人物 ---
        self._save_footer = QWidget()
        sfl = QVBoxLayout(self._save_footer)
        sfl.setContentsMargins(0, 4, 0, 0)
        sfl.setSpacing(4)
        foot_sep = QFrame()
        foot_sep.setFrameShape(QFrame.Shape.HLine)
        foot_sep.setFrameShadow(QFrame.Shadow.Sunken)
        sfl.addWidget(foot_sep)
        self._box_save = QGroupBox(tr_i18n("char.save_box"))
        bs = QVBoxLayout(self._box_save)
        self._add_btn = QPushButton(tr_i18n("char.add_save"))
        self._add_btn.clicked.connect(self._on_add)
        bs.addWidget(self._add_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        sfl.addWidget(self._box_save)
        root.addWidget(self._save_footer, 0)

        self.selected_character.currentTextChanged.connect(self._on_character_change)
        self._refresh_character_combo()
        self._on_character_change(self.selected_character.currentText())

    def _is_new_char(self, name: str) -> bool:
        return not name or name == tr_i18n("char.combo_new")

    def apply_i18n(self) -> None:
        self._h2.setText(tr_i18n("char.h2"))
        self._box_files.setTitle(tr_i18n("char.file_box"))
        self._lbl_current_char.setText(tr_i18n("char.row_current"))
        self._export_btn.setText(tr_i18n("char.export"))
        self._del_char_btn.setText(tr_i18n("char.delete"))
        self._import_lbl.setText(tr_i18n("char.import_lbl"))
        self.import_files_display.setPlaceholderText(tr_i18n("char.ph_no_file"))
        self._pick_files_btn.setText(tr_i18n("char.pick_file"))
        self._import_btn.setText(tr_i18n("char.import"))
        self._box_info.setTitle(tr_i18n("char.info_box"))
        self.char_color.setPlaceholderText(tr_i18n("char.ph_color"))
        self._f_name.setText(tr_i18n("char.name"))
        self._f_color.setText(tr_i18n("char.color"))
        self._b_pick_color.setText(tr_i18n("char.pick_color"))
        self._b_pick_color.setToolTip(tr_i18n("char.tt_pick_color"))
        self._f_prefix.setText(tr_i18n("char.sprite_dir"))
        self._setting_lbl.setText(tr_i18n("char.setting_lbl"))
        self._ai_btn.setText(tr_i18n("char.ai_write"))
        self._ai_translate_btn.setText(tr_i18n("char.ai_translate"))
        self._ai_translate_btn.setToolTip(tr_i18n("char.tt_ai_translate"))
        self._voice_box.setTitle(tr_i18n("char.voice_box"))
        self._v_gpt.setText(tr_i18n("char.gpt_path"))
        self._v_sov.setText(tr_i18n("char.sovits_path"))
        self._v_ref.setText(tr_i18n("char.ref_audio"))
        self._v_pt.setText(tr_i18n("char.ref_text"))
        self._v_pl.setText(tr_i18n("char.prompt_lang"))
        self._box_save.setTitle(tr_i18n("char.save_box"))
        self._add_btn.setText(tr_i18n("char.add_save"))
        self._h2s.setText(tr_i18n("char.h2_sprites"))
        self._box_sprites.setTitle(tr_i18n("char.sprite_box"))
        self._b_up.setText(tr_i18n("char.pick_sprites"))
        self._upload_sprites_btn.setText(tr_i18n("char.upload_img"))
        self._scale_lbl.setText(tr_i18n("char.scale_lbl"))
        self._scale_save.setText(tr_i18n("char.save_scale"))
        self._scale_save.setToolTip(tr_i18n("char.tt_scale"))
        self._del_all_sp.setText(tr_i18n("char.del_all_sp"))
        self._gal_lbl.setText(tr_i18n("char.gal_lbl"))
        self._del_one.setText(tr_i18n("char.del_one"))
        self._emo_lbl.setText(tr_i18n("char.emo_lbl"))
        self._tag_btn.setText(tr_i18n("char.upload_tags"))
        self._voice_title.setText(tr_i18n("char.voice_title"))
        self.sprite_voice_path.setPlaceholderText(tr_i18n("char.ph_vpath"))
        self.sprite_voice_text.setPlaceholderText(tr_i18n("char.ph_vtext"))
        self._play_v.setText(tr_i18n("char.play_voice"))
        self._bvw.setText(tr_i18n("char.pick_voice"))
        self._upload_voice_btn.setText(tr_i18n("char.upload_voice"))
        self._refresh_character_combo(self.selected_character.currentText())
        self._update_sprite_side_info()

    def _current_char(self) -> str:
        return self.selected_character.currentText().strip()

    def _refresh_character_combo(self, select: str | None = None) -> None:
        self.selected_character.blockSignals(True)
        self.selected_character.clear()
        self.selected_character.addItem(tr_i18n("char.combo_new"))
        for n in self._ctx.character_manager.get_character_name_list():
            self.selected_character.addItem(n)
            idx = self.selected_character.count() - 1
            ch = self._ctx.config_manager.get_character_by_name(n)
            raw = (ch.color or _DEFAULT_NAME_COLOR) if ch else _DEFAULT_NAME_COLOR
            q = _parse_color_text(str(raw).strip())
            self.selected_character.setItemData(
                idx, QBrush(q), Qt.ItemDataRole.ForegroundRole
            )
        if select:
            idx = self.selected_character.findText(select)
            if idx >= 0:
                self.selected_character.setCurrentIndex(idx)
        self.selected_character.blockSignals(False)

    def _fill_character(self, name: str) -> None:
        c = self._ctx.config_manager.get_character_by_name(name)
        if c is None:
            self.char_name.clear()
            self.char_color.setText(_DEFAULT_NAME_COLOR)
            self._update_color_swatch()
            self.sprite_prefix.setText("temp")
            for w in (self.gpt_model_path, self.sovits_model_path, self.refer_audio_path, self.prompt_text, self.prompt_lang):
                w.clear()
            self.character_setting.clear()
            return
        self.char_name.setText(c.name)
        self.char_color.setText(c.color or _DEFAULT_NAME_COLOR)
        self._update_color_swatch()
        self.sprite_prefix.setText(c.sprite_prefix or "temp")
        self.gpt_model_path.setText(c.gpt_model_path or "")
        self.sovits_model_path.setText(c.sovits_model_path or "")
        self.refer_audio_path.setText(c.refer_audio_path or "")
        self.prompt_text.setText(c.prompt_text or "")
        self.prompt_lang.setText(c.prompt_lang or "")
        self.speech_speed.setValue(float(c.speech_speed) if c.speech_speed else 1.0)
        self.character_setting.setPlainText(c.character_setting or "")

    def _on_character_change(self, name: str) -> None:
        if self._is_new_char(name):
            self._fill_character("")
        else:
            self._fill_character(name)
        paths, emo, _ = self._ctx.character_manager.get_character_sprites(name) if name and not self._is_new_char(name) else ([], "", [])
        self._load_gallery(paths)
        self.emotion_inputs.setPlainText(emo)
        ch = self._ctx.config_manager.get_character_by_name(name) if name and not self._is_new_char(name) else None
        self.sprite_scale.setValue(float(ch.sprite_scale) if ch else 1.0)
        self._sprite_paths.clear()
        self.sprite_files_display.clear()
        sync_gallery_to_tag_cursor(self.sprites_gallery, self.emotion_inputs)
        self._update_sprite_side_info()

    def _load_gallery(self, paths: list[str]) -> None:
        self.sprites_gallery.clear()
        for p in paths:
            if not p or not Path(p).exists():
                continue
            pix = QPixmap(p)
            if not pix.isNull():
                it = QListWidgetItem(
                    QIcon(
                        pix.scaled(
                            GALLERY_THUMB_PX,
                            GALLERY_THUMB_PX,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    ),
                    Path(p).name,
                )
                it.setData(Qt.ItemDataRole.UserRole, p)
                self.sprites_gallery.addItem(it)

    def _on_sprite_row(self) -> None:
        self._update_sprite_side_info()

    def _on_emotion_tag_cursor_moved(self) -> None:
        sync_gallery_to_tag_cursor(self.sprites_gallery, self.emotion_inputs)

    def _selected_sprite_index(self) -> int | None:
        r = self.sprites_gallery.currentRow()
        if r < 0:
            return None
        return r

    def _update_sprite_side_info(self) -> None:
        name = self._current_char()
        idx = self._selected_sprite_index()
        if self._is_new_char(name) or idx is None:
            self.selected_sprite_info.setText(tr_i18n("char.ph_no_sprite"))
            self.sprite_voice_path.clear()
            self.sprite_voice_text.clear()
            return
        vpath, vtext = self._ctx.character_manager.get_sprite_voice(name, idx)
        self.selected_sprite_info.setText(
            tr_i18n("char.sprite_info", n=idx + 1)
            + (tr_i18n("char.has_voice") if vpath else tr_i18n("char.no_voice"))
        )
        self.sprite_voice_path.setText(vpath or "")
        self.sprite_voice_text.setText(vtext or "")

    def _qcolor_for_char_field(self) -> QColor:
        return _parse_color_text(self.char_color.text() or _DEFAULT_NAME_COLOR)

    def _update_color_swatch(self) -> None:
        c = _parse_color_text(self.char_color.text() or _DEFAULT_NAME_COLOR)
        a = c.alphaF()
        self._color_swatch.setStyleSheet(
            f"background-color: rgba({c.red()},{c.green()},{c.blue()},{a:.3f}); "
            f"border: 1px solid #888;"
        )

    def _on_char_color_text_changed(self, _text: str) -> None:
        self._update_color_swatch()

    def _on_pick_color(self) -> None:
        cur = self._qcolor_for_char_field()
        picked = QColorDialog.getColor(
            cur,
            self,
            tr_i18n("char.color"),
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if picked.isValid():
            self.char_color.setText(_format_color_text(picked))

    def _set_io_widgets_enabled(self, enabled: bool) -> None:
        self._export_btn.setEnabled(enabled)
        self._import_btn.setEnabled(enabled)
        self._pick_files_btn.setEnabled(enabled)
        self._b_pick_color.setEnabled(enabled)

    def _on_export(self) -> None:
        name = self._current_char()
        if self._is_new_char(name):
            message_fail(self, "导出", "请选择有效角色")
            return
        c = self._ctx.config_manager.get_character_by_name(name)
        if c is None:
            message_fail(self, "导出", "人物不存在")
            return

        def work() -> None:
            Path("./output").mkdir(parents=True, exist_ok=True)
            ch = CharacterConfig.parse_dic(char_data=c.__dict__)
            fu.export_character([ch], output_path=f"./output/{c.name}.char")

        def on_ok(_: object) -> None:
            self._set_io_widgets_enabled(True)
            toast_success(self, "导出", "导出成功")

        def on_fail(msg: str) -> None:
            self._set_io_widgets_enabled(True)
            message_fail(self, "导出", f"导出失败: {msg}")

        self._set_io_widgets_enabled(False)
        run_ai_task_with_progress(
            self,
            tr_i18n("char.export"),
            tr_i18n("char.progress_export"),
            work,
            on_ok,
            on_fail,
        )

    def _pick_import_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, tr_i18n("char.dlg_import"), "", "Character (*.char);;All (*)"
        )
        self._import_paths = list(files)
        self.import_files_display.setText("; ".join(Path(p).name for p in self._import_paths))

    def _on_import(self) -> None:
        if not self._import_paths:
            message_fail(self, "导入", "请先选择文件")
            return
        paths = list(self._import_paths)

        def work() -> tuple[int, list[str], str | None]:
            success = 0
            err: list[str] = []
            last_imported_name: str | None = None
            for p in paths:
                try:
                    cfgs = fu.import_character(p)
                    success += 1
                    if cfgs:
                        last_imported_name = cfgs[-1].name
                except Exception as e:
                    err.append(f"{os.path.basename(p)}: {e}")
            return success, err, last_imported_name

        def on_ok(res: object) -> None:
            self._set_io_widgets_enabled(True)
            success, err, last_name = res  # type: ignore[misc]
            self._ctx.config_manager.reload()
            msg = f"成功导入 {success} 个角色。"
            if err:
                msg += "\n" + "\n".join(err)
                message_fail(self, "导入", msg)
            else:
                toast_success(self, "导入", msg)
            # 选中新导入人物：多文件时以最后一次成功导入的文件中最后一个角色为准
            self._refresh_character_combo(last_name if last_name else None)
            self._on_character_change(self.selected_character.currentText())
            self.character_list_changed.emit()

        def on_fail(msg: str) -> None:
            self._set_io_widgets_enabled(True)
            message_fail(self, "导入", f"导入失败: {msg}")

        self._set_io_widgets_enabled(False)
        run_ai_task_with_progress(
            self,
            tr_i18n("char.import"),
            tr_i18n("char.progress_import"),
            work,
            on_ok,
            on_fail,
        )

    def _on_add(self) -> None:
        sel = self.selected_character.currentText().strip()
        edit_as: str | None = None
        if not self._is_new_char(sel):
            edit_as = sel
        msg, _ = self._ctx.character_manager.add_character(
            self.char_name.text().strip(),
            self.char_color.text().strip() or _DEFAULT_NAME_COLOR,
            self.sprite_prefix.text().strip() or "temp",
            self.gpt_model_path.text().strip(),
            self.sovits_model_path.text().strip(),
            self.refer_audio_path.text().strip(),
            self.prompt_text.text().strip(),
            self.prompt_lang.text().strip(),
            self.character_setting.toPlainText().strip(),
            speech_speed=self.speech_speed.value(),
            edit_as_name=edit_as,
        )
        feedback_result(self, "人物", msg)
        self._refresh_character_combo(self.char_name.text().strip())
        self.character_list_changed.emit()

    def _on_delete(self) -> None:
        name = self._current_char()
        msg, _ = self._ctx.character_manager.delete_character(name)
        feedback_result(self, "人物", msg)
        self._refresh_character_combo(tr_i18n("char.combo_new"))
        self._on_character_change(tr_i18n("char.combo_new"))
        self.character_list_changed.emit()

    def _on_ai_help(self) -> None:
        name = self.char_name.text().strip()
        setting_text = self.character_setting.toPlainText()

        def work() -> tuple[str, str]:
            return self._ctx.character_manager.generate_character_setting(name, setting_text)

        def on_ok(res: tuple[str, str]) -> None:
            self._ai_btn.setEnabled(True)
            out, setting = res
            self.character_setting.setPlainText(setting)
            if is_failure_message(out):
                message_fail(self, "AI 帮写", out)
            else:
                body = (out or "").strip()
                if len(body) > 500:
                    body = body[:500] + "…"
                toast_success(self, "AI 帮写", body or "已更新角色设定")

        def on_fail(msg: str) -> None:
            self._ai_btn.setEnabled(True)
            message_fail(self, "AI 帮写", msg)

        self._ai_btn.setEnabled(False)
        run_ai_task_with_progress(
            self,
            tr_i18n("common.ai_working_title"),
            tr_i18n("common.ai_progress_write"),
            work,
            on_ok,
            on_fail,
        )

    def _on_ai_translate(self) -> None:
        code = str(self._ctx.config_manager.config.system_config.ui_language)
        name = self.char_name.text().strip()
        emo = self.emotion_inputs.toPlainText()
        cset = self.character_setting.toPlainText()

        def work() -> tuple[str, str, str, str]:
            return translate_character_name_and_tags(
                self._ctx.config_manager,
                code,
                name,
                emo,
                cset,
            )

        def on_ok(res: tuple[str, str, str, str]) -> None:
            self._ai_translate_btn.setEnabled(True)
            err, t_name, t_emo, t_setting = res
            if err == "no_content":
                message_fail(
                    self, tr_i18n("char.msg_translate_title"), tr_i18n("char.msg_translate_empty")
                )
            elif err == "llm_incomplete":
                message_fail(
                    self, tr_i18n("char.msg_translate_title"), tr_i18n("char.msg_translate_llm")
                )
            elif err:
                message_fail(
                    self,
                    tr_i18n("char.msg_translate_title"),
                    tr_i18n("char.msg_translate_fail", detail=err),
                )
            else:
                self.char_name.setText(t_name)
                self.emotion_inputs.setPlainText(t_emo)
                self.character_setting.setPlainText(t_setting)
                sync_gallery_to_tag_cursor(self.sprites_gallery, self.emotion_inputs)
                toast_success(
                    self,
                    tr_i18n("char.msg_translate_title"),
                    tr_i18n("char.toast_translate_ok"),
                )

        def on_fail(msg: str) -> None:
            self._ai_translate_btn.setEnabled(True)
            message_fail(
                self,
                tr_i18n("char.msg_translate_title"),
                tr_i18n("char.msg_translate_fail", detail=msg),
            )

        self._ai_translate_btn.setEnabled(False)
        run_ai_task_with_progress(
            self,
            tr_i18n("common.ai_working_title"),
            tr_i18n("common.ai_progress_translate"),
            work,
            on_ok,
            on_fail,
        )

    def _pick_sprites(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, tr_i18n("char.dlg_sprites"), "", "Images (*.png *.jpg *.jpeg *.webp);;All (*)"
        )
        self._sprite_paths = list(files)
        self.sprite_files_display.setText(f"{len(self._sprite_paths)} 个文件")

    def _on_upload_sprites(self) -> None:
        name = self._current_char()
        if not self._sprite_paths:
            message_fail(self, "立绘", "请选择要上传的图片")
            return
        msg, paths, emo = self._ctx.character_manager.upload_sprites(
            name,
            path_file_list(self._sprite_paths),
            self.emotion_inputs.toPlainText(),
        )
        feedback_result(self, "立绘", msg)
        self._load_gallery(paths)
        self.emotion_inputs.setPlainText(emo)
        sync_gallery_to_tag_cursor(self.sprites_gallery, self.emotion_inputs)
        self._refresh_character_combo(name)
        self.character_list_changed.emit()

    def _on_save_scale(self) -> None:
        msg = self._ctx.character_manager.save_sprite_scale(self._current_char(), self.sprite_scale.value())
        feedback_result(self, "立绘", msg)

    def _on_delete_all_sprites(self) -> None:
        msg, paths, emo = self._ctx.character_manager.delete_all_sprites(self._current_char())
        feedback_result(self, "立绘", msg)
        self._load_gallery(paths)
        self.emotion_inputs.setPlainText(emo)
        sync_gallery_to_tag_cursor(self.sprites_gallery, self.emotion_inputs)
        self.character_list_changed.emit()

    def _on_delete_one_sprite(self) -> None:
        idx = self._selected_sprite_index()
        if idx is None:
            return
        msg, paths, emo = self._ctx.character_manager.delete_single_sprite(self._current_char(), idx)
        feedback_result(self, "立绘", msg)
        self._load_gallery(paths)
        self.emotion_inputs.setPlainText(emo)
        sync_gallery_to_tag_cursor(self.sprites_gallery, self.emotion_inputs)
        self._update_sprite_side_info()
        self.character_list_changed.emit()

    def _on_upload_tags(self) -> None:
        msg = self._ctx.character_manager.upload_emotion_tags(
            self._current_char(), self.emotion_inputs.toPlainText()
        )
        feedback_result(self, "立绘", msg)

    def _pick_voice(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr_i18n("char.dlg_voice"), "", "Audio (*.wav *.mp3 *.ogg);;All (*)"
        )
        if path:
            self.voice_upload_path.setText(path)

    def _on_play_voice(self) -> None:
        p = self.sprite_voice_path.text().strip()
        if not p or not Path(p).is_file():
            message_fail(self, "播放", "无有效语音文件")
            return
        if not self._player:
            message_fail(
                self, "播放", tr_i18n("common.msg_qtmm_unavailable")
            )
            return
        self._player.setSource(QUrl.fromLocalFile(Path(p).resolve().as_posix()))
        self._player.play()

    def _on_upload_voice(self) -> None:
        vfile = self.voice_upload_path.text().strip()
        if not vfile:
            message_fail(self, "语音", "请选择语音文件")
            return
        idx = self._selected_sprite_index()
        if idx is None:
            message_fail(self, "语音", "请先选择立绘")
            return
        msg, vpath = self._ctx.character_manager.upload_voice(
            self._current_char(), idx, vfile, self.sprite_voice_text.text()
        )
        feedback_result(self, "语音", msg)
        if vpath:
            self.sprite_voice_path.setText(vpath)
        self._update_sprite_side_info()
        self.character_list_changed.emit()
