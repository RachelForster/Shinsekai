"""API 设定标签页（PyQt）。"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
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
    QSizePolicy,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from llm.constants import LLM_BASE_URLS
from ui.settings_ui.context import SettingsUIContext


def _add_collapsible_block(tree: QTreeWidget, title: str, content: QWidget) -> None:
    """在树中增加一项：默认折叠，展开后显示 content。"""
    top = QTreeWidgetItem([title])
    tree.addTopLevelItem(top)
    child = QTreeWidgetItem()
    top.addChild(child)
    content.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
    tree.setItemWidget(child, 0, content)
    top.setExpanded(False)
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
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner)

        lay.addWidget(QLabel("<h2>API 配置</h2>"))

        _provider, _model, _base_url, _api_key = self._ctx.config_manager.get_llm_api_config()
        _is_streaming = self._ctx.config_manager.config.api_config.is_streaming

        # --- 区块：LLM API ---
        llm_panel = QWidget()
        llm_form = QFormLayout(llm_panel)
        self.llm_provider = QComboBox()
        self.llm_provider.addItems(list(LLM_BASE_URLS.keys()))
        idx = self.llm_provider.findText(_provider)
        if idx >= 0:
            self.llm_provider.setCurrentIndex(idx)
        self.llm_model = QLineEdit(_model)
        self.api_key = QLineEdit(_api_key)
        self.api_key.setEchoMode(QLineEdit.Password)
        self.base_url = QLineEdit(_base_url)
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
        llm_form.addRow("选择大语言模型供应商", self.llm_provider)
        llm_form.addRow("模型ID", self.llm_model)
        llm_form.addRow("LLM API Key", self.api_key)
        llm_form.addRow("LLM API 基础网址", self.base_url)
        llm_form.addRow("是否使用流式响应", stream_row)

        # --- 区块：高级 LLM ---
        adv = QWidget()
        adv_lay = QVBoxLayout(adv)
        adv_lay.setContentsMargins(0, 0, 0, 0)
        adv_lay.addWidget(
            QLabel(
                "说明：OpenAI/Deepseek/豆包/通义千问通常支持 temperature、presence_penalty、frequency_penalty；"
                "Claude 仅使用 temperature；Gemini 通过 OpenAI 兼容接口时按兼容能力处理。"
                "repetition_penalty 并非所有 provider 支持，不支持时会自动忽略。"
            )
        )
        adv_form = QFormLayout()
        ac = self._ctx.config_manager.config.api_config
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setSingleStep(0.05)
        self.temperature.setValue(float(ac.temperature))
        self.repetition_penalty = QDoubleSpinBox()
        self.repetition_penalty.setRange(0.5, 2.0)
        self.repetition_penalty.setSingleStep(0.05)
        self.repetition_penalty.setValue(float(ac.repetition_penalty))
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
        adv_form.addRow("temperature", self.temperature)
        adv_form.addRow("repetition_penalty", self.repetition_penalty)
        adv_form.addRow("presence_penalty", self.presence_penalty)
        adv_form.addRow("frequency_penalty", self.frequency_penalty)
        adv_form.addRow("最大上下文 token", self.max_context_tokens)
        adv_lay.addLayout(adv_form)

        main_tree = QTreeWidget()
        main_tree.setColumnCount(1)
        main_tree.setHeaderHidden(True)
        main_tree.setAnimated(True)
        main_tree.setIndentation(20)
        main_tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        _add_collapsible_block(main_tree, "LLM API 基础", llm_panel)
        _add_collapsible_block(main_tree, "高级 LLM 设置", adv)

        _gsv_url, _gpt_sovits_work_path, _tts_provider = self._ctx.config_manager.get_gpt_sovits_config()
        tts_box = QGroupBox()
        tts_lay = QVBoxLayout(tts_box)
        tts_lay.addWidget(QLabel("如果没有可以不填。如果你想让角色读出台词，就需要配置。"))
        tts_lay.addWidget(QLabel("说明：Genie TTS 适用于 CPU；GPT SoVITS 更依赖 GPU 性能。"))
        self.tts_provider = QComboBox()
        self.tts_provider.addItems(["Genie TTS", "GPT SoVITS"])
        if _tts_provider == "genie-tts":
            self.tts_provider.setCurrentText("Genie TTS")
        else:
            self.tts_provider.setCurrentText("GPT SoVITS")
        self.sovits_url = QLineEdit(_gsv_url)
        self.gpt_sovits_api_path = QLineEdit(_gpt_sovits_work_path)
        tts_form = QFormLayout()
        tts_form.addRow("TTS 引擎", self.tts_provider)
        tts_form.addRow("TTS引擎 API 调用地址", self.sovits_url)
        tts_form.addRow("TTS引擎 服务启动路径", self.gpt_sovits_api_path)
        tts_lay.addLayout(tts_form)

        comfy = QGroupBox("ComfyUI（可选，用于生成 CG）")
        cf = QFormLayout(comfy)
        api = self._ctx.config_manager.config.api_config
        self.t2i_url = QLineEdit(api.t2i_api_url)
        self.t2i_work_path = QLineEdit(api.t2i_work_path)
        self.t2i_default_workflow_path = QLineEdit(api.t2i_default_workflow_path)
        self.prompt_node_id = QLineEdit(api.t2i_prompt_node_id)
        self.output_node_id = QLineEdit(api.t2i_output_node_id)
        cf.addRow("ComfyUI API 调用地址", self.t2i_url)
        cf.addRow("ComfyUI 安装路径", self.t2i_work_path)
        cf.addRow("ComfyUI 默认工作流路径", self.t2i_default_workflow_path)
        cf.addRow("输入节点ID", self.prompt_node_id)
        cf.addRow("保存节点ID", self.output_node_id)
        tts_lay.addWidget(comfy)
        _add_collapsible_block(main_tree, "TTS 与 ComfyUI", tts_box)

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
            link.setTextInteractionFlags(Qt.TextBrowserInteraction)
            links_ly.addWidget(link)
        help_lbl = QLabel(
            "解压后请将目录填到「TTS引擎 服务启动路径」。GPT SoVITS 建议至少 11GB 磁盘，Genie TTS 约 4GB。"
        )
        help_lbl.setWordWrap(True)
        links_ly.addWidget(help_lbl)
        _add_collapsible_block(main_tree, "资源下载与说明", links_w)

        out_row = QHBoxLayout()
        out_row.addWidget(main_tree, stretch=2)
        self.api_output = QPlainTextEdit()
        self.api_output.setReadOnly(True)
        self.api_output.setMaximumHeight(200)
        self.api_output.setPlaceholderText("输出信息")
        out_row.addWidget(self.api_output, stretch=1)
        lay.addLayout(out_row)

        save = QPushButton("保存配置")
        save.clicked.connect(self._on_save)
        lay.addWidget(save, alignment=Qt.AlignLeft)

        self.llm_provider.currentTextChanged.connect(self._on_provider_change)
        root.addWidget(scroll)

    def _on_provider_change(self, name: str) -> None:
        try:
            base, model, key = self._ctx.config_manager.update_llm_info(name)
        except Exception as e:
            self.api_output.setPlainText(f"更新供应商信息失败: {e}")
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
        self.api_output.setPlainText(msg)
        QMessageBox.information(self, "API 配置", msg)
