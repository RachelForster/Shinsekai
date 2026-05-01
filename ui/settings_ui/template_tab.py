"""聊天模板标签页（PySide6）。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from llm.template_generator import TRANSPARENT_BG
from ui.settings_ui.chat_template_handlers import (
    generate_template,
    launch_chat,
    load_template_from_file,
    parse_stored_template,
    save_template,
)
from i18n import tr as tr_i18n
from ui.settings_ui.context import SettingsUIContext
from ui.settings_ui.feedback import feedback_result, message_fail, toast_success
from ui.settings_ui.template_tab_session import (
    load_template_session,
    save_template_session,
)


class TemplateSettingsTab(QWidget):
    def __init__(self, ctx: SettingsUIContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._path_obj = Path(ctx.template_dir_path)
        self._char_checks: list[QCheckBox] = []
        # 在 refresh_lists / apply_i18n 重填控件时抑制自动「生成模板」，避免误触发
        self._suppress_auto_gen = False
        self._build_ui()
        self._wire_auto_generate_triggers()
        self.refresh_lists()
        # 首次进入设置时若默认停在其它页，此处不恢复；切换至模板页时由 MainWindow 调用 restore

    def _wire_auto_generate_triggers(self) -> None:
        self.bg_combo.currentTextChanged.connect(self._auto_generate)
        self.voice_lang_combo.currentIndexChanged.connect(self._auto_generate)
        self._group_effect.buttonClicked.connect(self._auto_generate)
        self._group_tr.buttonClicked.connect(self._auto_generate)
        self._group_cg.buttonClicked.connect(self._auto_generate)
        self._group_cot.buttonClicked.connect(self._auto_generate)
        self._group_choice.buttonClicked.connect(self._auto_generate)
        self._group_narration.buttonClicked.connect(self._auto_generate)
        self.max_speech_chars_spin.valueChanged.connect(self._auto_generate)
        self.max_dialog_items_spin.valueChanged.connect(self._auto_generate)

    def _auto_generate(self, *_args: object) -> None:
        if self._suppress_auto_gen:
            return
        self._on_generate()

    def _on_system_section_toggled(self, expanded: bool) -> None:
        self._system_body.setVisible(expanded)
        self._system_fold_btn.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setSpacing(10)

        self._tpl_h2 = QLabel(tr_i18n("template.h2"))
        self._tpl_intro = QLabel(tr_i18n("template.intro"))
        self._tpl_intro.setWordWrap(True)
        lay.addWidget(self._tpl_h2)
        lay.addWidget(self._tpl_intro)

        # --- 从文件加载 ---
        self._box_file = QGroupBox(tr_i18n("template.load_box"))
        bfl = QVBoxLayout(self._box_file)
        f_row = QHBoxLayout()
        self.template_combo = QComboBox()
        self.template_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.template_combo.activated.connect(self._on_template_combo_activated)
        f_row.addWidget(self.template_combo, stretch=1)
        bfl.addLayout(f_row)
        lay.addWidget(self._box_file)

        # --- 生成：大人物区 + 右侧选项 ---
        self._box_gen = QGroupBox(tr_i18n("template.gen_box"))
        bgen = QHBoxLayout(self._box_gen)
        bgen.setSpacing(12)

        char_box = QVBoxLayout()
        self._char_lbl = QLabel(tr_i18n("template.char_label"))
        self._char_lbl.setWordWrap(True)
        char_box.addWidget(self._char_lbl)
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
        self._bg_lbl = QLabel(tr_i18n("template.bg"))
        bg_form.addRow(self._bg_lbl, self.bg_combo)
        opt.addLayout(bg_form)

        self._voice_lang_lbl = QLabel(tr_i18n("template.voice_target_lang"))
        self.voice_lang_combo = QComboBox()
        self.voice_lang_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._fill_voice_lang_combo()
        self._sync_voice_lang_from_config()
        self.voice_lang_combo.activated.connect(self._on_voice_lang_activated)
        vlang_form = QFormLayout()
        vlang_form.addRow(self._voice_lang_lbl, self.voice_lang_combo)
        opt.addLayout(vlang_form)

        self.use_effect_yes = QRadioButton(tr_i18n("common.yes"))
        self.use_effect_no = QRadioButton(tr_i18n("common.no"))
        self.use_effect_yes.setChecked(True)
        self._group_effect = QButtonGroup(self)
        self._group_effect.addButton(self.use_effect_yes)
        self._group_effect.addButton(self.use_effect_no)
        er = QHBoxLayout()
        self._lbl_fx = QLabel(tr_i18n("template.fx"))
        er.addWidget(self._lbl_fx)
        er.addWidget(self.use_effect_yes)
        er.addWidget(self.use_effect_no)
        er.addStretch(1)
        opt.addLayout(er)

        self.use_tr_yes = QRadioButton(tr_i18n("common.yes"))
        self.use_tr_no = QRadioButton(tr_i18n("common.no"))
        self.use_tr_yes.setChecked(True)
        self._group_tr = QButtonGroup(self)
        self._group_tr.addButton(self.use_tr_yes)
        self._group_tr.addButton(self.use_tr_no)
        llm_tr_row = QHBoxLayout()
        self._lbl_llm_tr = QLabel(tr_i18n("template.llm_tr"))
        llm_tr_row.addWidget(self._lbl_llm_tr)
        llm_tr_row.addWidget(self.use_tr_yes)
        llm_tr_row.addWidget(self.use_tr_no)
        llm_tr_row.addStretch(1)
        opt.addLayout(llm_tr_row)

        self.use_cg_yes = QRadioButton(tr_i18n("common.yes"))
        self.use_cg_no = QRadioButton(tr_i18n("common.no"))
        self.use_cg_no.setChecked(True)
        self._group_cg = QButtonGroup(self)
        self._group_cg.addButton(self.use_cg_yes)
        self._group_cg.addButton(self.use_cg_no)
        cr = QHBoxLayout()
        self._lbl_cg = QLabel(tr_i18n("template.cg"))
        cr.addWidget(self._lbl_cg)
        cr.addWidget(self.use_cg_yes)
        cr.addWidget(self.use_cg_no)
        cr.addStretch(1)
        opt.addLayout(cr)

        self.use_cot_yes = QRadioButton(tr_i18n("common.yes"))
        self.use_cot_no = QRadioButton(tr_i18n("common.no"))
        self.use_cot_no.setChecked(True)
        self._group_cot = QButtonGroup(self)
        self._group_cot.addButton(self.use_cot_yes)
        self._group_cot.addButton(self.use_cot_no)
        cotr = QHBoxLayout()
        self._lbl_cot = QLabel(tr_i18n("template.cot"))
        cotr.addWidget(self._lbl_cot)
        cotr.addWidget(self.use_cot_yes)
        cotr.addWidget(self.use_cot_no)
        cotr.addStretch(1)
        opt.addLayout(cotr)

        self.use_choice_yes = QRadioButton(tr_i18n("common.yes"))
        self.use_choice_no = QRadioButton(tr_i18n("common.no"))
        self.use_choice_yes.setChecked(True)
        self._group_choice = QButtonGroup(self)
        self._group_choice.addButton(self.use_choice_yes)
        self._group_choice.addButton(self.use_choice_no)
        ch_row = QHBoxLayout()
        self._lbl_choice_rules = QLabel(tr_i18n("template.rule_choice"))
        ch_row.addWidget(self._lbl_choice_rules)
        ch_row.addWidget(self.use_choice_yes)
        ch_row.addWidget(self.use_choice_no)
        ch_row.addStretch(1)
        opt.addLayout(ch_row)

        self.use_narration_yes = QRadioButton(tr_i18n("common.yes"))
        self.use_narration_no = QRadioButton(tr_i18n("common.no"))
        self.use_narration_yes.setChecked(True)
        self._group_narration = QButtonGroup(self)
        self._group_narration.addButton(self.use_narration_yes)
        self._group_narration.addButton(self.use_narration_no)
        nar_row = QHBoxLayout()
        self._lbl_narr_rules = QLabel(tr_i18n("template.rule_narration"))
        nar_row.addWidget(self._lbl_narr_rules)
        nar_row.addWidget(self.use_narration_yes)
        nar_row.addWidget(self.use_narration_no)
        nar_row.addStretch(1)
        opt.addLayout(nar_row)

        lim_form = QFormLayout()
        self._lbl_max_speech = QLabel(tr_i18n("template.max_speech_chars"))
        self.max_speech_chars_spin = QSpinBox()
        self.max_speech_chars_spin.setRange(0, 500_000)
        self.max_speech_chars_spin.setSingleStep(10)
        self.max_speech_chars_spin.setSpecialValueText(tr_i18n("template.limit_unlimited"))
        lim_form.addRow(self._lbl_max_speech, self.max_speech_chars_spin)
        self._lbl_max_dialog = QLabel(tr_i18n("template.max_dialog_items"))
        self.max_dialog_items_spin = QSpinBox()
        self.max_dialog_items_spin.setRange(0, 500)
        self.max_dialog_items_spin.setSpecialValueText(tr_i18n("template.limit_unlimited"))
        lim_form.addRow(self._lbl_max_dialog, self.max_dialog_items_spin)
        opt.addLayout(lim_form)

        opt.addStretch(1)
        bgen.addLayout(opt, stretch=1)
        lay.addWidget(self._box_gen)

        # --- 用户情景（参与历史文件名映射）---
        self._box_scenario = QGroupBox(tr_i18n("template.scenario_box"))
        sl = QVBoxLayout(self._box_scenario)
        self.scenario_output = QPlainTextEdit()
        self.scenario_output.setPlaceholderText(tr_i18n("template.scenario_ph"))
        self.scenario_output.setMinimumHeight(120)
        sl.addWidget(self.scenario_output)
        lay.addWidget(self._box_scenario)

        # --- 系统生成模板（默认折叠，点击标题展开）---
        self._box_system = QGroupBox()
        sys_lay = QVBoxLayout(self._box_system)
        head_row = QHBoxLayout()
        self._system_fold_btn = QToolButton()
        self._system_fold_btn.setCheckable(True)
        self._system_fold_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self._system_fold_btn.setText(tr_i18n("template.system_box"))
        self._system_fold_btn.setArrowType(Qt.ArrowType.RightArrow)
        self._system_fold_btn.setChecked(False)
        self._system_fold_btn.toggled.connect(self._on_system_section_toggled)
        head_row.addWidget(self._system_fold_btn)
        head_row.addStretch(1)
        sys_lay.addLayout(head_row)

        self._system_body = QWidget()
        el = QVBoxLayout(self._system_body)
        el.setContentsMargins(0, 0, 0, 0)
        self.template_output = QPlainTextEdit()
        self.template_output.setPlaceholderText(tr_i18n("template.system_ph"))
        self.template_output.setMinimumHeight(200)
        el.addWidget(self.template_output)
        sys_lay.addWidget(self._system_body)
        self._system_body.setVisible(False)
        lay.addWidget(self._box_system)

        # --- 保存与启动前参数（启动/关闭在页底固定）---
        self._box_run = QGroupBox(tr_i18n("template.run_box"))
        rnl = QVBoxLayout(self._box_run)
        fn_row = QHBoxLayout()
        self.filename_edit = QLineEdit()
        self.filename_edit.setPlaceholderText(tr_i18n("template.fn_ph"))
        self._save_tpl = QPushButton(tr_i18n("template.save_tpl"))
        self._save_tpl.clicked.connect(self._on_save)
        fn_row.addWidget(self.filename_edit, stretch=1)
        fn_row.addWidget(self._save_tpl)
        rnl.addLayout(fn_row)

        init_row = QHBoxLayout()
        self.init_sprite_path = QLineEdit()
        self.init_sprite_path.setPlaceholderText(tr_i18n("template.init_sp_ph"))
        self._pick_init = QPushButton(tr_i18n("template.browse"))
        self._pick_init.clicked.connect(self._pick_init_sprite)
        init_row.addWidget(self.init_sprite_path, stretch=1)
        init_row.addWidget(self._pick_init)
        rnl.addLayout(init_row)

        self.history_file = QLineEdit()
        self.history_file.setPlaceholderText(tr_i18n("template.hist_ph"))
        rnl.addWidget(self.history_file)

        self.room_id = QLineEdit(self._ctx.config_manager.config.system_config.live_room_id or "")
        # self.room_id.setPlaceholderText(tr_i18n("template.live_ph"))
        # self._live_lbl = QLabel(tr_i18n("template.live_lbl"))
        # rnl.addWidget(self._live_lbl)
        # rnl.addWidget(self.room_id)

        lay.addWidget(self._box_run)

        root.addWidget(scroll, stretch=1)

        # 固定在页底的启动（不随主区域滚动）
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
        self._launch_btn = QPushButton(tr_i18n("template.launch"))
        self._launch_btn.setMinimumWidth(120)
        self._launch_btn.clicked.connect(self._on_launch)
        btn_row.addWidget(self._launch_btn)
        btn_row.addStretch(1)
        f_lay.addLayout(btn_row)
        root.addWidget(foot)

    def apply_i18n(self) -> None:
        self._suppress_auto_gen = True
        try:
            self._apply_i18n_impl()
        finally:
            self._suppress_auto_gen = False

    def _apply_i18n_impl(self) -> None:
        self._tpl_h2.setText(tr_i18n("template.h2"))
        self._tpl_intro.setText(tr_i18n("template.intro"))
        self._box_file.setTitle(tr_i18n("template.load_box"))
        self._box_gen.setTitle(tr_i18n("template.gen_box"))
        self._char_lbl.setText(tr_i18n("template.char_label"))
        self._bg_lbl.setText(tr_i18n("template.bg"))
        self._voice_lang_lbl.setText(tr_i18n("template.voice_target_lang"))
        cur_v = None
        if self.voice_lang_combo.count():
            cur_v = self.voice_lang_combo.currentData()
        self._fill_voice_lang_combo()
        if cur_v is not None:
            for i in range(self.voice_lang_combo.count()):
                if self.voice_lang_combo.itemData(i) == cur_v:
                    self.voice_lang_combo.setCurrentIndex(i)
                    break
        else:
            self._sync_voice_lang_from_config()
        ytxt, ntxt = tr_i18n("common.yes"), tr_i18n("common.no")
        self.use_effect_yes.setText(ytxt)
        self.use_effect_no.setText(ntxt)
        self.use_tr_yes.setText(ytxt)
        self.use_tr_no.setText(ntxt)
        self.use_cg_yes.setText(ytxt)
        self.use_cg_no.setText(ntxt)
        self.use_cot_yes.setText(ytxt)
        self.use_cot_no.setText(ntxt)
        self.use_choice_yes.setText(ytxt)
        self.use_choice_no.setText(ntxt)
        self.use_narration_yes.setText(ytxt)
        self.use_narration_no.setText(ntxt)
        self._lbl_fx.setText(tr_i18n("template.fx"))
        self._lbl_llm_tr.setText(tr_i18n("template.llm_tr"))
        self._lbl_cg.setText(tr_i18n("template.cg"))
        self._lbl_cot.setText(tr_i18n("template.cot"))
        self._lbl_choice_rules.setText(tr_i18n("template.rule_choice"))
        self._lbl_narr_rules.setText(tr_i18n("template.rule_narration"))
        self._lbl_max_speech.setText(tr_i18n("template.max_speech_chars"))
        self._lbl_max_dialog.setText(tr_i18n("template.max_dialog_items"))
        self.max_speech_chars_spin.setSpecialValueText(tr_i18n("template.limit_unlimited"))
        self.max_dialog_items_spin.setSpecialValueText(tr_i18n("template.limit_unlimited"))
        self._box_scenario.setTitle(tr_i18n("template.scenario_box"))
        self.scenario_output.setPlaceholderText(tr_i18n("template.scenario_ph"))
        self._system_fold_btn.setText(tr_i18n("template.system_box"))
        self.template_output.setPlaceholderText(tr_i18n("template.system_ph"))
        self._box_run.setTitle(tr_i18n("template.run_box"))
        self.filename_edit.setPlaceholderText(tr_i18n("template.fn_ph"))
        self._save_tpl.setText(tr_i18n("template.save_tpl"))
        self.init_sprite_path.setPlaceholderText(tr_i18n("template.init_sp_ph"))
        self._pick_init.setText(tr_i18n("template.browse"))
        self.history_file.setPlaceholderText(tr_i18n("template.hist_ph"))
        # self._live_lbl.setText(tr_i18n("template.live_lbl"))
        # self.room_id.setPlaceholderText(tr_i18n("template.live_ph"))
        self._launch_btn.setText(tr_i18n("template.launch"))

    def _fill_voice_lang_combo(self) -> None:
        self.voice_lang_combo.clear()
        for code in ("ja", "en", "zh", "yue"):
            self.voice_lang_combo.addItem(
                tr_i18n(f"template.voice_lang_{code}"), code
            )

    def _sync_voice_lang_from_config(self) -> None:
        raw = (
            getattr(
                self._ctx.config_manager.config.system_config, "voice_language", None
            )
            or "ja"
        )
        c = (str(raw).strip() or "ja").lower()
        for i in range(self.voice_lang_combo.count()):
            if str(self.voice_lang_combo.itemData(i)).lower() == c:
                self.voice_lang_combo.setCurrentIndex(i)
                return
        self.voice_lang_combo.setCurrentIndex(0)

    def _on_voice_lang_activated(self, index: int) -> None:
        code = self.voice_lang_combo.itemData(index)
        if not code:
            return
        self._ctx.config_manager.config.system_config.voice_language = str(code)
        self._ctx.config_manager.save_system_config()

    def _pick_init_sprite(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr_i18n("template.pick_sprite_title"), "", "Images (*.png *.jpg *.jpeg *.webp);;All (*)"
        )
        if path:
            self.init_sprite_path.setText(path)

    def _selected_chars(self) -> list[str]:
        return [cb.text() for cb in self._char_checks if cb.isChecked()]

    def _on_generate(self) -> None:
        vcode = self.voice_lang_combo.currentData()
        if vcode:
            self._ctx.config_manager.config.system_config.voice_language = str(vcode)
            self._ctx.config_manager.save_system_config()
        ue = "是" if self.use_effect_yes.isChecked() else "否"
        ut = "是" if self.use_tr_yes.isChecked() else "否"
        ucg = "是" if self.use_cg_yes.isChecked() else "否"
        ucot = "是" if self.use_cot_yes.isChecked() else "否"
        uch = "是" if self.use_choice_yes.isChecked() else "否"
        unar = "是" if self.use_narration_yes.isChecked() else "否"
        tpl, out_fn = generate_template(
            self._ctx,
            self._selected_chars(),
            self.bg_combo.currentText(),
            ue,
            ut,
            ucg,
            ucot,
            uch,
            unar,
            self.max_speech_chars_spin.value(),
            self.max_dialog_items_spin.value(),
        )
        self.template_output.setPlainText(tpl)
        if out_fn:
            self.filename_edit.setText(out_fn)

    def _on_template_combo_activated(self, index: int) -> None:
        """用户从下拉列表选中某项时载入模板（程序化改索引不会触发 activated）。"""
        if index < 0:
            return
        name = self.template_combo.itemText(index).strip()
        if not name:
            return
        scen, sys_t, fn = load_template_from_file(self._ctx, name)
        if scen.startswith("加载失败"):
            message_fail(self, "加载模板", scen)
            return
        self.scenario_output.setPlainText(scen)
        self.template_output.setPlainText(sys_t)
        self.filename_edit.setText(fn)

    def _on_save(self) -> None:
        msg, files = save_template(
            self._ctx,
            self.scenario_output.toPlainText(),
            self.template_output.toPlainText(),
            self.filename_edit.text().strip(),
        )
        self._refresh_template_combo(files)
        feedback_result(self, "保存模板", msg)

    def _save_launch_session(self) -> None:
        payload = {
            "selected_characters": self._selected_chars(),
            "background": self.bg_combo.currentText(),
            "voice_lang": str(self.voice_lang_combo.currentData() or "")
            or (
                self._ctx.config_manager.config.system_config.voice_language or "ja"
            ),
            "use_effect_yes": self.use_effect_yes.isChecked(),
            "use_tr_yes": self.use_tr_yes.isChecked(),
            "use_cg_yes": self.use_cg_yes.isChecked(),
            "use_cot_yes": self.use_cot_yes.isChecked(),
            "use_choice_yes": self.use_choice_yes.isChecked(),
            "use_narration_yes": self.use_narration_yes.isChecked(),
            "max_speech_chars": self.max_speech_chars_spin.value(),
            "max_dialog_items": self.max_dialog_items_spin.value(),
            "scenario_text": self.scenario_output.toPlainText(),
            "system_template_text": self.template_output.toPlainText(),
            "filename_stub": self.filename_edit.text().strip(),
            "template_file_dropdown": self.template_combo.currentText().strip(),
            "init_sprite_path": self.init_sprite_path.text().strip(),
            "history_file": self.history_file.text().strip(),
            "room_id": self.room_id.text().strip(),
        }
        try:
            save_template_session(self._ctx.template_dir_path, payload)
        except OSError:
            pass

    def restore_last_launch_session(self) -> None:
        snap = load_template_session(self._ctx.template_dir_path)
        if not snap:
            return
        self._suppress_auto_gen = True
        try:
            chars: list[str] = snap.get("selected_characters") or []
            if isinstance(chars, list):
                want = {str(x) for x in chars}
                for cb in self._char_checks:
                    cb.setChecked(cb.text() in want)

            bg = snap.get("background")
            if isinstance(bg, str) and bg.strip():
                # 兼容旧文案「透明背景」
                bg_clean = TRANSPARENT_BG if bg.strip() == "透明背景" else bg.strip()
                if self.bg_combo.findText(bg_clean) >= 0:
                    self.bg_combo.setCurrentText(bg_clean)

            vl = snap.get("voice_lang")
            if isinstance(vl, str) and vl.strip():
                vlow = vl.strip().lower()
                for i in range(self.voice_lang_combo.count()):
                    if str(self.voice_lang_combo.itemData(i) or "").lower() == vlow:
                        self.voice_lang_combo.setCurrentIndex(i)
                        vc = self.voice_lang_combo.itemData(i)
                        if vc:
                            self._ctx.config_manager.config.system_config.voice_language = (
                                str(vc)
                            )
                            self._ctx.config_manager.save_system_config()
                        break

            if snap.get("use_effect_yes") is True:
                self.use_effect_yes.setChecked(True)
            elif snap.get("use_effect_yes") is False:
                self.use_effect_no.setChecked(True)

            if snap.get("use_tr_yes") is True:
                self.use_tr_yes.setChecked(True)
            elif snap.get("use_tr_yes") is False:
                self.use_tr_no.setChecked(True)

            if snap.get("use_cg_yes") is True:
                self.use_cg_yes.setChecked(True)
            elif snap.get("use_cg_yes") is False:
                self.use_cg_no.setChecked(True)

            if snap.get("use_cot_yes") is True:
                self.use_cot_yes.setChecked(True)
            elif snap.get("use_cot_yes") is False:
                self.use_cot_no.setChecked(True)

            if snap.get("use_choice_yes") is True:
                self.use_choice_yes.setChecked(True)
            elif snap.get("use_choice_yes") is False:
                self.use_choice_no.setChecked(True)

            if snap.get("use_narration_yes") is True:
                self.use_narration_yes.setChecked(True)
            elif snap.get("use_narration_yes") is False:
                self.use_narration_no.setChecked(True)

            _msc = snap.get("max_speech_chars")
            if isinstance(_msc, int) and _msc >= 0:
                self.max_speech_chars_spin.setValue(_msc)
            elif isinstance(_msc, (float, str)):
                try:
                    self.max_speech_chars_spin.setValue(max(0, int(_msc)))
                except ValueError:
                    pass

            _mdi = snap.get("max_dialog_items")
            if isinstance(_mdi, int) and _mdi >= 0:
                self.max_dialog_items_spin.setValue(_mdi)
            elif isinstance(_mdi, (float, str)):
                try:
                    self.max_dialog_items_spin.setValue(max(0, int(_mdi)))
                except ValueError:
                    pass

            st = snap.get("scenario_text")
            sy = snap.get("system_template_text")
            if isinstance(st, str) or isinstance(sy, str):
                self.scenario_output.setPlainText(st if isinstance(st, str) else "")
                self.template_output.setPlainText(sy if isinstance(sy, str) else "")
            else:
                tt = snap.get("template_text")
                if isinstance(tt, str):
                    a, b = parse_stored_template(tt)
                    if b.strip():
                        self.scenario_output.setPlainText(a)
                        self.template_output.setPlainText(b)
                    else:
                        self.scenario_output.setPlainText(a)
                        self.template_output.clear()

            fn = snap.get("filename_stub")
            if isinstance(fn, str):
                self.filename_edit.setText(fn)

            tdrop = snap.get("template_file_dropdown")
            if isinstance(tdrop, str) and tdrop.strip():
                name = tdrop.strip()
                if self.template_combo.findText(name) >= 0:
                    self.template_combo.setCurrentText(name)

            isp = snap.get("init_sprite_path")
            if isinstance(isp, str):
                self.init_sprite_path.setText(isp)

            hf = snap.get("history_file")
            if isinstance(hf, str):
                self.history_file.setText(hf)

            rid = snap.get("room_id")
            if isinstance(rid, str):
                self.room_id.setText(rid)
        finally:
            self._suppress_auto_gen = False

    def _on_launch(self) -> None:
        self._save_launch_session()
        ucg = "是" if self.use_cg_yes.isChecked() else "否"
        msg = launch_chat(
            self._ctx,
            self.scenario_output.toPlainText(),
            self.template_output.toPlainText(),
            self.init_sprite_path.text().strip(),
            self.history_file.text().strip(),
            self.bg_combo.currentText(),
            ucg,
            self.room_id.text().strip(),
        )
        if msg:
            toast_success(self, "启动聊天", msg)

    def _refresh_template_combo(self, names: list[str] | None = None) -> None:
        self.template_combo.clear()
        path = self._path_obj
        path.mkdir(parents=True, exist_ok=True)
        files = names if names is not None else [f.name for f in path.iterdir() if f.is_file()]
        self.template_combo.addItems(sorted(files))

    def refresh_lists(self) -> None:
        self._suppress_auto_gen = True
        try:
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
                cb.toggled.connect(self._auto_generate)
                r, c = divmod(i, cols)
                self.char_grid.addWidget(cb, r, c)
            prev = self.bg_combo.currentText() if self.bg_combo.count() else ""
            self.bg_combo.clear()
            items = self._ctx.background_manager.get_background_name_list() + [TRANSPARENT_BG]
            self.bg_combo.addItems(items)
            if prev in items:
                self.bg_combo.setCurrentText(prev)
            elif prev == "透明背景":
                self.bg_combo.setCurrentText(TRANSPARENT_BG)
            else:
                self.bg_combo.setCurrentText(TRANSPARENT_BG)
            self._refresh_template_combo()
        finally:
            self._suppress_auto_gen = False
