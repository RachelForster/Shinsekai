"""API 设定标签页（PyQt）。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
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

from llm.constants import LLM_BASE_URLS
from ui.settings_ui.context import SettingsUIContext
from ui.settings_ui.feedback import feedback_result, message_fail


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

        lay.addWidget(QLabel("<h2>API 配置</h2>"))
        sub = QLabel(
            "配置大语言模型、TTS 与 ComfyUI；变更后请使用页底「保存配置」写入 api.yaml。"
        )
        sub.setObjectName("apiSettingsSubtitle")
        sub.setWordWrap(True)
        lay.addWidget(sub)

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
        self.llm_model.setPlaceholderText("如 gpt-4o、deepseek-chat 等，依供应商填写")
        self.api_key = QLineEdit(_api_key)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("切换供应商时可能自动带出新 Key")
        self.base_url = QLineEdit(_base_url)
        self.base_url.setPlaceholderText("OpenAI 兼容地址，以 /v1 结尾等")
        self.stream_yes = QRadioButton("是")
        self.stream_no = QRadioButton("否")
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
        llm_form.addRow("大语言模型供应商", self.llm_provider)
        llm_form.addRow("模型 ID", self.llm_model)
        llm_form.addRow("LLM API Key", self.api_key)
        llm_form.addRow("LLM 基础地址", self.base_url)
        llm_form.addRow("流式响应 (SSE)", stream_row)

        # --- 高级 LLM：双列表单节省纵向空间 ---
        adv = QWidget()
        adv_lay = QVBoxLayout(adv)
        adv_lay.setContentsMargins(0, 0, 0, 0)
        adv_help = QLabel(
            "各厂商对采样参数支持不同：OpenAI/Deepseek/豆包/通义等一般支持 temperature、presence、frequency；"
            "Claude 常用仅 temperature；Gemini 视兼容情况；repetition_penalty 若不支持会忽略。"
        )
        adv_help.setWordWrap(True)
        adv_help.setObjectName("apiSectionHint")
        adv_help.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        adv_lay.addWidget(adv_help)
        ac = self._ctx.config_manager.config.api_config
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setSingleStep(0.05)
        self.temperature.setValue(float(ac.temperature))
        self.temperature.setToolTip("0～2，越高越发散")
        self.repetition_penalty = QDoubleSpinBox()
        self.repetition_penalty.setRange(0.5, 2.0)
        self.repetition_penalty.setSingleStep(0.05)
        self.repetition_penalty.setValue(float(ac.repetition_penalty))
        self.repetition_penalty.setToolTip("部分端不支持则忽略")
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
        self.max_context_tokens.setToolTip("0 可表示不限制，依后端为准")
        adv_2col = QHBoxLayout()
        adv_l = QFormLayout()
        adv_l.setContentsMargins(0, 0, 8, 0)
        adv_l.addRow("temperature", self.temperature)
        adv_l.addRow("presence_penalty", self.presence_penalty)
        adv_l.addRow("最大上下文 token", self.max_context_tokens)
        adv_r = QFormLayout()
        adv_r.setContentsMargins(0, 0, 0, 0)
        adv_r.addRow("repetition_penalty", self.repetition_penalty)
        adv_r.addRow("frequency_penalty", self.frequency_penalty)
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
        _add_collapsible_block(main_tree, "LLM 基础", llm_panel, expanded=True)
        _add_collapsible_block(main_tree, "高级参数（采样/上下文）", adv, expanded=False)

        _gsv_url, _gpt_sovits_work_path, _tts_provider = self._ctx.config_manager.get_gpt_sovits_config()
        tts_w = QWidget()
        tts_lay = QVBoxLayout(tts_w)
        tts_lay.setContentsMargins(0, 0, 0, 0)
        tts_hint = QLabel(
            "不念台词可留空。需要时填写 API 与本地/整合包路径。Genie TTS 偏 CPU；"
            "GPT SoVITS 偏 GPU。整合包见下方「资源与说明」链接。"
        )
        tts_hint.setWordWrap(True)
        tts_hint.setObjectName("apiSectionHint")
        tts_lay.addWidget(tts_hint)
        self.tts_provider = QComboBox()
        self.tts_provider.addItems(["Genie TTS", "GPT SoVITS"])
        if _tts_provider == "genie-tts":
            self.tts_provider.setCurrentText("Genie TTS")
        else:
            self.tts_provider.setCurrentText("GPT SoVITS")
        self.sovits_url = QLineEdit(_gsv_url)
        self.sovits_url.setPlaceholderText("如 http://127.0.0.1:9880/ ")
        self.gpt_sovits_api_path = QLineEdit(_gpt_sovits_work_path)
        self.gpt_sovits_api_path.setPlaceholderText("整合包或工程根目录，按你的部署填写")
        tts_form = QFormLayout()
        tts_form.setContentsMargins(0, 0, 0, 0)
        tts_form.addRow("TTS 引擎", self.tts_provider)
        tts_form.addRow("TTS 服务地址", self.sovits_url)
        tts_form.addRow("TTS 服务/整合包路径", self.gpt_sovits_api_path)
        tts_lay.addLayout(tts_form)

        api = self._ctx.config_manager.config.api_config
        comfy_w = QWidget()
        cvl = QVBoxLayout(comfy_w)
        cvl.setContentsMargins(0, 0, 0, 0)
        c_hint = QLabel(
            "用于通过 ComfyUI 生图 / CG。需已部署 ComfyUI 并配好工作流，默认折叠以减少干扰。"
        )
        c_hint.setWordWrap(True)
        c_hint.setObjectName("apiSectionHint")
        cvl.addWidget(c_hint)
        cf = QFormLayout()
        cf.setContentsMargins(0, 0, 0, 0)
        self.t2i_url = QLineEdit(api.t2i_api_url)
        self.t2i_work_path = QLineEdit(api.t2i_work_path)
        self.t2i_default_workflow_path = QLineEdit(api.t2i_default_workflow_path)
        self.prompt_node_id = QLineEdit(api.t2i_prompt_node_id)
        self.output_node_id = QLineEdit(api.t2i_output_node_id)
        self.t2i_url.setPlaceholderText("如 http://127.0.0.1:8188")
        cf.addRow("ComfyUI API 地址", self.t2i_url)
        cf.addRow("ComfyUI 程序目录", self.t2i_work_path)
        cf.addRow("默认工作流文件", self.t2i_default_workflow_path)
        cf.addRow("正提示词节点 ID", self.prompt_node_id)
        cf.addRow("输出/保存节点 ID", self.output_node_id)
        cvl.addLayout(cf)
        _add_collapsible_block(main_tree, "TTS 语音", tts_w, expanded=True)
        _add_collapsible_block(main_tree, "ComfyUI 生图（可选）", comfy_w, expanded=False)

        links_w = QWidget()
        links_ly = QVBoxLayout(links_w)
        links_ly.setContentsMargins(0, 0, 0, 0)
        links_ly.addWidget(QLabel("下载 GPT SoVITS 整合包"))
        for text, url in [
            ("GPT-SOVITS github 源地址", "https://github.com/RVC-Boss/GPT-SoVITS"),
            ("点击下载 GPT-SOVITS 整合包 (ModelScope)", "https://www.modelscope.cn/models/FlowerCry/gpt-sovits-7z-pacakges/resolve/master/GPT-SoVITS-v2pro-20250604.7z"),
            ("50 系显卡整合包 (ModelScope)", "https://www.modelscope.cn/models/FlowerCry/gpt-sovits-7z-pacakges/resolve/master/GPT-SoVITS-v2pro-20250604-nvidia50.7z"),
        ]:
            link = QLabel(f'<a href="{url}">{text}</a>')
            link.setOpenExternalLinks(True)
            link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            links_ly.addWidget(link)
        help_lbl = QLabel(
            "解压后请将目录填到「TTS引擎 服务启动路径」。GPT SoVITS 建议至少 11GB 磁盘，Genie TTS 约 4GB。"
        )
        help_lbl.setWordWrap(True)
        links_ly.addWidget(help_lbl)
        _add_collapsible_block(main_tree, "资源与说明", links_w)

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
        save = QPushButton("保存配置")
        save.setMinimumWidth(160)
        save.setToolTip("将当前各栏写入项目 api.yaml")
        save.clicked.connect(self._on_save)
        save_row.addWidget(save)
        save_row.addStretch(1)
        fl.addLayout(save_row)
        root.addWidget(foot)

    def _on_provider_change(self, name: str) -> None:
        try:
            base, model, key = self._ctx.config_manager.update_llm_info(name)
        except Exception as e:
            message_fail(self, "API 配置", f"更新供应商信息失败: {e}")
            return
        self.base_url.setText(base)
        self.llm_model.setText(model)
        self.api_key.setText(key)

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
        feedback_result(self, "API 配置", msg)
