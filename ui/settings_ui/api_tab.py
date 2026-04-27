"""API 设定标签页（PyQt）。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from i18n import init_i18n, normalize_lang, tr as tr_i18n
from llm.constants import LLM_BASE_URLS
from ui.settings_ui.context import SettingsUIContext
from ui.settings_ui.feedback import feedback_result, message_fail
from ui.settings_ui.tts_bundle_download_dialog import TtsBundleDownloadDialog


def _add_collapsible_block(
    tree: QTreeWidget, title: str, content: QWidget, *, expanded: bool = False
) -> None:
    """在树中增加一项，展开后显示 content。"""
    top = QTreeWidgetItem([title])
    tree.addTopLevelItem(top)
    child = QTreeWidgetItem()
    top.addChild(child)
    content.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
    )
    tree.setItemWidget(child, 0, content)
    top.setExpanded(expanded)
    # 占满列宽、避免子行缩进过窄
    child.setFirstColumnSpanned(True)


class ApiSettingsTab(QWidget):
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
        lay.setSpacing(10)

        self._lang_group = QGroupBox(tr_i18n("lang.group"))
        lgl = QVBoxLayout(self._lang_group)
        self._lang_hint = QLabel(tr_i18n("lang.hint"))
        self._lang_hint.setWordWrap(True)
        self._lang_combo = QComboBox()
        for label, code in (("简体中文", "zh_CN"), ("English", "en"), ("日本語", "ja")):
            self._lang_combo.addItem(label, code)
        _lc = normalize_lang(
            str(self._ctx.config_manager.config.system_config.ui_language)
        )
        self._lang_combo.setCurrentIndex(
            {"zh_CN": 0, "en": 1, "ja": 2}.get(_lc, 0)
        )
        self._lang_combo.activated.connect(self._on_language_activated)
        lgh = QHBoxLayout()
        lgh.addWidget(self._lang_combo)
        lgh.addStretch(1)
        lgl.addLayout(lgh)
        lgl.addWidget(self._lang_hint)
        lay.addWidget(self._lang_group)

        self._api_h2 = QLabel(tr_i18n("api.h2"))
        self._api_sub = QLabel(tr_i18n("api.subtitle"))
        self._api_sub.setObjectName("apiSettingsSubtitle")
        self._api_sub.setWordWrap(True)
        lay.addWidget(self._api_h2)
        lay.addWidget(self._api_sub)

        _provider, _model, _base_url, _api_key = self._ctx.config_manager.get_llm_api_config()
        _is_streaming = self._ctx.config_manager.config.api_config.is_streaming

        # --- 区块：LLM API ---
        llm_panel = QWidget()
        llm_form = QFormLayout(llm_panel)
        llm_form.setContentsMargins(0, 0, 0, 0)
        self.llm_provider = QComboBox()
        self.llm_provider.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.llm_provider.addItems(list(LLM_BASE_URLS.keys()))
        idx = self.llm_provider.findText(_provider)
        if idx >= 0:
            self.llm_provider.setCurrentIndex(idx)
        self.llm_model = QLineEdit(_model)
        self.llm_model.setPlaceholderText(tr_i18n("api.form.ph_model"))
        self.api_key = QLineEdit(_api_key)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText(tr_i18n("api.form.ph_key"))
        self.base_url = QLineEdit(_base_url)
        self.base_url.setPlaceholderText(tr_i18n("api.form.ph_base"))
        self.stream_yes = QRadioButton(tr_i18n("common.yes"))
        self.stream_no = QRadioButton(tr_i18n("common.no"))
        if _is_streaming:
            self.stream_yes.setChecked(True)
        else:
            self.stream_no.setChecked(True)
        stream_grp = QButtonGroup(self)
        stream_grp.addButton(self.stream_yes)
        stream_grp.addButton(self.stream_no)
        stream_row = QWidget()
        sr = QHBoxLayout(stream_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.addWidget(self.stream_yes)
        sr.addWidget(self.stream_no)
        self._f_llm_provider = QLabel(tr_i18n("api.form.llm_provider"))
        self._f_model = QLabel(tr_i18n("api.form.model_id"))
        self._f_api_key = QLabel(tr_i18n("api.form.api_key"))
        self._f_base = QLabel(tr_i18n("api.form.base_url"))
        self._f_stream = QLabel(tr_i18n("api.form.stream"))
        llm_form.addRow(self._f_llm_provider, self.llm_provider)
        llm_form.addRow(self._f_model, self.llm_model)
        llm_form.addRow(self._f_api_key, self.api_key)
        llm_form.addRow(self._f_base, self.base_url)
        llm_form.addRow(self._f_stream, stream_row)

        # --- 高级 LLM：双列表单节省纵向空间 ---
        adv = QWidget()
        adv_lay = QVBoxLayout(adv)
        adv_lay.setContentsMargins(0, 0, 0, 0)
        self._adv_help = QLabel(tr_i18n("api.adv.help"))
        self._adv_help.setWordWrap(True)
        self._adv_help.setObjectName("apiSectionHint")
        self._adv_help.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        adv_lay.addWidget(self._adv_help)
        ac = self._ctx.config_manager.config.api_config
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setSingleStep(0.05)
        self.temperature.setValue(float(ac.temperature))
        self.temperature.setToolTip(tr_i18n("api.adv.tt_temp"))
        self.repetition_penalty = QDoubleSpinBox()
        self.repetition_penalty.setRange(0.5, 2.0)
        self.repetition_penalty.setSingleStep(0.05)
        self.repetition_penalty.setValue(float(ac.repetition_penalty))
        self.repetition_penalty.setToolTip(tr_i18n("api.adv.tt_rep"))
        self.presence_penalty = QDoubleSpinBox()
        self.presence_penalty.setRange(-2.0, 2.0)
        self.presence_penalty.setSingleStep(0.05)
        self.presence_penalty.setValue(float(ac.presence_penalty))
        self.frequency_penalty = QDoubleSpinBox()
        self.frequency_penalty.setRange(-2.0, 2.0)
        self.frequency_penalty.setSingleStep(0.05)
        self.frequency_penalty.setValue(float(ac.frequency_penalty))
        self.max_context_tokens = QSpinBox()
        self.max_context_tokens.setRange(0, 2_000_000)
        self.max_context_tokens.setValue(int(ac.max_context_tokens))
        self.max_context_tokens.setToolTip(tr_i18n("api.adv.tt_maxctx"))
        adv_2col = QHBoxLayout()
        adv_l = QFormLayout()
        adv_l.setContentsMargins(0, 0, 8, 0)
        self._adv_l_temp = QLabel(tr_i18n("api.adv.l_temp"))
        self._adv_l_presence = QLabel(tr_i18n("api.adv.l_presence"))
        self._adv_l_max = QLabel(tr_i18n("api.adv.l_maxctx"))
        self._adv_l_rep = QLabel(tr_i18n("api.adv.l_rep"))
        self._adv_l_freq = QLabel(tr_i18n("api.adv.l_freq"))
        adv_l.addRow(self._adv_l_temp, self.temperature)
        adv_l.addRow(self._adv_l_presence, self.presence_penalty)
        adv_l.addRow(self._adv_l_max, self.max_context_tokens)
        adv_r = QFormLayout()
        adv_r.setContentsMargins(0, 0, 0, 0)
        adv_r.addRow(self._adv_l_rep, self.repetition_penalty)
        adv_r.addRow(self._adv_l_freq, self.frequency_penalty)
        adv_2col.addLayout(adv_l, stretch=1)
        adv_2col.addLayout(adv_r, stretch=1)
        adv_lay.addLayout(adv_2col)

        main_tree = QTreeWidget()
        main_tree.setColumnCount(1)
        main_tree.setHeaderHidden(True)
        main_tree.setAnimated(True)
        main_tree.setIndentation(18)
        main_tree.setMinimumHeight(220)
        main_tree.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        _add_collapsible_block(main_tree, tr_i18n("api.tree.llm"), llm_panel, expanded=True)
        _add_collapsible_block(main_tree, tr_i18n("api.tree.adv"), adv, expanded=False)

        _gsv_url, _gpt_sovits_work_path, _tts_provider = self._ctx.config_manager.get_gpt_sovits_config()
        tts_w = QWidget()
        tts_lay = QVBoxLayout(tts_w)
        tts_lay.setContentsMargins(0, 0, 0, 0)
        tts_dl_box = QWidget()
        tts_dl_lay = QVBoxLayout(tts_dl_box)
        tts_dl_lay.setContentsMargins(0, 0, 0, 0)
        self._tts_dl_short_hint = QLabel(tr_i18n("api.tts.env.inline_hint"))
        self._tts_dl_short_hint.setWordWrap(True)
        self._tts_dl_short_hint.setObjectName("apiSectionHint")
        self._tts_dl_btn = QPushButton(tr_i18n("api.tts.env.btn_dl"))
        self._tts_dl_btn.clicked.connect(self._on_tts_bundle_download)
        tdlh = QHBoxLayout()
        tdlh.setContentsMargins(0, 0, 0, 0)
        tdlh.addWidget(self._tts_dl_btn)
        tdlh.addStretch(1)
        tts_dl_lay.addWidget(self._tts_dl_short_hint)
        tts_dl_lay.addLayout(tdlh)
        tts_lay.addWidget(tts_dl_box)

        self._tts_hint = QLabel(tr_i18n("api.tts.hint"))
        self._tts_hint.setWordWrap(True)
        self._tts_hint.setObjectName("apiSectionHint")
        tts_lay.addWidget(self._tts_hint)
        self.tts_provider = QComboBox()
        self.tts_provider.addItems(["Genie TTS", "GPT SoVITS"])
        if _tts_provider == "genie-tts":
            self.tts_provider.setCurrentText("Genie TTS")
        else:
            self.tts_provider.setCurrentText("GPT SoVITS")
        self.sovits_url = QLineEdit(_gsv_url)
        self.sovits_url.setPlaceholderText(tr_i18n("api.tts.ph_url"))
        self.gpt_sovits_api_path = QLineEdit(_gpt_sovits_work_path)
        self.gpt_sovits_api_path.setPlaceholderText(tr_i18n("api.tts.ph_path"))
        tts_form = QFormLayout()
        tts_form.setContentsMargins(0, 0, 0, 0)
        self._tts_engine = QLabel(tr_i18n("api.tts.engine"))
        self._tts_url = QLabel(tr_i18n("api.tts.url"))
        self._tts_path = QLabel(tr_i18n("api.tts.path"))
        tts_form.addRow(self._tts_engine, self.tts_provider)
        tts_form.addRow(self._tts_url, self.sovits_url)
        tts_form.addRow(self._tts_path, self.gpt_sovits_api_path)
        tts_lay.addLayout(tts_form)

        api = self._ctx.config_manager.config.api_config
        comfy_w = QWidget()
        cvl = QVBoxLayout(comfy_w)
        cvl.setContentsMargins(0, 0, 0, 0)
        self._c_hint = QLabel(tr_i18n("api.comfy.hint"))
        self._c_hint.setWordWrap(True)
        self._c_hint.setObjectName("apiSectionHint")
        cvl.addWidget(self._c_hint)
        cf = QFormLayout()
        cf.setContentsMargins(0, 0, 0, 0)
        self.t2i_url = QLineEdit(api.t2i_api_url)
        self.t2i_work_path = QLineEdit(api.t2i_work_path)
        self.t2i_default_workflow_path = QLineEdit(api.t2i_default_workflow_path)
        self.prompt_node_id = QLineEdit(api.t2i_prompt_node_id)
        self.output_node_id = QLineEdit(api.t2i_output_node_id)
        self.t2i_url.setPlaceholderText(tr_i18n("api.comfy.ph_t2i"))
        self._cf_t2i = QLabel(tr_i18n("api.comfy.t2i_url"))
        self._cf_dir = QLabel(tr_i18n("api.comfy.t2i_dir"))
        self._cf_wf = QLabel(tr_i18n("api.comfy.workflow"))
        self._cf_p = QLabel(tr_i18n("api.comfy.prompt_id"))
        self._cf_o = QLabel(tr_i18n("api.comfy.out_id"))
        cf.addRow(self._cf_t2i, self.t2i_url)
        cf.addRow(self._cf_dir, self.t2i_work_path)
        cf.addRow(self._cf_wf, self.t2i_default_workflow_path)
        cf.addRow(self._cf_p, self.prompt_node_id)
        cf.addRow(self._cf_o, self.output_node_id)
        cvl.addLayout(cf)
        _add_collapsible_block(main_tree, tr_i18n("api.tree.tts"), tts_w, expanded=True)
        _add_collapsible_block(main_tree, tr_i18n("api.tree.comfy"), comfy_w, expanded=False)

        links_w = QWidget()
        links_ly = QVBoxLayout(links_w)
        links_ly.setContentsMargins(0, 0, 0, 0)
        self._links_title = QLabel(tr_i18n("api.links.title"))
        links_ly.addWidget(self._links_title)
        self._res_link_data = [
            ("api.links.link1", "https://github.com/RVC-Boss/GPT-SoVITS"),
            (
                "api.links.link2",
                "https://www.modelscope.cn/models/FlowerCry/gpt-sovits-7z-pacakges/resolve/master/GPT-SoVITS-v2pro-20250604.7z",
            ),
            (
                "api.links.link3",
                "https://www.modelscope.cn/models/FlowerCry/gpt-sovits-7z-pacakges/resolve/master/GPT-SoVITS-v2pro-20250604-nvidia50.7z",
            ),

            ("api.links.link4", "https://github.com/High-Logic/Genie-TTS"),
            (
                "api.links.link5",
                "https://www.modelscope.cn/models/twillzxy/genie-tts-server/resolve/master/Genie-TTS%20Server.7z",
            ),
        ]
        self._res_link_labels: list[QLabel] = []
        for key, url in self._res_link_data:
            lb = QLabel(f'<a href="{url}">{tr_i18n(key)}</a>')
            lb.setOpenExternalLinks(True)
            lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            self._res_link_labels.append(lb)
            links_ly.addWidget(lb)
        self._links_help = QLabel(tr_i18n("api.links.help"))
        self._links_help.setWordWrap(True)
        links_ly.addWidget(self._links_help)
        _add_collapsible_block(main_tree, tr_i18n("api.tree.resource"), links_w)

        self._main_tree = main_tree
        lay.addWidget(main_tree, stretch=1)

        self.llm_provider.currentTextChanged.connect(self._on_provider_change)
        root.addWidget(scroll, stretch=1)

        foot = QFrame()
        foot.setObjectName("apiTabFooter")
        foot.setFrameShape(QFrame.Shape.NoFrame)
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        fl.addWidget(sep)
        save_row = QHBoxLayout()
        save_row.setContentsMargins(12, 8, 12, 8)
        self._api_save = QPushButton(tr_i18n("api.save"))
        self._api_save.setMinimumWidth(160)
        self._api_save.setToolTip(tr_i18n("api.save_tip"))
        self._api_save.clicked.connect(self._on_save)
        save_row.addWidget(self._api_save)
        save_row.addStretch(1)
        fl.addLayout(save_row)
        root.addWidget(foot)

    def _on_language_activated(self, index: int) -> None:
        code = self._lang_combo.itemData(index) or "zh_CN"
        self._ctx.config_manager.set_ui_language(code)
        init_i18n(code)
        w = self.window()
        if w is not None and hasattr(w, "apply_i18n"):
            w.apply_i18n()

    def apply_i18n(self) -> None:
        self._api_h2.setText(tr_i18n("api.h2"))
        self._api_sub.setText(tr_i18n("api.subtitle"))
        self._lang_group.setTitle(tr_i18n("lang.group"))
        self._lang_hint.setText(tr_i18n("lang.hint"))
        self._api_save.setText(tr_i18n("api.save"))
        self._api_save.setToolTip(tr_i18n("api.save_tip"))
        self._f_llm_provider.setText(tr_i18n("api.form.llm_provider"))
        self._f_model.setText(tr_i18n("api.form.model_id"))
        self._f_api_key.setText(tr_i18n("api.form.api_key"))
        self._f_base.setText(tr_i18n("api.form.base_url"))
        self._f_stream.setText(tr_i18n("api.form.stream"))
        self.llm_model.setPlaceholderText(tr_i18n("api.form.ph_model"))
        self.api_key.setPlaceholderText(tr_i18n("api.form.ph_key"))
        self.base_url.setPlaceholderText(tr_i18n("api.form.ph_base"))
        self._adv_help.setText(tr_i18n("api.adv.help"))
        self.temperature.setToolTip(tr_i18n("api.adv.tt_temp"))
        self.repetition_penalty.setToolTip(tr_i18n("api.adv.tt_rep"))
        self.max_context_tokens.setToolTip(tr_i18n("api.adv.tt_maxctx"))
        self._adv_l_temp.setText(tr_i18n("api.adv.l_temp"))
        self._adv_l_rep.setText(tr_i18n("api.adv.l_rep"))
        self._adv_l_presence.setText(tr_i18n("api.adv.l_presence"))
        self._adv_l_freq.setText(tr_i18n("api.adv.l_freq"))
        self._adv_l_max.setText(tr_i18n("api.adv.l_maxctx"))
        self._tts_hint.setText(tr_i18n("api.tts.hint"))
        self._tts_dl_short_hint.setText(tr_i18n("api.tts.env.inline_hint"))
        self._tts_dl_btn.setText(tr_i18n("api.tts.env.btn_dl"))
        self.sovits_url.setPlaceholderText(tr_i18n("api.tts.ph_url"))
        self.gpt_sovits_api_path.setPlaceholderText(tr_i18n("api.tts.ph_path"))
        self._tts_engine.setText(tr_i18n("api.tts.engine"))
        self._tts_url.setText(tr_i18n("api.tts.url"))
        self._tts_path.setText(tr_i18n("api.tts.path"))
        self._c_hint.setText(tr_i18n("api.comfy.hint"))
        self.t2i_url.setPlaceholderText(tr_i18n("api.comfy.ph_t2i"))
        self._cf_t2i.setText(tr_i18n("api.comfy.t2i_url"))
        self._cf_dir.setText(tr_i18n("api.comfy.t2i_dir"))
        self._cf_wf.setText(tr_i18n("api.comfy.workflow"))
        self._cf_p.setText(tr_i18n("api.comfy.prompt_id"))
        self._cf_o.setText(tr_i18n("api.comfy.out_id"))
        self._links_title.setText(tr_i18n("api.links.title"))
        for lb, (key, url) in zip(self._res_link_labels, self._res_link_data, strict=True):
            lb.setText(f'<a href="{url}">{tr_i18n(key)}</a>')
        self._links_help.setText(tr_i18n("api.links.help"))
        self.stream_yes.setText(tr_i18n("common.yes"))
        self.stream_no.setText(tr_i18n("common.no"))
        if self._main_tree and self._main_tree.topLevelItemCount() >= 5:
            for i, k in enumerate(
                ("tree.llm", "tree.adv", "tree.tts", "tree.comfy", "tree.resource")
            ):
                it = self._main_tree.topLevelItem(i)
                if it is not None:
                    it.setText(0, tr_i18n(f"api.{k}"))
        sidx = {"zh_CN": 0, "en": 1, "ja": 2}.get(
            normalize_lang(
                str(self._ctx.config_manager.config.system_config.ui_language)
            ),
            0,
        )
        self._lang_combo.blockSignals(True)
        self._lang_combo.setCurrentIndex(sidx)
        self._lang_combo.blockSignals(False)
        for w in QApplication.topLevelWidgets():
            if isinstance(w, TtsBundleDownloadDialog) and w.isVisible():
                w.apply_i18n()

    def _on_provider_change(self, name: str) -> None:
        try:
            base, model, key = self._ctx.config_manager.update_llm_info(name)
        except Exception as e:
            message_fail(
                self,
                tr_i18n("api.msg.config"),
                tr_i18n("api.msg.provider_fail").format(e=e),
            )
            return
        self.base_url.setText(base)
        self.llm_model.setText(model)
        self.api_key.setText(key)

    def _on_tts_bundle_download(self) -> None:
        dlg = TtsBundleDownloadDialog(
            self,
            gpt_sovits_api_path=self.gpt_sovits_api_path,
            tts_provider=self.tts_provider,
        )
        dlg.exec()

    def _on_save(self) -> None:
        is_streaming = "是" if self.stream_yes.isChecked() else "否"
        msg = self._ctx.config_manager.save_api_config_new(
            self.llm_provider.currentText(),
            self.llm_model.text().strip(),
            self.api_key.text(),
            self.base_url.text().strip(),
            is_streaming,
            self.tts_provider.currentText(),
            self.sovits_url.text().strip(),
            self.gpt_sovits_api_path.text().strip(),
            self.t2i_url.text().strip(),
            self.t2i_work_path.text().strip(),
            self.t2i_default_workflow_path.text().strip(),
            self.prompt_node_id.text().strip(),
            self.output_node_id.text().strip(),
            self.temperature.value(),
            self.repetition_penalty.value(),
            self.presence_penalty.value(),
            self.frequency_penalty.value(),
            self.max_context_tokens.value(),
        )
        feedback_result(self, tr_i18n("api.msg.config"), msg)
