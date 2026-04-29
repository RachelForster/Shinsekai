"""小工具标签页（PyQt）。"""

from __future__ import annotations

import re
from pathlib import Path

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
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
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from i18n import tr as tr_i18n
from tools.crop_sprite import batch_crop_upper_half
from tools.remove_bg import batch_remove_background
from core.plugins.plugin_host import collect_tools_tab_contributions
from sdk.plugin_host_context import PluginSettingsUIContext
from ui.settings_ui.context import SettingsUIContext
from ui.settings_ui.utils import GALLERY_THUMB_PX


def _extract_prompt_from_line(line: str) -> str:
    """从「立绘 1：…」/「Sprite 1: …」等行中取出提示词部分。"""
    s = line.strip()
    if not s:
        return ""
    m = re.match(r"^[^:]+[:：]\s*(.+)$", s)
    if m:
        return m.group(1).strip()
    return s


class ToolsSettingsTab(QWidget):
    def __init__(self, ctx: SettingsUIContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._build_ui()
        self.refresh_characters()

    def _t(self, key: str, **kwargs) -> str:
        return tr_i18n(f"tools.{key}", **kwargs)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self._tabs = QTabWidget()
        root.addWidget(self._tabs)
        builtin_page = QWidget()
        builtin_layout = QVBoxLayout(builtin_page)
        builtin_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner)

        self._h2 = QLabel()
        lay.addWidget(self._h2)

        self.gem_box = QGroupBox()
        gv = QVBoxLayout(self.gem_box)
        self._gem_hint = QLabel()
        gv.addWidget(self._gem_hint)
        gr = QHBoxLayout()
        col1 = QVBoxLayout()
        self.character_generate = QComboBox()
        self._lbl_char = QLabel()
        col1.addWidget(self._lbl_char)
        col1.addWidget(self.character_generate)
        self.sprite_num = QSpinBox()
        self.sprite_num.setRange(1, 100)
        self.sprite_num.setValue(1)
        self._lbl_count = QLabel()
        col1.addWidget(self._lbl_count)
        col1.addWidget(self.sprite_num)
        self.gen_prompt_btn = QPushButton()
        self.gen_prompt_btn.clicked.connect(self._on_gen_prompts)
        col1.addWidget(self.gen_prompt_btn)
        self.ref_pic_path = QLineEdit()
        self.pick_ref = QPushButton()
        self.pick_ref.clicked.connect(self._pick_ref)
        rr = QHBoxLayout()
        rr.addWidget(self.ref_pic_path)
        rr.addWidget(self.pick_ref)
        self._lbl_ref = QLabel()
        col1.addWidget(self._lbl_ref)
        col1.addLayout(rr)
        gr.addLayout(col1)

        col2 = QVBoxLayout()
        self.sprite_prompts = QPlainTextEdit()
        self.sprite_prompts.setMinimumHeight(120)
        col2.addWidget(self.sprite_prompts)
        self.sprite_output_dir = QLineEdit()
        col2.addWidget(self.sprite_output_dir)
        self.gen_sp_btn = QPushButton()
        self.gen_sp_btn.clicked.connect(self._on_gen_sprites)
        col2.addWidget(self.gen_sp_btn)
        gr.addLayout(col2)

        col3 = QVBoxLayout()
        self.sprites_gallery = QListWidget()
        self.sprites_gallery.setViewMode(QListWidget.ViewMode.IconMode)
        self.sprites_gallery.setIconSize(QSize(GALLERY_THUMB_PX, GALLERY_THUMB_PX))
        self.sprites_gallery.setSpacing(8)
        self.sprites_gallery.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.sprites_gallery.setMinimumHeight(400)
        self._lbl_gallery = QLabel()
        col3.addWidget(self._lbl_gallery)
        col3.addWidget(self.sprites_gallery)
        gr.addLayout(col3)
        gv.addLayout(gr)
        lay.addWidget(self.gem_box)

        crop_row = QHBoxLayout()
        crop_col = QVBoxLayout()
        self._crop_h3 = QLabel()
        crop_col.addWidget(self._crop_h3)
        self.crop_input = QLineEdit()
        self.crop_output = QLineEdit()
        self.crop_ratio = QDoubleSpinBox()
        self.crop_ratio.setRange(0.0, 1.0)
        self.crop_ratio.setSingleStep(0.05)
        self.crop_ratio.setValue(1.0)
        self._crop_in = QLabel()
        self._crop_out = QLabel()
        self._crop_ratio = QLabel()
        crop_col.addWidget(self._crop_in)
        crop_col.addWidget(self.crop_input)
        crop_col.addWidget(self._crop_out)
        crop_col.addWidget(self.crop_output)
        crop_col.addWidget(self._crop_ratio)
        crop_col.addWidget(self.crop_ratio)
        self.crop_btn = QPushButton()
        self.crop_btn.clicked.connect(self._on_crop)
        crop_col.addWidget(self.crop_btn)
        crop_row.addLayout(crop_col)

        rmbg_col = QVBoxLayout()
        self._rmbg_h3 = QLabel()
        rmbg_col.addWidget(self._rmbg_h3)
        self._rmbg_first = QLabel()
        rmbg_col.addWidget(self._rmbg_first)
        self.rmbg_input = QLineEdit()
        self.rmbg_output = QLineEdit()
        self._rmbg_in = QLabel()
        self._rmbg_out = QLabel()
        rmbg_col.addWidget(self._rmbg_in)
        rmbg_col.addWidget(self.rmbg_input)
        rmbg_col.addWidget(self._rmbg_out)
        rmbg_col.addWidget(self.rmbg_output)
        self.rmbg_btn = QPushButton()
        self.rmbg_btn.clicked.connect(self._on_rmbg)
        rmbg_col.addWidget(self.rmbg_btn)
        crop_row.addLayout(rmbg_col)
        lay.addLayout(crop_row)

        self.tool_output = QPlainTextEdit()
        self.tool_output.setReadOnly(True)
        self.tool_output.setMaximumHeight(120)
        lay.addWidget(self.tool_output)

        builtin_layout.addWidget(scroll)
        self._tabs.addTab(builtin_page, self._t("tab_main"))
        for contrib in collect_tools_tab_contributions():
            plg = PluginSettingsUIContext.from_settings_ui_context(self._ctx)
            self._tabs.addTab(contrib.build(plg), contrib.title)
        # refresh_characters 在 apply_i18n 之后由 __init__ 调用

    def apply_i18n(self) -> None:
        if getattr(self, "_tabs", None) is not None and self._tabs.count():
            self._tabs.setTabText(0, self._t("tab_main"))
        self._h2.setText(self._t("h2_sprites"))
        self.gem_box.setTitle(self._t("gem_box"))
        self._gem_hint.setText(self._t("gem_hint"))
        self._lbl_char.setText(self._t("char"))
        self._lbl_count.setText(self._t("sprite_count"))
        self.gen_prompt_btn.setText(self._t("gen_prompts_btn"))
        self.ref_pic_path.setPlaceholderText(self._t("ref_ph"))
        self.pick_ref.setText(self._t("browse"))
        self._lbl_ref.setText(self._t("ref_label"))
        self.sprite_prompts.setPlaceholderText(self._t("prompts_ph"))
        self.sprite_output_dir.setPlaceholderText(self._t("out_dir_ph"))
        self.gen_sp_btn.setText(self._t("gen_sprites_btn"))
        self._lbl_gallery.setText(self._t("gallery_lbl"))
        self._crop_h3.setText(self._t("crop_h3"))
        self._crop_in.setText(self._t("crop_in"))
        self._crop_out.setText(self._t("crop_out"))
        self._crop_ratio.setText(self._t("crop_ratio"))
        self.crop_btn.setText(self._t("crop_btn"))
        self._rmbg_h3.setText(self._t("rmbg_h3"))
        self._rmbg_first.setText(self._t("rmbg_first"))
        self._rmbg_in.setText(self._t("rmbg_in"))
        self._rmbg_out.setText(self._t("rmbg_out"))
        self.rmbg_btn.setText(self._t("rmbg_btn"))

    def refresh_characters(self) -> None:
        self.character_generate.clear()
        self.character_generate.addItems(self._ctx.character_manager.get_character_name_list())

    def _pick_ref(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self._t("dlg_ref_title"),
            "",
            "Images (*.png *.jpg *.jpeg);;All (*)",
        )
        if path:
            self.ref_pic_path.setText(path)

    def _on_gen_prompts(self) -> None:
        name = self.character_generate.currentText()
        if not name:
            QMessageBox.warning(
                self, self._t("msg_title_prompts"), self._t("msg_select_char")
            )
            return
        char = self._ctx.config_manager.get_character_by_name(name)
        if not char:
            QMessageBox.warning(
                self, self._t("msg_title_prompts"), self._t("msg_no_char")
            )
            return
        prompts = self._ctx.image_generator.generate_prompts(
            self.sprite_num.value(), char.character_setting
        )
        lines = "\n".join(
            self._t("prompt_line", n=i + 1, text=p) for i, p in enumerate(prompts)
        )
        self.sprite_prompts.setPlainText(lines)

    def _on_gen_sprites(self) -> None:
        name = self.character_generate.currentText()
        if not name:
            QMessageBox.warning(
                self, self._t("msg_title_gen"), self._t("msg_select_char")
            )
            return
        ref = self.ref_pic_path.text().strip()
        if not ref or not Path(ref).is_file():
            QMessageBox.warning(
                self, self._t("msg_title_gen"), self._t("msg_ref_invalid")
            )
            return
        raw = self.sprite_prompts.toPlainText().strip()
        prompt_list = [
            p
            for p in (
                _extract_prompt_from_line(line) for line in raw.split("\n")
            )
            if p
        ]
        if not prompt_list:
            QMessageBox.warning(
                self, self._t("msg_title_gen"), self._t("msg_no_prompts")
            )
            return
        out_dir = self.sprite_output_dir.text().strip()
        if not out_dir:
            out_dir = Path("data/sprite") / self._ctx.config_manager.get_character_by_name(
                name
            ).sprite_prefix
        try:
            files = self._ctx.image_generator.batch_generate_sprites(
                ref, prompt_list, out_dir
            )
        except Exception as e:
            self.tool_output.setPlainText(self._t("msg_gen_fail", e=str(e)))
            return
        self.sprites_gallery.clear()
        for p in files:
            if p and Path(p).exists():
                pix = QPixmap(str(p))
                if not pix.isNull():
                    item = QListWidgetItem(
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
                    item.setData(Qt.ItemDataRole.UserRole, str(p))
                    self.sprites_gallery.addItem(item)
        self.tool_output.setPlainText(
            self._t("msg_gen_ok", n=len(files), dir=str(out_dir))
        )

    def _on_crop(self) -> None:
        out = self.crop_output.text().strip() or None
        msg = batch_crop_upper_half(
            self.crop_ratio.value(),
            self.crop_input.text().strip(),
            out,
        )
        self.tool_output.setPlainText(str(msg))

    def _on_rmbg(self) -> None:
        msg = batch_remove_background(
            self.rmbg_input.text().strip(), self.rmbg_output.text().strip()
        )
        self.tool_output.setPlainText(str(msg))
