"""聊天模板标签页（PyQt）。"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QFileDialog,
)

from ui.settings_ui.chat_template_handlers import (
    generate_template,
    launch_chat,
    load_template_from_file,
    save_template,
    stop_chat,
)
from ui.settings_ui.context import SettingsUIContext


class TemplateSettingsTab(QWidget):
    def __init__(self, ctx: SettingsUIContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._path_obj = Path(ctx.template_dir_path)
        self._char_checks: list[QCheckBox] = []
        self._build_ui()
        self.refresh_lists()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner)

        lay.addWidget(QLabel("<h2>聊天模板管理</h2>"))
        lay.addWidget(QLabel("您可以选择从文件导入模版或者选择人物生成模版"))

        row = QHBoxLayout()
        left = QVBoxLayout()
        self.template_combo = QComboBox()
        left.addWidget(QLabel("从文件导入"))
        left.addWidget(self.template_combo)
        load_btn = QPushButton("加载模板")
        load_btn.clicked.connect(self._on_load)
        left.addWidget(load_btn)
        row.addLayout(left)

        right = QVBoxLayout()
        self.char_scroll = QScrollArea()
        self.char_scroll.setWidgetResizable(True)
        self.char_scroll.setMaximumHeight(160)
        self.char_host = QWidget()
        self.char_col = QVBoxLayout(self.char_host)
        self.char_scroll.setWidget(self.char_host)
        right.addWidget(QLabel("选择参与对话的角色"))
        right.addWidget(self.char_scroll)

        self.bg_combo = QComboBox()
        right.addWidget(QLabel("选择背景"))
        right.addWidget(self.bg_combo)

        self.use_effect_yes = QRadioButton("是")
        self.use_effect_no = QRadioButton("否")
        self.use_effect_yes.setChecked(True)
        ge = QButtonGroup(self)
        ge.addButton(self.use_effect_yes)
        ge.addButton(self.use_effect_no)
        er = QHBoxLayout()
        er.addWidget(QLabel("是否开启特殊效果"))
        er.addWidget(self.use_effect_yes)
        er.addWidget(self.use_effect_no)
        right.addLayout(er)

        self.use_tr_yes = QRadioButton("是")
        self.use_tr_no = QRadioButton("否")
        self.use_tr_yes.setChecked(True)
        gt = QButtonGroup(self)
        gt.addButton(self.use_tr_yes)
        gt.addButton(self.use_tr_no)
        tr = QHBoxLayout()
        tr.addWidget(QLabel("是否使用LLM翻译"))
        tr.addWidget(self.use_tr_yes)
        tr.addWidget(self.use_tr_no)
        right.addLayout(tr)

        self.use_cg_yes = QRadioButton("是")
        self.use_cg_no = QRadioButton("否")
        self.use_cg_no.setChecked(True)
        gc = QButtonGroup(self)
        gc.addButton(self.use_cg_yes)
        gc.addButton(self.use_cg_no)
        cr = QHBoxLayout()
        cr.addWidget(QLabel("是否开启CG生成"))
        cr.addWidget(self.use_cg_yes)
        cr.addWidget(self.use_cg_no)
        right.addLayout(cr)

        self.use_cot_yes = QRadioButton("是")
        self.use_cot_no = QRadioButton("否")
        self.use_cot_no.setChecked(True)
        gcot = QButtonGroup(self)
        gcot.addButton(self.use_cot_yes)
        gcot.addButton(self.use_cot_no)
        cotr = QHBoxLayout()
        cotr.addWidget(QLabel("是否启用思维链"))
        cotr.addWidget(self.use_cot_yes)
        cotr.addWidget(self.use_cot_no)
        right.addLayout(cotr)

        gen_btn = QPushButton("生成模板")
        gen_btn.clicked.connect(self._on_generate)
        right.addWidget(gen_btn)
        row.addLayout(right)
        lay.addLayout(row)

        self.template_output = QPlainTextEdit()
        self.template_output.setPlaceholderText("模板内容")
        self.template_output.setMinimumHeight(180)
        lay.addWidget(self.template_output)

        fn_row = QHBoxLayout()
        self.filename_edit = QLineEdit()
        self.filename_edit.setPlaceholderText("保存的文件名")
        save_btn = QPushButton("保存模板")
        save_btn.clicked.connect(self._on_save)
        fn_row.addWidget(self.filename_edit)
        fn_row.addWidget(save_btn)
        lay.addLayout(fn_row)

        vm_row = QHBoxLayout()
        vm_row.addWidget(QLabel("语音模式"))
        self.voice_preset = QRadioButton("预设语音模式")
        self.voice_full = QRadioButton("全语音模式")
        self.voice_preset.setChecked(True)
        vg = QButtonGroup(self)
        vg.addButton(self.voice_preset)
        vg.addButton(self.voice_full)
        vm_row.addWidget(self.voice_preset)
        vm_row.addWidget(self.voice_full)
        lay.addLayout(vm_row)

        init_row = QHBoxLayout()
        self.init_sprite_path = QLineEdit()
        self.init_sprite_path.setPlaceholderText("初始立绘图片路径（可选）")
        pick_init = QPushButton("浏览…")
        pick_init.clicked.connect(self._pick_init_sprite)
        init_row.addWidget(self.init_sprite_path)
        init_row.addWidget(pick_init)
        lay.addLayout(init_row)

        self.history_file = QLineEdit()
        self.history_file.setPlaceholderText("历史记录文件路径（可选），默认在 ./data/chat_history/")
        lay.addWidget(self.history_file)

        self.room_id = QLineEdit(self._ctx.config_manager.config.system_config.live_room_id or "")
        self.room_id.setPlaceholderText("bilibili 房间ID（可选）")
        lay.addWidget(QLabel("直播（可选）"))
        lay.addWidget(self.room_id)

        launch_btn = QPushButton("启动聊天")
        launch_btn.clicked.connect(self._on_launch)
        stop_btn = QPushButton("关闭聊天")
        stop_btn.clicked.connect(self._on_stop)
        btn_row = QHBoxLayout()
        btn_row.addWidget(launch_btn)
        btn_row.addWidget(stop_btn)
        lay.addLayout(btn_row)

        self.launch_output = QPlainTextEdit()
        self.launch_output.setReadOnly(True)
        self.launch_output.setMaximumHeight(120)
        self.launch_output.setPlaceholderText("启动结果")
        lay.addWidget(self.launch_output)

        root.addWidget(scroll)

    def _pick_init_sprite(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择初始立绘", "", "Images (*.png *.jpg *.jpeg *.webp);;All (*)")
        if path:
            self.init_sprite_path.setText(path)

    def _selected_chars(self) -> list[str]:
        return [cb.text() for cb in self._char_checks if cb.isChecked()]

    def _on_generate(self) -> None:
        ue = "是" if self.use_effect_yes.isChecked() else "否"
        ut = "是" if self.use_tr_yes.isChecked() else "否"
        ucg = "是" if self.use_cg_yes.isChecked() else "否"
        ucot = "是" if self.use_cot_yes.isChecked() else "否"
        tpl, out_fn = generate_template(
            self._ctx,
            self._selected_chars(),
            self.bg_combo.currentText(),
            ue,
            ut,
            ucg,
            ucot,
        )
        self.template_output.setPlainText(tpl)
        if out_fn:
            self.filename_edit.setText(out_fn)

    def _on_save(self) -> None:
        msg, files = save_template(self._ctx, self.template_output.toPlainText(), self.filename_edit.text().strip())
        self.launch_output.setPlainText(msg)
        self._refresh_template_combo(files)
        QMessageBox.information(self, "保存模板", msg)

    def _on_load(self) -> None:
        name = self.template_combo.currentText()
        if not name:
            QMessageBox.warning(self, "加载模板", "请先选择模板文件")
            return
        tpl, fn = load_template_from_file(self._ctx, name)
        if tpl.startswith("加载失败"):
            QMessageBox.warning(self, "加载模板", tpl)
            return
        self.template_output.setPlainText(tpl)
        self.filename_edit.setText(fn)

    def _on_launch(self) -> None:
        vm = "全语音模式" if self.voice_full.isChecked() else "预设语音模式"
        ucg = "是" if self.use_cg_yes.isChecked() else "否"
        msg = launch_chat(
            self._ctx,
            self.template_output.toPlainText(),
            vm,
            self.init_sprite_path.text().strip(),
            self.history_file.text().strip(),
            self.bg_combo.currentText(),
            ucg,
            self.room_id.text().strip(),
        )
        self.launch_output.setPlainText(msg or "")
        if msg:
            QMessageBox.information(self, "启动聊天", msg)

    def _on_stop(self) -> None:
        msg = stop_chat()
        self.launch_output.setPlainText(msg)
        QMessageBox.information(self, "关闭聊天", msg)

    def _refresh_template_combo(self, names: list[str] | None = None) -> None:
        self.template_combo.clear()
        path = self._path_obj
        path.mkdir(parents=True, exist_ok=True)
        files = names if names is not None else [f.name for f in path.iterdir() if f.is_file()]
        self.template_combo.addItems(sorted(files))

    def refresh_lists(self) -> None:
        while self.char_col.count():
            item = self.char_col.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._char_checks.clear()
        for name in self._ctx.character_manager.get_character_name_list():
            cb = QCheckBox(name)
            self._char_checks.append(cb)
            self.char_col.addWidget(cb)
        self.bg_combo.clear()
        self.bg_combo.addItems(self._ctx.background_manager.get_background_name_list() + ["透明背景"])
        self._refresh_template_combo()
