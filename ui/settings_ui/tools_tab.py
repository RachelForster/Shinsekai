"""小工具标签页（PyQt）。"""

from __future__ import annotations

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
    QVBoxLayout,
    QWidget,
)

from tools.crop_sprite import batch_crop_upper_half
from tools.remove_bg import batch_remove_background
from ui.settings_ui.context import SettingsUIContext


class ToolsSettingsTab(QWidget):
    def __init__(self, ctx: SettingsUIContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner)

        lay.addWidget(QLabel("<h2>立绘处理</h2>"))

        gem_box = QGroupBox("批量自动生成立绘（需配置 Gemini API Key）")
        gv = QVBoxLayout(gem_box)
        gv.addWidget(QLabel("需要 Gemini API Key。也可使用官方免费界面生成。"))
        gr = QHBoxLayout()
        col1 = QVBoxLayout()
        self.character_generate = QComboBox()
        col1.addWidget(QLabel("角色"))
        col1.addWidget(self.character_generate)
        self.sprite_num = QSpinBox()
        self.sprite_num.setRange(1, 100)
        self.sprite_num.setValue(1)
        col1.addWidget(QLabel("生成立绘数量"))
        col1.addWidget(self.sprite_num)
        gen_prompt_btn = QPushButton("生成立绘提示词")
        gen_prompt_btn.clicked.connect(self._on_gen_prompts)
        col1.addWidget(gen_prompt_btn)
        self.ref_pic_path = QLineEdit()
        self.ref_pic_path.setPlaceholderText("参考图片路径")
        pick_ref = QPushButton("浏览…")
        pick_ref.clicked.connect(self._pick_ref)
        rr = QHBoxLayout()
        rr.addWidget(self.ref_pic_path)
        rr.addWidget(pick_ref)
        col1.addWidget(QLabel("参考图片"))
        col1.addLayout(rr)
        gr.addLayout(col1)

        col2 = QVBoxLayout()
        self.sprite_prompts = QPlainTextEdit()
        self.sprite_prompts.setPlaceholderText("立绘提示词，一行一个")
        self.sprite_prompts.setMinimumHeight(120)
        col2.addWidget(self.sprite_prompts)
        self.sprite_output_dir = QLineEdit()
        self.sprite_output_dir.setPlaceholderText("输出目录，默认可留空")
        col2.addWidget(self.sprite_output_dir)
        gen_sp_btn = QPushButton("批量生成立绘")
        gen_sp_btn.clicked.connect(self._on_gen_sprites)
        col2.addWidget(gen_sp_btn)
        gr.addLayout(col2)

        col3 = QVBoxLayout()
        self.sprites_gallery = QListWidget()
        self.sprites_gallery.setViewMode(QListWidget.ViewMode.IconMode)
        self.sprites_gallery.setIconSize(QSize(120, 120))
        self.sprites_gallery.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.sprites_gallery.setMinimumHeight(200)
        col3.addWidget(QLabel("已生成的立绘"))
        col3.addWidget(self.sprites_gallery)
        gr.addLayout(col3)
        gv.addLayout(gr)
        lay.addWidget(gem_box)

        crop_row = QHBoxLayout()
        crop_col = QVBoxLayout()
        crop_col.addWidget(QLabel("<h3>批量裁剪立绘</h3>"))
        self.crop_input = QLineEdit()
        self.crop_output = QLineEdit()
        self.crop_ratio = QDoubleSpinBox()
        self.crop_ratio.setRange(0.0, 1.0)
        self.crop_ratio.setSingleStep(0.05)
        self.crop_ratio.setValue(1.0)
        crop_col.addWidget(QLabel("输入目录"))
        crop_col.addWidget(self.crop_input)
        crop_col.addWidget(QLabel("输出目录（可空）"))
        crop_col.addWidget(self.crop_output)
        crop_col.addWidget(QLabel("保留上半部分比例"))
        crop_col.addWidget(self.crop_ratio)
        crop_btn = QPushButton("确认裁剪")
        crop_btn.clicked.connect(self._on_crop)
        crop_col.addWidget(crop_btn)
        crop_row.addLayout(crop_col)

        rmbg_col = QVBoxLayout()
        rmbg_col.addWidget(QLabel("<h3>批量抠出立绘</h3>"))
        rmbg_col.addWidget(QLabel("首次可能自动下载模型，耗时较长。"))
        self.rmbg_input = QLineEdit()
        self.rmbg_output = QLineEdit()
        rmbg_col.addWidget(QLabel("输入目录"))
        rmbg_col.addWidget(self.rmbg_input)
        rmbg_col.addWidget(QLabel("输出目录（可空）"))
        rmbg_col.addWidget(self.rmbg_output)
        rmbg_btn = QPushButton("确认处理")
        rmbg_btn.clicked.connect(self._on_rmbg)
        rmbg_col.addWidget(rmbg_btn)
        crop_row.addLayout(rmbg_col)
        lay.addLayout(crop_row)

        self.tool_output = QPlainTextEdit()
        self.tool_output.setReadOnly(True)
        self.tool_output.setMaximumHeight(120)
        lay.addWidget(self.tool_output)

        root.addWidget(scroll)
        self.refresh_characters()

    def refresh_characters(self) -> None:
        self.character_generate.clear()
        self.character_generate.addItems(self._ctx.character_manager.get_character_name_list())

    def _pick_ref(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "参考图片", "", "Images (*.png *.jpg *.jpeg);;All (*)")
        if path:
            self.ref_pic_path.setText(path)

    def _on_gen_prompts(self) -> None:
        name = self.character_generate.currentText()
        if not name:
            QMessageBox.warning(self, "提示词", "请选择角色")
            return
        char = self._ctx.config_manager.get_character_by_name(name)
        if not char:
            QMessageBox.warning(self, "提示词", "角色不存在")
            return
        prompts = self._ctx.image_generator.generate_prompts(self.sprite_num.value(), char.character_setting)
        lines = "\n".join(f"立绘 {i + 1}：{p}" for i, p in enumerate(prompts))
        self.sprite_prompts.setPlainText(lines)

    def _on_gen_sprites(self) -> None:
        name = self.character_generate.currentText()
        if not name:
            QMessageBox.warning(self, "生成", "请选择角色")
            return
        ref = self.ref_pic_path.text().strip()
        if not ref or not Path(ref).is_file():
            QMessageBox.warning(self, "生成", "请选择有效的参考图片")
            return
        raw = self.sprite_prompts.toPlainText().strip()
        prompt_list = [line.split("：", 1)[-1].strip() if "：" in line else line.strip() for line in raw.split("\n") if line.strip()]
        if not prompt_list:
            QMessageBox.warning(self, "生成", "请输入提示词")
            return
        out_dir = self.sprite_output_dir.text().strip()
        if not out_dir:
            out_dir = Path("data/sprite") / self._ctx.config_manager.get_character_by_name(name).sprite_prefix
        try:
            files = self._ctx.image_generator.batch_generate_sprites(ref, prompt_list, out_dir)
        except Exception as e:
            self.tool_output.setPlainText(f"生成失败: {e}")
            return
        self.sprites_gallery.clear()
        for p in files:
            if p and Path(p).exists():
                pix = QPixmap(str(p))
                if not pix.isNull():
                    item = QListWidgetItem(
                        QIcon(
                            pix.scaled(
                                120,
                                120,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                        ),
                        Path(p).name,
                    )
                    item.setData(Qt.ItemDataRole.UserRole, str(p))
                    self.sprites_gallery.addItem(item)
        self.tool_output.setPlainText(f"已生成 {len(files)} 张（输出目录: {out_dir}）")

    def _on_crop(self) -> None:
        out = self.crop_output.text().strip() or None
        msg = batch_crop_upper_half(
            self.crop_ratio.value(),
            self.crop_input.text().strip(),
            out,
        )
        self.tool_output.setPlainText(str(msg))

    def _on_rmbg(self) -> None:
        msg = batch_remove_background(self.rmbg_input.text().strip(), self.rmbg_output.text().strip())
        self.tool_output.setPlainText(str(msg))
