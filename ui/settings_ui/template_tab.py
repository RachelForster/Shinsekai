"""聊天模板标签页（PyQt）。"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.settings_ui.chat_template_handlers import (
    generate_template,
    launch_chat,
    load_template_from_file,
    save_template,
    stop_chat,
)
from ui.settings_ui.context import SettingsUIContext
from ui.settings_ui.feedback import feedback_result, message_fail, toast_info


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
        lay.setSpacing(10)

        lay.addWidget(QLabel("<h2>聊天模板</h2>"))
        intro = QLabel("可从文件加载已有模板，或勾选人物与选项后生成新模板，再编辑、保存与启动。")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        # --- 从文件加载 ---
        box_file = QGroupBox("从文件加载模板")
        bfl = QVBoxLayout(box_file)
        f_row = QHBoxLayout()
        self.template_combo = QComboBox()
        self.template_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        f_row.addWidget(self.template_combo, stretch=1)
        load_btn = QPushButton("加载到下方编辑区")
        load_btn.clicked.connect(self._on_load)
        f_row.addWidget(load_btn)
        bfl.addLayout(f_row)
        lay.addWidget(box_file)

        # --- 生成：大人物区 + 右侧选项 ---
        box_gen = QGroupBox("生成模板（选人物与选项）")
        bgen = QHBoxLayout(box_gen)
        bgen.setSpacing(12)

        char_box = QVBoxLayout()
        char_lbl = QLabel("参与对话的人物（可勾选多名）")
        char_lbl.setWordWrap(True)
        char_box.addWidget(char_lbl)
        self.char_scroll = QScrollArea()
        self.char_scroll.setWidgetResizable(True)
        self.char_scroll.setMinimumHeight(300)
        self.char_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.char_host = QWidget()
        self.char_grid = QGridLayout(self.char_host)
        self.char_grid.setColumnStretch(0, 1)
        self.char_grid.setColumnStretch(1, 1)
        self.char_grid.setColumnStretch(2, 1)
        self.char_scroll.setWidget(self.char_host)
        char_box.addWidget(self.char_scroll, stretch=1)
        bgen.addLayout(char_box, stretch=2)

        opt = QVBoxLayout()
        self.bg_combo = QComboBox()
        bg_form = QFormLayout()
        bg_form.addRow("背景", self.bg_combo)
        opt.addLayout(bg_form)

        self.use_effect_yes = QRadioButton("是")
        self.use_effect_no = QRadioButton("否")
        self.use_effect_yes.setChecked(True)
        ge = QButtonGroup(self)
        ge.addButton(self.use_effect_yes)
        ge.addButton(self.use_effect_no)
        er = QHBoxLayout()
        er.addWidget(QLabel("特殊效果"))
        er.addWidget(self.use_effect_yes)
        er.addWidget(self.use_effect_no)
        er.addStretch(1)
        opt.addLayout(er)

        self.use_tr_yes = QRadioButton("是")
        self.use_tr_no = QRadioButton("否")
        self.use_tr_yes.setChecked(True)
        gt = QButtonGroup(self)
        gt.addButton(self.use_tr_yes)
        gt.addButton(self.use_tr_no)
        tr = QHBoxLayout()
        tr.addWidget(QLabel("LLM 翻译"))
        tr.addWidget(self.use_tr_yes)
        tr.addWidget(self.use_tr_no)
        tr.addStretch(1)
        opt.addLayout(tr)

        self.use_cg_yes = QRadioButton("是")
        self.use_cg_no = QRadioButton("否")
        self.use_cg_no.setChecked(True)
        gcg = QButtonGroup(self)
        gcg.addButton(self.use_cg_yes)
        gcg.addButton(self.use_cg_no)
        cr = QHBoxLayout()
        cr.addWidget(QLabel("CG 生成"))
        cr.addWidget(self.use_cg_yes)
        cr.addWidget(self.use_cg_no)
        cr.addStretch(1)
        opt.addLayout(cr)

        self.use_cot_yes = QRadioButton("是")
        self.use_cot_no = QRadioButton("否")
        self.use_cot_no.setChecked(True)
        gcot = QButtonGroup(self)
        gcot.addButton(self.use_cot_yes)
        gcot.addButton(self.use_cot_no)
        cotr = QHBoxLayout()
        cotr.addWidget(QLabel("思维链 CoT"))
        cotr.addWidget(self.use_cot_yes)
        cotr.addWidget(self.use_cot_no)
        cotr.addStretch(1)
        opt.addLayout(cotr)

        opt.addStretch(1)
        gen_btn = QPushButton("根据选项生成模板")
        gen_btn.clicked.connect(self._on_generate)
        opt.addWidget(gen_btn)
        bgen.addLayout(opt, stretch=1)
        lay.addWidget(box_gen)

        # --- 模板正文 ---
        box_edit = QGroupBox("模板内容")
        el = QVBoxLayout(box_edit)
        self.template_output = QPlainTextEdit()
        self.template_output.setPlaceholderText("在此编辑或加载、生成后的模板内容")
        self.template_output.setMinimumHeight(200)
        el.addWidget(self.template_output)
        lay.addWidget(box_edit)

        # --- 保存与启动前参数（启动/关闭在页底固定）---
        box_run = QGroupBox("保存与聊天参数")
        rnl = QVBoxLayout(box_run)
        fn_row = QHBoxLayout()
        self.filename_edit = QLineEdit()
        self.filename_edit.setPlaceholderText("保存为模板文件名")
        save_btn = QPushButton("保存模板")
        save_btn.clicked.connect(self._on_save)
        fn_row.addWidget(self.filename_edit, stretch=1)
        fn_row.addWidget(save_btn)
        rnl.addLayout(fn_row)

        vm_row = QHBoxLayout()
        vm_row.addWidget(QLabel("语音模式"))
        self.voice_preset = QRadioButton("预设语音")
        self.voice_full = QRadioButton("全语音")
        self.voice_preset.setChecked(True)
        vg = QButtonGroup(self)
        vg.addButton(self.voice_preset)
        vg.addButton(self.voice_full)
        vm_row.addWidget(self.voice_preset)
        vm_row.addWidget(self.voice_full)
        vm_row.addStretch(1)
        rnl.addLayout(vm_row)

        init_row = QHBoxLayout()
        self.init_sprite_path = QLineEdit()
        self.init_sprite_path.setPlaceholderText("初始立绘图片（可选）")
        pick_init = QPushButton("浏览…")
        pick_init.clicked.connect(self._pick_init_sprite)
        init_row.addWidget(self.init_sprite_path, stretch=1)
        init_row.addWidget(pick_init)
        rnl.addLayout(init_row)

        self.history_file = QLineEdit()
        self.history_file.setPlaceholderText("历史记录文件（可选），默认在 ./data/chat_history/")
        rnl.addWidget(self.history_file)

        self.room_id = QLineEdit(self._ctx.config_manager.config.system_config.live_room_id or "")
        self.room_id.setPlaceholderText("bilibili 房间 ID（可选）")
        rnl.addWidget(QLabel("直播（可选）"))
        rnl.addWidget(self.room_id)

        lay.addWidget(box_run)

        root.addWidget(scroll, stretch=1)

        # 固定在页底的启动 / 关闭（不随主区域滚动）
        foot = QFrame()
        foot.setObjectName("templateTabFooter")
        foot.setFrameShape(QFrame.Shape.NoFrame)
        f_lay = QVBoxLayout(foot)
        f_lay.setContentsMargins(0, 0, 0, 0)
        f_lay.setSpacing(0)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        f_lay.addWidget(sep)
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(12, 8, 12, 8)
        launch_btn = QPushButton("启动聊天")
        launch_btn.setMinimumWidth(120)
        launch_btn.clicked.connect(self._on_launch)
        stop_btn = QPushButton("关闭聊天")
        stop_btn.setMinimumWidth(120)
        stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(launch_btn)
        btn_row.addWidget(stop_btn)
        btn_row.addStretch(1)
        f_lay.addLayout(btn_row)
        root.addWidget(foot)

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
        self._refresh_template_combo(files)
        feedback_result(self, "保存模板", msg)

    def _on_load(self) -> None:
        name = self.template_combo.currentText()
        if not name:
            message_fail(self, "加载模板", "请先选择模板文件")
            return
        tpl, fn = load_template_from_file(self._ctx, name)
        if tpl.startswith("加载失败"):
            message_fail(self, "加载模板", tpl)
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
        if msg:
            toast_info(self, "启动聊天", msg)

    def _on_stop(self) -> None:
        msg = stop_chat()
        toast_info(self, "关闭聊天", msg)

    def _refresh_template_combo(self, names: list[str] | None = None) -> None:
        self.template_combo.clear()
        path = self._path_obj
        path.mkdir(parents=True, exist_ok=True)
        files = names if names is not None else [f.name for f in path.iterdir() if f.is_file()]
        self.template_combo.addItems(sorted(files))

    def refresh_lists(self) -> None:
        while self.char_grid.count():
            item = self.char_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._char_checks.clear()
        names = self._ctx.character_manager.get_character_name_list()
        cols = 3
        for i, name in enumerate(names):
            cb = QCheckBox(name)
            self._char_checks.append(cb)
            r, c = divmod(i, cols)
            self.char_grid.addWidget(cb, r, c)
        self.bg_combo.clear()
        self.bg_combo.addItems(self._ctx.background_manager.get_background_name_list() + ["透明背景"])
        self._refresh_template_combo()
