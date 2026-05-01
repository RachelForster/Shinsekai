"""一键下载 TTS 整合包：在弹窗中展示平台/GPU/推荐，并允许下拉修改包后再下载。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from i18n import tr as tr_i18n
from ui.settings_ui.feedback import feedback_result, message_fail
from ui.settings_ui.tts_bundle_worker import TtsBundleDownloadWorker
from ui.settings_ui.tts_env_probe import (
    bundle_choice_for_kind,
    format_gpu_lines,
    format_platform,
    get_default_project_root,
    get_gpu_list,
    recommend_tts_bundle,
)

_BUNDLE_ORDER = ("genie", "gptso", "gptso50")


class TtsBundleDownloadDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        *,
        gpt_sovits_api_path: QLineEdit,
        tts_provider: QComboBox,
    ) -> None:
        super().__init__(parent)
        self._path_edit = gpt_sovits_api_path
        self._tts_provider = tts_provider
        self._worker: TtsBundleDownloadWorker | None = None
        self._downloading = False
        self._pending_accept = False
        self.setModal(True)
        self.setMinimumWidth(460)

        root = QVBoxLayout(self)
        self._platform_lbl = QLabel()
        self._platform_lbl.setWordWrap(True)
        self._platform_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._gpu_lbl = QLabel()
        self._gpu_lbl.setWordWrap(True)
        self._gpu_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._rec_hint = QLabel()
        self._rec_hint.setWordWrap(True)
        self._rec_hint.setObjectName("apiSectionHint")
        self._f_pick = QLabel()
        self._combo = QComboBox()
        for k in _BUNDLE_ORDER:
            self._combo.addItem("", k)  # text set in _relang
        self._combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._combo.setMinimumWidth(360)

        self._st = QLabel()
        self._st.setVisible(False)
        self._pb = QProgressBar()
        self._pb.setRange(0, 100)
        self._pb.setVisible(False)

        root.addWidget(self._platform_lbl)
        root.addWidget(self._gpu_lbl)
        root.addWidget(self._rec_hint)
        fp = QFormLayout()
        fp.setContentsMargins(0, 8, 0, 0)
        fp.addRow(self._f_pick, self._combo)
        root.addLayout(fp)
        root.addWidget(self._st)
        root.addWidget(self._pb)

        btn_row = QHBoxLayout()
        self._btn_start = QPushButton()
        self._btn_start.clicked.connect(self._on_start)
        self._btn_cancel = QPushButton()
        self._btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addStretch(1)
        btn_row.addWidget(self._btn_start)
        btn_row.addWidget(self._btn_cancel)
        root.addLayout(btn_row)

        self._relang()
        self._refresh_gpu_and_combo()

    def _relang(self) -> None:
        self.setWindowTitle(tr_i18n("api.tts.env.dlg_title"))
        self._f_pick.setText(tr_i18n("api.tts.env.dlg_pick"))
        self._btn_start.setText(tr_i18n("api.tts.env.dlg_start"))
        self._btn_cancel.setText(tr_i18n("api.tts.env.dlg_cancel"))
        for i, k in enumerate(_BUNDLE_ORDER):
            self._combo.setItemText(i, tr_i18n(f"api.tts.env.rec_{k}"))

    def _refresh_gpu_and_combo(self) -> None:
        gpus = get_gpu_list()
        self._platform_lbl.setText(
            f"{tr_i18n('api.tts.env.dlg_platform')}\n{format_platform()}"
        )
        self._gpu_lbl.setText(
            f"{tr_i18n('api.tts.env.dlg_gpu')}\n"
            f"{format_gpu_lines(gpus, none_msg=tr_i18n('api.tts.env.no_gpu'))}"
        )
        ch = recommend_tts_bundle(gpus)
        self._rec_hint.setText(
            f"{tr_i18n('api.tts.env.dlg_recommend')}\n{tr_i18n(f'api.tts.env.rec_{ch.kind}')}"
        )
        idx = self._combo.findData(ch.kind)
        if idx < 0:
            idx = 0
        self._combo.setCurrentIndex(idx)

    def showEvent(self, e: QShowEvent | None) -> None:
        super().showEvent(e)
        if e is not None and not self._downloading:
            self._relang()
            self._refresh_gpu_and_combo()

    def apply_i18n(self) -> None:
        if self._downloading:
            return
        self._relang()
        self._refresh_gpu_and_combo()

    def _set_busy(self, busy: bool) -> None:
        self._downloading = busy
        self._btn_start.setEnabled(not busy)
        self._combo.setEnabled(not busy)
        self._btn_cancel.setEnabled(not busy)
        if not busy:
            self._st.setVisible(False)
            self._pb.setVisible(False)
            self._pb.setValue(0)

    def _on_cancel(self) -> None:
        if self._downloading and self._worker and self._worker.isRunning():
            return
        self.reject()

    def closeEvent(self, e: QCloseEvent) -> None:  # pragma: no cover
        if self._downloading and self._worker and self._worker.isRunning():
            e.ignore()
            return
        super().closeEvent(e)

    def _on_start(self) -> None:
        if self._downloading or (self._worker and self._worker.isRunning()):
            return
        kind = self._combo.currentData()
        if not isinstance(kind, str):
            kind = "genie"
        ch = bundle_choice_for_kind(kind)
        self._st.setVisible(True)
        self._pb.setVisible(True)
        self._pb.setValue(0)
        self._on_worker_status("download")
        self._set_busy(True)

        self._pending_accept = False
        w = TtsBundleDownloadWorker(
            ch.download_url,
            ch.bundle_dir_key,
            get_default_project_root(),
            self,
        )
        self._worker = w
        w.progress.connect(self._pb.setValue)
        w.status.connect(self._on_worker_status)
        w.finished_ok.connect(self._on_worker_ok)
        w.failed.connect(self._on_worker_fail)
        w.finished.connect(self._on_worker_thread_done)
        w.start()

    def _on_worker_status(self, s: str) -> None:
        if s == "download":
            self._st.setText(tr_i18n("api.tts.env.st_download"))
        elif s == "extract":
            self._st.setText(tr_i18n("api.tts.env.st_extract"))
        self._st.setVisible(True)

    def _on_worker_ok(self, abs_path: str) -> None:
        self._path_edit.setText(abs_path)
        kind = self._combo.currentData()
        if not isinstance(kind, str):
            kind = "genie"
        if kind == "genie":
            idx = self._tts_provider.findData("genie-tts")
        else:
            idx = self._tts_provider.findData("gpt-sovits")
        if idx >= 0:
            self._tts_provider.setCurrentIndex(idx)
        feedback_result(
            self,
            tr_i18n("api.msg.config"),
            tr_i18n("api.tts.env.done").format(path=abs_path),
        )
        self._pending_accept = True

    def _on_worker_fail(self, msg: str) -> None:
        if msg == "py7zr":
            message_fail(
                self, tr_i18n("api.msg.config"), tr_i18n("api.tts.env.err_py7")
            )
        elif msg == "7za":
            message_fail(
                self, tr_i18n("api.msg.config"), tr_i18n("api.tts.env.err_7z")
            )
        else:
            message_fail(self, tr_i18n("api.msg.config"), msg)
        self._pending_accept = False
        self._set_busy(False)

    def _on_worker_thread_done(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._pending_accept:
            self._pending_accept = False
            self._downloading = False
            self.accept()
        else:
            self._set_busy(False)
