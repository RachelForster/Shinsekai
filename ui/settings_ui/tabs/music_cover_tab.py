"""音乐翻唱流水线标签页（PySide6）。"""

from __future__ import annotations

import traceback

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QCheckBox,
)

from live.music_cover_pipeline import format_pipeline_log, run_pipeline, search_preview
from ui.settings_ui.context import SettingsUIContext


class MusicCoverSettingsTab(QWidget):
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

        intro = QLabel(
            "下载 → 歌词/字幕 → UVR 分离 → RVC 翻唱 → 合成。修改路径后请先保存配置，再执行流水线。"
        )
        intro.setWordWrap(True)
        lay.addWidget(intro)

        _msc = self._ctx.config_manager.config.system_config
        left = QVBoxLayout()
        box = QGroupBox("流水线与工具路径")
        form = QFormLayout(box)
        self.mc_work_dir = QLineEdit(_msc.music_cover_work_dir or "./data/music_cover")
        self.mc_yt_dlp = QLineEdit(_msc.music_cover_yt_dlp_exe or "")
        self.mc_ffmpeg = QLineEdit(_msc.music_cover_ffmpeg_exe or "")
        self.mc_uvr_tpl = QPlainTextEdit(_msc.music_cover_uvr_cmd_template or "")
        self.mc_uvr_tpl.setMaximumHeight(70)
        self.mc_rvc_tpl = QPlainTextEdit(_msc.music_cover_rvc_cmd_template or "")
        self.mc_rvc_tpl.setMaximumHeight(70)
        self.mc_rvc_model = QLineEdit(_msc.music_cover_rvc_model_path or "")
        self.mc_rvc_index = QLineEdit(_msc.music_cover_rvc_index_path or "")
        form.addRow("工作目录", self.mc_work_dir)
        form.addRow("yt-dlp 路径（可空=PATH）", self.mc_yt_dlp)
        form.addRow("ffmpeg 路径（可空=PATH）", self.mc_ffmpeg)
        form.addRow("UVR/分离 命令模板", self.mc_uvr_tpl)
        form.addRow("RVC 命令模板", self.mc_rvc_tpl)
        form.addRow("RVC 模型 .pth", self.mc_rvc_model)
        form.addRow("RVC 索引 .index（可选）", self.mc_rvc_index)

        rvc_adv = QGroupBox("rvc-python 推理参数")
        ra = QFormLayout(rvc_adv)
        self.mc_rvc_device = QLineEdit(_msc.music_cover_rvc_device or "cuda:0")
        self.mc_rvc_ver = QComboBox()
        self.mc_rvc_ver.addItems(["v1", "v2"])
        self.mc_rvc_ver.setCurrentText(_msc.music_cover_rvc_model_version or "v2")
        self.mc_rvc_f0 = QComboBox()
        self.mc_rvc_f0.addItems(["rmvpe", "harvest", "crepe", "pm"])
        self.mc_rvc_f0.setCurrentText(_msc.music_cover_rvc_f0_method or "rmvpe")
        self.mc_rvc_pitch = QDoubleSpinBox()
        self.mc_rvc_pitch.setRange(-12, 12)
        self.mc_rvc_pitch.setSingleStep(0.5)
        self.mc_rvc_pitch.setValue(float(_msc.music_cover_rvc_pitch))
        self.mc_rvc_ir = QDoubleSpinBox()
        self.mc_rvc_ir.setRange(0.0, 1.0)
        self.mc_rvc_ir.setSingleStep(0.05)
        self.mc_rvc_ir.setValue(float(_msc.music_cover_rvc_index_rate))
        self.mc_rvc_fr = QSpinBox()
        self.mc_rvc_fr.setRange(0, 7)
        self.mc_rvc_fr.setValue(int(_msc.music_cover_rvc_filter_radius))
        self.mc_rvc_rsr = QSpinBox()
        self.mc_rvc_rsr.setRange(0, 192000)
        self.mc_rvc_rsr.setValue(int(_msc.music_cover_rvc_resample_sr))
        self.mc_rvc_rmr = QDoubleSpinBox()
        self.mc_rvc_rmr.setRange(0.0, 1.0)
        self.mc_rvc_rmr.setSingleStep(0.05)
        self.mc_rvc_rmr.setValue(float(_msc.music_cover_rvc_rms_mix_rate))
        self.mc_rvc_pr = QDoubleSpinBox()
        self.mc_rvc_pr.setRange(0.0, 0.5)
        self.mc_rvc_pr.setSingleStep(0.01)
        self.mc_rvc_pr.setValue(float(_msc.music_cover_rvc_protect))
        ra.addRow("device", self.mc_rvc_device)
        ra.addRow("模型版本", self.mc_rvc_ver)
        ra.addRow("音高 method", self.mc_rvc_f0)
        ra.addRow("变调 pitch（半音）", self.mc_rvc_pitch)
        ra.addRow("index_rate", self.mc_rvc_ir)
        ra.addRow("filter_radius", self.mc_rvc_fr)
        ra.addRow("resample_sr（0=不重采样）", self.mc_rvc_rsr)
        ra.addRow("rms_mix_rate", self.mc_rvc_rmr)
        ra.addRow("protect", self.mc_rvc_pr)
        left.addWidget(box)
        left.addWidget(rvc_adv)

        save_btn = QPushButton("保存翻唱流水线配置")
        save_btn.clicked.connect(self._on_save)
        left.addWidget(save_btn)
        self.mc_save_out = QPlainTextEdit()
        self.mc_save_out.setReadOnly(True)
        self.mc_save_out.setMaximumHeight(80)
        left.addWidget(self.mc_save_out)

        right = QVBoxLayout()
        self.mc_src = QComboBox()
        self.mc_src.addItems(["YouTube", "Bilibili", "完整 URL"])
        self.mc_query = QPlainTextEdit()
        self.mc_query.setMaximumHeight(80)
        self.mc_query.setPlaceholderText("搜索词或 URL")
        self.mc_pick = QSlider(Qt.Orientation.Horizontal)
        self.mc_pick.setRange(0, 7)
        self.mc_pick.setValue(0)
        self.mc_pick_label = QLabel("选用第 0 条")
        self.mc_pick.valueChanged.connect(lambda v: self.mc_pick_label.setText(f"选用第 {v} 条"))
        self.mc_skip_rvc = QCheckBox("跳过 RVC（仅用分离后人声合成）")
        search_btn = QPushButton("预览搜索结果")
        search_btn.clicked.connect(self._on_search)
        run_btn = QPushButton("执行完整流水线")
        run_btn.clicked.connect(self._on_run)
        self.mc_log = QPlainTextEdit()
        self.mc_log.setReadOnly(True)
        self.mc_log.setMinimumHeight(200)
        self.mc_audio_path = QLineEdit()
        self.mc_audio_path.setPlaceholderText("成品 wav 路径（执行后显示）")
        self.mc_audio_path.setReadOnly(True)

        right.addWidget(QLabel("来源"))
        right.addWidget(self.mc_src)
        right.addWidget(QLabel("搜索词或 URL"))
        right.addWidget(self.mc_query)
        right.addWidget(self.mc_pick_label)
        right.addWidget(self.mc_pick)
        right.addWidget(self.mc_skip_rvc)
        right.addWidget(search_btn)
        right.addWidget(run_btn)
        right.addWidget(QLabel("日志"))
        right.addWidget(self.mc_log)
        right.addWidget(QLabel("成品试听路径"))
        right.addWidget(self.mc_audio_path)

        row = QHBoxLayout()
        row.addLayout(left, stretch=1)
        row.addLayout(right, stretch=1)
        lay.addLayout(row)

        root.addWidget(scroll)

    def _mc_source_key(self, label: str) -> str:
        return {"YouTube": "youtube", "Bilibili": "bilibili", "完整 URL": "url"}[label]

    def _on_save(self) -> None:
        msg = self._ctx.config_manager.save_music_cover_config(
            self.mc_work_dir.text(),
            self.mc_yt_dlp.text(),
            self.mc_ffmpeg.text(),
            self.mc_uvr_tpl.toPlainText(),
            self.mc_rvc_tpl.toPlainText(),
            self.mc_rvc_model.text(),
            self.mc_rvc_index.text(),
            self.mc_rvc_device.text(),
            self.mc_rvc_ver.currentText(),
            self.mc_rvc_f0.currentText(),
            self.mc_rvc_pitch.value(),
            self.mc_rvc_ir.value(),
            self.mc_rvc_fr.value(),
            self.mc_rvc_rsr.value(),
            self.mc_rvc_rmr.value(),
            self.mc_rvc_pr.value(),
        )
        self.mc_save_out.setPlainText(msg)

    def _on_search(self) -> None:
        try:
            log = search_preview(
                self._ctx.config_manager.config.system_config,
                self._mc_source_key(self.mc_src.currentText()),
                self.mc_query.toPlainText().strip(),
            )
            self.mc_log.setPlainText(log)
        except Exception:
            self.mc_log.setPlainText(traceback.format_exc())

    def _on_run(self) -> None:
        try:
            r = run_pipeline(
                self._ctx.config_manager.config.system_config,
                source=self._mc_source_key(self.mc_src.currentText()),
                query=self.mc_query.toPlainText().strip(),
                pick_index=int(self.mc_pick.value()),
                skip_rvc=bool(self.mc_skip_rvc.isChecked()),
            )
            msg = format_pipeline_log(r)
            audio = str(r.final_mix) if r.final_mix.exists() else ""
            self.mc_log.setPlainText(msg)
            self.mc_audio_path.setText(audio)
        except Exception:
            self.mc_log.setPlainText(traceback.format_exc())
            self.mc_audio_path.clear()
