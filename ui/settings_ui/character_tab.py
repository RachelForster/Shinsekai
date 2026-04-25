"""人物设定标签页（PyQt）。"""

from __future__ import annotations

import os
from pathlib import Path

from PyQt5.QtCore import Qt, QSize, QUrl, pyqtSignal
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
from PyQt5.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
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
    QVBoxLayout,
    QWidget,
)

import tools.file_util as fu
from config.character_config import CharacterConfig
from ui.settings_ui.context import SettingsUIContext
from ui.settings_ui.utils import path_file_list


class CharacterSettingsTab(QWidget):
    character_list_changed = pyqtSignal()

    def __init__(self, ctx: SettingsUIContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._player = QMediaPlayer(self, QMediaPlayer.LowLatency)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner)

        lay.addWidget(QLabel("<h2>人物管理</h2>"))
        top = QHBoxLayout()
        col_a = QVBoxLayout()
        col_a.addWidget(QLabel("加载或添加可用角色"))
        self.selected_character = QComboBox()
        col_a.addWidget(self.selected_character)
        export_btn = QPushButton("导出到 ./output 文件夹")
        export_btn.clicked.connect(self._on_export)
        del_btn = QPushButton("删除人物")
        del_btn.clicked.connect(self._on_delete)
        col_a.addWidget(export_btn)
        col_a.addWidget(del_btn)
        top.addLayout(col_a)

        col_b = QVBoxLayout()
        col_b.addWidget(QLabel("从文件导入（可多选 .char）"))
        imp_row = QHBoxLayout()
        self.import_files_display = QLineEdit()
        self.import_files_display.setReadOnly(True)
        self.import_files_display.setPlaceholderText("未选择文件")
        pick_files = QPushButton("选择文件…")
        pick_files.clicked.connect(self._pick_import_files)
        self._import_paths: list[str] = []
        imp_row.addWidget(self.import_files_display)
        imp_row.addWidget(pick_files)
        col_b.addLayout(imp_row)
        import_btn = QPushButton("从文件导入人物")
        import_btn.clicked.connect(self._on_import)
        col_b.addWidget(import_btn)
        self.import_output = QPlainTextEdit()
        self.import_output.setReadOnly(True)
        self.import_output.setMaximumHeight(100)
        col_b.addWidget(self.import_output)
        top.addLayout(col_b)
        lay.addLayout(top)

        info_row = QHBoxLayout()
        left_info = QFormLayout()
        self.char_name = QLineEdit()
        self.char_color = QLineEdit()
        self.char_color.setPlaceholderText("#d07d7d")
        self.sprite_prefix = QLineEdit("temp")
        left_info.addRow("人物名称", self.char_name)
        left_info.addRow("名称显示颜色", self.char_color)
        left_info.addRow("上传数据目录名（英文）", self.sprite_prefix)
        info_row.addLayout(left_info)
        right_info = QVBoxLayout()
        right_info.addWidget(QLabel("角色设定"))
        self.character_setting = QPlainTextEdit()
        self.character_setting.setMinimumHeight(100)
        ai_btn = QPushButton("AI 一键帮写")
        ai_btn.clicked.connect(self._on_ai_help)
        right_info.addWidget(self.character_setting)
        right_info.addWidget(ai_btn)
        info_row.addLayout(right_info)
        lay.addLayout(info_row)

        voice_box = QGroupBox("语音模块（可选）")
        vf = QFormLayout(voice_box)
        self.gpt_model_path = QLineEdit()
        self.sovits_model_path = QLineEdit()
        self.refer_audio_path = QLineEdit()
        self.prompt_text = QLineEdit()
        self.prompt_lang = QLineEdit()
        vf.addRow("GPT 模型路径", self.gpt_model_path)
        vf.addRow("SoVITS 模型路径", self.sovits_model_path)
        vf.addRow("参考音频路径", self.refer_audio_path)
        vf.addRow("参考音频文字内容", self.prompt_text)
        vf.addRow("语言 (en/ja/zh)", self.prompt_lang)
        lay.addWidget(voice_box)

        add_row = QHBoxLayout()
        add_btn = QPushButton("添加或保存人物设置")
        add_btn.clicked.connect(self._on_add)
        add_row.addWidget(add_btn)
        self.add_output = QPlainTextEdit()
        self.add_output.setReadOnly(True)
        self.add_output.setMaximumHeight(80)
        add_row.addWidget(self.add_output)
        lay.addLayout(add_row)

        lay.addWidget(QLabel("<h2>立绘管理</h2>"))
        sp_row = QHBoxLayout()
        sp_left = QVBoxLayout()
        up_row = QHBoxLayout()
        self.sprite_files_display = QLineEdit()
        self.sprite_files_display.setReadOnly(True)
        self._sprite_paths: list[str] = []
        b_up = QPushButton("选择立绘图片…")
        b_up.clicked.connect(self._pick_sprites)
        up_row.addWidget(self.sprite_files_display)
        up_row.addWidget(b_up)
        sp_left.addLayout(up_row)
        upload_sprites_btn = QPushButton("上传图片")
        upload_sprites_btn.clicked.connect(self._on_upload_sprites)
        sp_left.addWidget(upload_sprites_btn)
        self.sprite_scale = QDoubleSpinBox()
        self.sprite_scale.setRange(0, 3)
        self.sprite_scale.setSingleStep(0.05)
        self.sprite_scale.setValue(1.0)
        sp_left.addWidget(QLabel("立绘显示缩放"))
        sp_left.addWidget(self.sprite_scale)
        scale_save = QPushButton("保存立绘放大/缩小倍数")
        scale_save.clicked.connect(self._on_save_scale)
        sp_left.addWidget(scale_save)
        del_all_sp = QPushButton("删除所有立绘")
        del_all_sp.clicked.connect(self._on_delete_all_sprites)
        sp_left.addWidget(del_all_sp)
        sp_row.addLayout(sp_left)

        sp_mid = QVBoxLayout()
        self.sprites_gallery = QListWidget()
        self.sprites_gallery.setViewMode(QListWidget.IconMode)
        self.sprites_gallery.setIconSize(QSize(100, 100))
        self.sprites_gallery.setResizeMode(QListWidget.Adjust)
        self.sprites_gallery.setMinimumHeight(200)
        self.sprites_gallery.currentRowChanged.connect(self._on_sprite_row)
        sp_mid.addWidget(QLabel("已上传的立绘（点击选择）"))
        sp_mid.addWidget(self.sprites_gallery)
        del_one = QPushButton("删除选中立绘")
        del_one.clicked.connect(self._on_delete_one_sprite)
        sp_mid.addWidget(del_one)
        sp_row.addLayout(sp_mid)

        sp_right = QVBoxLayout()
        sp_right.addWidget(QLabel("标注立绘情绪关键字"))
        self.emotion_inputs = QPlainTextEdit()
        self.emotion_inputs.setMinimumHeight(150)
        sp_right.addWidget(self.emotion_inputs)
        tag_btn = QPushButton("上传立绘标注")
        tag_btn.clicked.connect(self._on_upload_tags)
        sp_right.addWidget(tag_btn)
        sp_row.addLayout(sp_right)
        lay.addLayout(sp_row)

        voice_row = QHBoxLayout()
        vv = QVBoxLayout()
        vv.addWidget(QLabel("立绘与语音（可选）"))
        self.selected_sprite_info = QLineEdit()
        self.selected_sprite_info.setReadOnly(True)
        vv.addWidget(self.selected_sprite_info)
        play_v = QPushButton("播放当前立绘语音")
        play_v.clicked.connect(self._on_play_voice)
        vv.addWidget(play_v)
        self.sprite_voice_path = QLineEdit()
        self.sprite_voice_path.setPlaceholderText("当前语音文件路径")
        self.sprite_voice_path.setReadOnly(True)
        vv.addWidget(self.sprite_voice_path)
        self.sprite_voice_text = QLineEdit()
        self.sprite_voice_text.setPlaceholderText("立绘语音内容 / 参考语音需填写文字")
        vv.addWidget(self.sprite_voice_text)
        vr = QHBoxLayout()
        self.voice_upload_path = QLineEdit()
        bvw = QPushButton("选择语音…")
        bvw.clicked.connect(self._pick_voice)
        vr.addWidget(self.voice_upload_path)
        vr.addWidget(bvw)
        vv.addLayout(vr)
        upload_voice_btn = QPushButton("上传语音")
        upload_voice_btn.clicked.connect(self._on_upload_voice)
        vv.addWidget(upload_voice_btn)
        self.voice_upload_output = QPlainTextEdit()
        self.voice_upload_output.setReadOnly(True)
        self.voice_upload_output.setMaximumHeight(60)
        vv.addWidget(self.voice_upload_output)
        voice_row.addLayout(vv)
        lay.addLayout(voice_row)

        root.addWidget(scroll)

        self.selected_character.currentTextChanged.connect(self._on_character_change)
        self._refresh_character_combo()
        self._on_character_change(self.selected_character.currentText())

    def _current_char(self) -> str:
        return self.selected_character.currentText().strip()

    def _refresh_character_combo(self, select: str | None = None) -> None:
        self.selected_character.blockSignals(True)
        self.selected_character.clear()
        self.selected_character.addItem("新角色")
        for n in self._ctx.character_manager.get_character_name_list():
            self.selected_character.addItem(n)
        if select:
            idx = self.selected_character.findText(select)
            if idx >= 0:
                self.selected_character.setCurrentIndex(idx)
        self.selected_character.blockSignals(False)

    def _fill_character(self, name: str) -> None:
        c = self._ctx.config_manager.get_character_by_name(name)
        if c is None:
            self.char_name.clear()
            self.char_color.setText("#d07d7d")
            self.sprite_prefix.setText("temp")
            for w in (self.gpt_model_path, self.sovits_model_path, self.refer_audio_path, self.prompt_text, self.prompt_lang):
                w.clear()
            self.character_setting.clear()
            return
        self.char_name.setText(c.name)
        self.char_color.setText(c.color or "#d07d7d")
        self.sprite_prefix.setText(c.sprite_prefix or "temp")
        self.gpt_model_path.setText(c.gpt_model_path or "")
        self.sovits_model_path.setText(c.sovits_model_path or "")
        self.refer_audio_path.setText(c.refer_audio_path or "")
        self.prompt_text.setText(c.prompt_text or "")
        self.prompt_lang.setText(c.prompt_lang or "")
        self.character_setting.setPlainText(c.character_setting or "")

    def _on_character_change(self, name: str) -> None:
        if not name or name == "新角色":
            self._fill_character("")
        else:
            self._fill_character(name)
        paths, emo, _ = self._ctx.character_manager.get_character_sprites(name) if name and name != "新角色" else ([], "", [])
        self._load_gallery(paths)
        self.emotion_inputs.setPlainText(emo)
        ch = self._ctx.config_manager.get_character_by_name(name) if name and name != "新角色" else None
        self.sprite_scale.setValue(float(ch.sprite_scale) if ch else 1.0)
        self._sprite_paths.clear()
        self.sprite_files_display.clear()
        self.sprites_gallery.setCurrentRow(-1)
        self._update_sprite_side_info()

    def _load_gallery(self, paths: list[str]) -> None:
        self.sprites_gallery.clear()
        for p in paths:
            if not p or not Path(p).exists():
                continue
            pix = QPixmap(p)
            if not pix.isNull():
                it = QListWidgetItem(QIcon(pix.scaled(100, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation)), Path(p).name)
                it.setData(Qt.UserRole, p)
                self.sprites_gallery.addItem(it)

    def _on_sprite_row(self) -> None:
        self._update_sprite_side_info()

    def _selected_sprite_index(self) -> int | None:
        r = self.sprites_gallery.currentRow()
        if r < 0:
            return None
        return r

    def _update_sprite_side_info(self) -> None:
        name = self._current_char()
        idx = self._selected_sprite_index()
        if not name or name == "新角色" or idx is None:
            self.selected_sprite_info.setText("未选择立绘")
            self.sprite_voice_path.clear()
            self.sprite_voice_text.clear()
            return
        vpath, vtext = self._ctx.character_manager.get_sprite_voice(name, idx)
        self.selected_sprite_info.setText(f"立绘 {idx + 1}" + (" (已有语音)" if vpath else " (无语音)"))
        self.sprite_voice_path.setText(vpath or "")
        self.sprite_voice_text.setText(vtext or "")

    def _on_export(self) -> None:
        name = self._current_char()
        if not name or name == "新角色":
            self.import_output.setPlainText("请选择有效角色")
            return
        c = self._ctx.config_manager.get_character_by_name(name)
        if c is None:
            self.import_output.setPlainText("人物不存在")
            return
        try:
            Path("./output").mkdir(parents=True, exist_ok=True)
            ch = CharacterConfig.parse_dic(char_data=c.__dict__)
            fu.export_character([ch], output_path=f"./output/{c.name}.char")
            self.import_output.setPlainText("导出成功")
        except Exception as e:
            self.import_output.setPlainText(f"导出失败 {e}")

    def _pick_import_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "导入 .char", "", "Character (*.char);;All (*)")
        self._import_paths = list(files)
        self.import_files_display.setText("; ".join(Path(p).name for p in self._import_paths))

    def _on_import(self) -> None:
        if not self._import_paths:
            self.import_output.setPlainText("请先选择文件")
            return
        success = 0
        err: list[str] = []
        for p in self._import_paths:
            try:
                fu.import_character(p)
                success += 1
            except Exception as e:
                err.append(f"{os.path.basename(p)}: {e}")
        self._ctx.config_manager.reload()
        msg = f"成功导入 {success} 个角色。"
        if err:
            msg += "\n" + "\n".join(err)
        self.import_output.setPlainText(msg)
        self._refresh_character_combo()
        self.character_list_changed.emit()

    def _on_add(self) -> None:
        msg, _ = self._ctx.character_manager.add_character(
            self.char_name.text().strip(),
            self.char_color.text().strip() or "#d07d7d",
            self.sprite_prefix.text().strip() or "temp",
            self.gpt_model_path.text().strip(),
            self.sovits_model_path.text().strip(),
            self.refer_audio_path.text().strip(),
            self.prompt_text.text().strip(),
            self.prompt_lang.text().strip(),
            self.character_setting.toPlainText().strip(),
        )
        self.add_output.setPlainText(msg)
        self._refresh_character_combo(self.char_name.text().strip())
        self.character_list_changed.emit()

    def _on_delete(self) -> None:
        name = self._current_char()
        msg, _ = self._ctx.character_manager.delete_character(name)
        self.add_output.setPlainText(msg)
        self._refresh_character_combo("新角色")
        self._on_character_change("新角色")
        self.character_list_changed.emit()

    def _on_ai_help(self) -> None:
        out, setting = self._ctx.character_manager.generate_character_setting(
            self.char_name.text().strip(),
            self.character_setting.toPlainText(),
        )
        self.import_output.setPlainText(out)
        self.character_setting.setPlainText(setting)

    def _pick_sprites(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "立绘图片", "", "Images (*.png *.jpg *.jpeg *.webp);;All (*)")
        self._sprite_paths = list(files)
        self.sprite_files_display.setText(f"{len(self._sprite_paths)} 个文件")

    def _on_upload_sprites(self) -> None:
        name = self._current_char()
        if not self._sprite_paths:
            self.add_output.setPlainText("请选择要上传的图片")
            return
        msg, paths, emo = self._ctx.character_manager.upload_sprites(
            name,
            path_file_list(self._sprite_paths),
            self.emotion_inputs.toPlainText(),
        )
        self.add_output.setPlainText(msg)
        self._load_gallery(paths)
        self.emotion_inputs.setPlainText(emo)
        self._refresh_character_combo(name)
        self.character_list_changed.emit()

    def _on_save_scale(self) -> None:
        msg = self._ctx.character_manager.save_sprite_scale(self._current_char(), self.sprite_scale.value())
        self.add_output.setPlainText(msg)

    def _on_delete_all_sprites(self) -> None:
        msg, paths, emo = self._ctx.character_manager.delete_all_sprites(self._current_char())
        self.add_output.setPlainText(msg)
        self._load_gallery(paths)
        self.emotion_inputs.setPlainText(emo)
        self.character_list_changed.emit()

    def _on_delete_one_sprite(self) -> None:
        idx = self._selected_sprite_index()
        if idx is None:
            return
        msg, paths, emo = self._ctx.character_manager.delete_single_sprite(self._current_char(), idx)
        self.add_output.setPlainText(msg)
        self._load_gallery(paths)
        self.emotion_inputs.setPlainText(emo)
        self._update_sprite_side_info()
        self.character_list_changed.emit()

    def _on_upload_tags(self) -> None:
        msg = self._ctx.character_manager.upload_emotion_tags(
            self._current_char(), self.emotion_inputs.toPlainText()
        )
        self.add_output.setPlainText(msg)

    def _pick_voice(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "语音文件", "", "Audio (*.wav *.mp3 *.ogg);;All (*)")
        if path:
            self.voice_upload_path.setText(path)

    def _on_play_voice(self) -> None:
        p = self.sprite_voice_path.text().strip()
        if not p or not Path(p).is_file():
            QMessageBox.information(self, "播放", "无有效语音文件")
            return
        self._player.setMedia(QMediaContent(QUrl.fromLocalFile(Path(p).resolve().as_posix())))
        self._player.play()

    def _on_upload_voice(self) -> None:
        vfile = self.voice_upload_path.text().strip()
        if not vfile:
            self.voice_upload_output.setPlainText("请选择语音文件")
            return
        idx = self._selected_sprite_index()
        if idx is None:
            self.voice_upload_output.setPlainText("请先选择立绘")
            return
        msg, vpath = self._ctx.character_manager.upload_voice(
            self._current_char(), idx, vfile, self.sprite_voice_text.text()
        )
        self.voice_upload_output.setPlainText(msg)
        if vpath:
            self.sprite_voice_path.setText(vpath)
        self._update_sprite_side_info()
        self.character_list_changed.emit()
