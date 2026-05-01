from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from plugins.moondream_vision.config_model import (
    MoondreamVisionConfig,
    default_config_path,
    load_config,
    save_config,
)
from sdk.plugin_host_context import PluginSettingsUIContext


class MoondreamVisionSettingsTab(QWidget):
    """设置 → 小工具：本地 Moondream2（Transformers）截屏识别。"""

    def __init__(
        self, plg: PluginSettingsUIContext, plugin_root: Path, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._plg = plg
        self._root = plugin_root
        self._path = default_config_path(plugin_root)
        self._build()
        self._load_into_ui()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        hint = QLabel(
            "使用 mss 截屏，通过 Hugging Face Transformers 加载本地缓存的 Moondream2（vikhyatk/moondream2），"
            "满足「屏幕相对上次识别有明显变化 / 鼠标移动 / （Windows）新开或切换前台窗口」时才会截屏送模型；"
            "并受下方「最短推理间隔」限制，避免过于频繁。\n\n"
            "请先安装插件依赖：\n"
            "pip install -r plugins/moondream_vision/requirements.txt\n\n"
            "首次启用后首次推理会从网络下载模型到 HF 缓存（可填「缓存目录」重定向）。\n\n"
            "INT8 / INT4：使用 bitsandbytes，需 NVIDIA GPU + CUDA；INT4 为 NF4 方案。"
        )
        hint.setWordWrap(True)
        lay.addWidget(hint)

        box = QGroupBox("Moondream 本地识屏")
        fl = QFormLayout(box)
        self._enabled = QCheckBox("启用识屏（差分 / 鼠标 / 系统窗口事件触发）")
        fl.addRow(self._enabled)
        self._model_id = QLineEdit()
        self._model_id.setPlaceholderText("vikhyatk/moondream2")
        fl.addRow("模型 ID:", self._model_id)
        self._revision = QLineEdit()
        self._revision.setPlaceholderText("可选，如 2025-01-09")
        fl.addRow("修订 revision:", self._revision)
        self._cache_dir = QLineEdit()
        self._cache_dir.setPlaceholderText("可选；留空用系统默认 HF 缓存")
        fl.addRow("缓存目录:", self._cache_dir)
        self._device = QComboBox()
        for label, data in (
            ("自动", "auto"),
            ("CUDA", "cuda"),
            ("Apple MPS", "mps"),
            ("CPU", "cpu"),
        ):
            self._device.addItem(label, data)
        fl.addRow("设备:", self._device)
        self._quantization = QComboBox()
        for label, data in (
            ("无（浮点）", "none"),
            ("INT8", "int8"),
            ("INT4（NF4）", "int4"),
        ):
            self._quantization.addItem(label, data)
        self._quantization.setToolTip(
            "INT8 / INT4 需 NVIDIA CUDA 与 bitsandbytes；与 Apple MPS / 纯 CPU 不兼容。"
            "视觉塔 vision 不参与量化（仍为 FP），以兼容 Moondream 自定义前向；仅语言部分减压显存。"
        )
        fl.addRow("权重量化:", self._quantization)
        self._motion_poll = QDoubleSpinBox()
        self._motion_poll.setRange(0.12, 3.0)
        self._motion_poll.setSingleStep(0.05)
        self._motion_poll.setSuffix(" 秒")
        self._motion_poll.setToolTip("采样鼠标、窗口与缩略图差分的间隔；越小越灵敏、占用略高")
        fl.addRow("触发采样间隔:", self._motion_poll)
        self._diff_thr = QDoubleSpinBox()
        self._diff_thr.setRange(0.003, 0.35)
        self._diff_thr.setDecimals(3)
        self._diff_thr.setSingleStep(0.002)
        self._diff_thr.setToolTip("相对上次识别成功的缩略图，变化像素占比阈值")
        fl.addRow("屏幕差分阈值:", self._diff_thr)
        self._mouse_pct = QDoubleSpinBox()
        self._mouse_pct.setRange(0.02, 25.0)
        self._mouse_pct.setDecimals(2)
        self._mouse_pct.setSingleStep(0.05)
        self._mouse_pct.setSuffix(" %")
        self._mouse_pct.setToolTip(
            "相对当前「显示器索引」对应画面的宽/高较大一边；移动直线距离超过该比例视为活动"
        )
        fl.addRow("鼠标移动阈值(% 屏):", self._mouse_pct)
        self._interval = QDoubleSpinBox()
        self._interval.setRange(5.0, 600.0)
        self._interval.setSingleStep(1.0)
        self._interval.setSuffix(" 秒")
        self._interval.setToolTip("两次送模型推理之间的最短间隔（满足触发条件后仍可能排队等待）")
        fl.addRow("最短推理间隔:", self._interval)
        self._monitor = QSpinBox()
        self._monitor.setRange(0, 16)
        self._monitor.setToolTip("mss：0=所有显示器合成；1 通常为第一块物理屏")
        fl.addRow("显示器索引:", self._monitor)
        self._question = QTextEdit()
        self._question.setMaximumHeight(90)
        self._question.setPlaceholderText("发给视觉模型的提问")
        fl.addRow("识别提问:", self._question)
        self._prefix = QLineEdit()
        self._prefix.setPlaceholderText("发到聊天里的前缀")
        fl.addRow("消息前缀:", self._prefix)

        row = QHBoxLayout()
        save_btn = QPushButton("保存设置")
        save_btn.clicked.connect(self._on_save)
        row.addWidget(save_btn)
        row.addStretch(1)
        fl.addRow(row)
        lay.addWidget(box)
        lay.addStretch(1)

    def _quant_index(self, mode: str) -> int:
        m = (mode or "none").strip().lower()
        for i in range(self._quantization.count()):
            if str(self._quantization.itemData(i)).lower() == m:
                return i
        return 0

    def _device_index(self, device: str) -> int:
        d = (device or "auto").strip().lower()
        for i in range(self._device.count()):
            if str(self._device.itemData(i)).lower() == d:
                return i
        return 0

    def _load_into_ui(self) -> None:
        c = load_config(self._path)
        self._enabled.setChecked(c.enabled)
        self._model_id.setText(c.model_id)
        self._revision.setText(c.revision)
        self._cache_dir.setText(c.cache_dir)
        self._device.setCurrentIndex(self._device_index(c.device))
        self._quantization.setCurrentIndex(self._quant_index(c.quantization))
        self._motion_poll.setValue(c.motion_poll_sec)
        self._diff_thr.setValue(c.diff_threshold)
        self._mouse_pct.setValue(c.mouse_move_percent)
        self._interval.setValue(c.interval_sec)
        self._monitor.setValue(c.monitor_index)
        self._question.setPlainText(c.question)
        self._prefix.setText(c.message_prefix)

    def _read_from_ui(self) -> MoondreamVisionConfig:
        c = MoondreamVisionConfig(
            enabled=self._enabled.isChecked(),
            model_id=self._model_id.text().strip() or "vikhyatk/moondream2",
            revision=self._revision.text().strip(),
            cache_dir=self._cache_dir.text().strip(),
            device=str(self._device.currentData() or "auto"),
            quantization=str(self._quantization.currentData() or "none"),
            motion_poll_sec=float(self._motion_poll.value()),
            diff_threshold=float(self._diff_thr.value()),
            mouse_move_percent=float(self._mouse_pct.value()),
            interval_sec=float(self._interval.value()),
            monitor_index=int(self._monitor.value()),
            question=self._question.toPlainText().strip() or MoondreamVisionConfig.question,
            message_prefix=self._prefix.text(),
        )
        c.clamp()
        return c

    def _on_save(self) -> None:
        c = self._read_from_ui()
        save_config(self._path, c)
        QMessageBox.information(
            self,
            "Moondream",
            "已保存。修改模型 ID、设备、量化、缓存目录后，建议重启聊天主程序以重新加载权重。",
        )
