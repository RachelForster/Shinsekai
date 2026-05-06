"""插件设置页：管理插件（卡片网格）与从远程索引「发现插件」。"""


from __future__ import annotations

import json
import shutil
from collections import defaultdict
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, QUrl, Signal, Slot, QEventLoop
from PySide6.QtGui import QCloseEvent, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QAbstractItemView,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.plugins.plugin_host import (
    append_plugin_manifest_entry_if_missing,
    collect_settings_contributions,
    collect_tools_tab_contributions,
    get_plugin_manager,
    infer_plugin_package_directory,
    normalize_manifest_entry,
    read_plugin_manifest_items,
    remove_plugin_manifest_entry,
    set_plugin_manifest_enabled,
)
from core.plugins.registry_catalog import (
    DEFAULT_REGISTRY_JSON_URL,
    RegistryPluginRecord,
    fetch_registry_error_message,
    fetch_registry_plugins,
)
from core.plugins.plugin_requirements_install import install_plugin_requirements_txt
from core.plugins.registry_download import (
    format_download_error,
    load_downloaded_repos,
    mark_repo_downloaded,
    normalize_repo_slug,
    unmark_repo_downloaded,
    unmark_repo_for_manifest_entry,
)
from core.plugins.github_bundle_update import (
    default_app_github_repo_slug,
    fetch_recent_tag_names,
    install_github_plugin_under_plugins,
    overwrite_merge_app_tree,
    read_local_version,
    resolve_project_root,
)

from i18n import tr as tr_i18n
from sdk.plugin_host_context import PluginSettingsUIContext
from sdk.types import SettingsUIContribution, ToolsTabContribution

from ui.settings_ui.context import SettingsUIContext
from ui.settings_ui.feedback import message_fail, toast_info, toast_success
from ui.settings_ui.tabs.plugin_mcp_tab import PluginMcpTab
from ui.settings_ui.widgets.segmented_tab_nav import SegmentedTabNav


def _parse_pip_install_result_json(raw: str) -> tuple[str, str]:
    """Returns ``(code, detail_tail)`` from worker JSON; safe defaults if malformed."""
    if not raw.strip():
        return ("pip_skip_no_requirements", "")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ("pip_skip_no_requirements", "")
    if not isinstance(data, dict):
        return ("pip_skip_no_requirements", "")
    code = str(data.get("pip") or "").strip()
    tail = str(data.get("detail") or "").strip()
    if not code:
        return ("pip_skip_no_requirements", tail)
    return (code, tail)


def _format_byte_size(n: int) -> str:
    if n <= 0:
        return "0 B"
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KiB"
    return f"{n / (1024 * 1024):.2f} MiB"


class _DiscoverInstallProgressDialog(QDialog):
    """发现插件：下载 ZIP + pip 时的进度与日志。"""

    def __init__(
        self,
        parent: QWidget | None,
        repo_slug: str,
        *,
        window_title_key: str = "plugins.discover_install_progress_title",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr_i18n(window_title_key))
        self.setModal(False)
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        repo_txt = tr_i18n("plugins.discover_install_progress_repo", repo=repo_slug)
        self._repo_lbl = QLabel(repo_txt)
        self._repo_lbl.setWordWrap(True)
        lay.addWidget(self._repo_lbl)
        self._phase_lbl = QLabel(tr_i18n("plugins.discover_phase_download"))
        self._phase_lbl.setWordWrap(True)
        lay.addWidget(self._phase_lbl)
        self._bytes_lbl = QLabel("")
        self._bytes_lbl.setStyleSheet("color: palette(mid);")
        lay.addWidget(self._bytes_lbl)
        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        lay.addWidget(self._bar)
        log_hint = QLabel(tr_i18n("plugins.discover_install_log_hint"))
        log_hint.setWordWrap(True)
        log_hint.setStyleSheet("color: palette(mid);")
        lay.addWidget(log_hint)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(16000)
        mono = self._log.font()
        mono.setFamily("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._log.setFont(mono)
        lay.addWidget(self._log, stretch=1)
        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bbox.rejected.connect(self.accept)
        self._close_btn = bbox.button(QDialogButtonBox.StandardButton.Close)
        assert self._close_btn is not None
        self._close_btn.setEnabled(False)
        lay.addWidget(bbox)
        self._allow_close = False

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._allow_close:
            event.ignore()
            return
        super().closeEvent(event)

    @Slot(str)
    def set_phase_label(self, text: str) -> None:
        self._phase_lbl.setText(text)

    @Slot(int, int)
    def on_download_progress(self, current: int, total: int) -> None:
        if total and total > 0:
            self._bar.setRange(0, total)
            self._bar.setValue(min(current, total))
            self._bytes_lbl.setText(
                tr_i18n(
                    "plugins.discover_install_progress_bytes",
                    current=_format_byte_size(current),
                    total=_format_byte_size(total),
                )
            )
        else:
            self._bar.setRange(0, 0)
            self._bytes_lbl.setText(
                tr_i18n(
                    "plugins.discover_install_progress_bytes_unknown",
                    current=_format_byte_size(current),
                )
            )

    @Slot(str)
    def append_pip_line(self, line: str) -> None:
        self._log.appendPlainText(line)
        self._log.verticalScrollBar().setValue(self._log.verticalScrollBar().maximum())

    @Slot()
    def on_pip_phase_started(self) -> None:
        self._log.appendPlainText(tr_i18n("plugins.discover_install_pip_separator"))

    def mark_finished(self, ok: bool, download_err: str, pip_json: str) -> None:
        self._allow_close = True
        self._close_btn.setEnabled(True)
        if not ok:
            self._phase_lbl.setText(tr_i18n("plugins.discover_install_done_fail"))
            self._bar.setRange(0, 100)
            self._bar.setValue(0)
            if download_err.strip():
                self._log.appendPlainText(
                    tr_i18n("plugins.discover_install_download_error_heading")
                    + "\n"
                    + download_err.strip()
                )
            return
        self._phase_lbl.setText(tr_i18n("plugins.discover_install_done_ok"))
        self._bar.setRange(0, 100)
        self._bar.setValue(100)
        self._bytes_lbl.clear()
        pip_code, detail_tail = _parse_pip_install_result_json(pip_json)
        if pip_code == "app_update_skip_pip":
            self._log.appendPlainText(tr_i18n("plugins.app_update_no_pip_log"))
        elif pip_code == "pip_skip_no_requirements":
            self._log.appendPlainText(tr_i18n("plugins.plugin_pip_skip"))
        elif pip_code in ("pip_timeout", "pip_exception") and detail_tail.strip():
            self._log.appendPlainText(
                "\n"
                + tr_i18n("plugins.plugin_pip_detail_heading")
                + "\n"
                + detail_tail.strip()
            )


class _DiscoverFetchSignals(QObject):
    finished = Signal(list, str)


class _DiscoverFetchTask(QRunnable):
    """Background GET + JSON parse for plugin registry."""

    def __init__(self, url: str, sig: _DiscoverFetchSignals) -> None:
        super().__init__()
        self._url = url
        self._sig = sig
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            rows = fetch_registry_plugins(self._url)
        except Exception as exc:
            self._sig.finished.emit([], fetch_registry_error_message(exc))
        else:
            self._sig.finished.emit(rows, "")


class _DownloadSignals(QObject):
    """repo_norm, ok, download_err, pip_result_json"""

    finished = Signal(str, bool, str, str)
    download_progress = Signal(int, int)
    status_message = Signal(str)
    pip_log_line = Signal(str)
    pip_phase_started = Signal()


class _TagListFetchSignals(QObject):
    done = Signal(list)
    fail = Signal(str)


class _TagListFetchTask(QRunnable):
    def __init__(self, slug: str, sig: _TagListFetchSignals) -> None:
        super().__init__()
        self._slug = slug
        self._sig = sig
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            self._sig.done.emit(fetch_recent_tag_names(self._slug))
        except Exception as exc:
            self._sig.fail.emit(format_download_error(exc))


def _blocking_fetch_tag_names(slug: str) -> list[str]:
    sig = _TagListFetchSignals()
    loop = QEventLoop()
    out: list[str] = []

    def ok(rows: object) -> None:
        nonlocal out
        if isinstance(rows, list):
            out = [str(x).strip() for x in rows if str(x).strip()]
        loop.quit()

    def _bad(_msg: str) -> None:
        loop.quit()

    sig.done.connect(ok)
    sig.fail.connect(_bad)
    QThreadPool.globalInstance().start(_TagListFetchTask(slug, sig))
    loop.exec()
    return out


class _PickRepoRefDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        *,
        repo_slug: str,
        tag_names: list[str],
        title_i18n: str = "plugins.repo_ref_pick_title",
        repo_hint_i18n: str = "plugins.repo_ref_pick_repo",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr_i18n(title_i18n))
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr_i18n(repo_hint_i18n, repo=repo_slug)))
        self._combo = QComboBox()
        self._combo.addItem(tr_i18n("plugins.repo_ref_latest"), "latest")
        self._combo.addItem(tr_i18n("plugins.repo_ref_head"), "head")
        for t in tag_names:
            self._combo.addItem(t, f"tag:{t}")
        self._combo.setCurrentIndex(0)
        lay.addWidget(self._combo)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def ref_choice(self) -> tuple[str, str]:
        d = str(self._combo.currentData() or "latest")
        if d == "latest":
            return "latest", ""
        if d == "head":
            return "head", ""
        if d.startswith("tag:"):
            return "tag", d[4:]
        return "latest", ""


class _DownloadRepoTask(QRunnable):
    def __init__(
        self,
        repo: str,
        catalog_display_name: str,
        sig: _DownloadSignals,
        *,
        ref_kind: str,
        tag_name: str,
        overwrite: bool,
    ) -> None:
        super().__init__()
        self._repo = repo
        self._catalog_display_name = catalog_display_name.strip()
        self._sig = sig
        self._ref_kind = ref_kind if ref_kind in ("latest", "head", "tag") else "latest"
        self._tag_name = tag_name.strip()
        self._overwrite = overwrite
        self.setAutoDelete(True)

    def run(self) -> None:
        norm = normalize_repo_slug(self._repo)
        self._sig.status_message.emit(tr_i18n("plugins.discover_phase_download"))
        plugins_dir = resolve_project_root() / "plugins"
        try:
            dest = install_github_plugin_under_plugins(
                self._repo,
                catalog_display_name=self._catalog_display_name,
                ref_kind=self._ref_kind,  # type: ignore[arg-type]
                tag_name=self._tag_name,
                overwrite=self._overwrite,
                plugins_parent=plugins_dir,
                progress=lambda cur, tot: self._sig.download_progress.emit(
                    cur, tot if tot is not None else 0
                ),
                on_phase=lambda phase: self._emit_extract_phase(phase),
            )
        except Exception as exc:
            self._sig.finished.emit(norm, False, format_download_error(exc), "")
            return
        self._sig.status_message.emit(tr_i18n("plugins.discover_phase_pip"))
        self._sig.download_progress.emit(0, 0)
        self._sig.pip_phase_started.emit()

        def _pip_line(line: str) -> None:
            self._sig.pip_log_line.emit(line)

        pip_code, pip_detail = install_plugin_requirements_txt(
            dest, on_output_line=_pip_line
        )
        pip_payload = json.dumps(
            {"pip": pip_code, "detail": pip_detail}, ensure_ascii=False
        )
        self._sig.finished.emit(norm, True, "", pip_payload)

    def _emit_extract_phase(self, phase: str) -> None:
        if phase == "extract":
            self._sig.status_message.emit(tr_i18n("plugins.discover_phase_extract"))


class _AppSelfUpdateTask(QRunnable):
    """主程序源码树 GitHub ZIP 合并覆盖 + pip install 项目依赖。"""

    def __init__(
        self,
        slug: str,
        ref_kind: str,
        tag_name: str,
        sig: _DownloadSignals,
    ) -> None:
        super().__init__()
        self._slug = slug.strip()
        self._ref_kind = ref_kind if ref_kind in ("latest", "head", "tag") else "latest"
        self._tag_name = tag_name.strip()
        self._sig = sig
        self.setAutoDelete(True)

    def run(self) -> None:
        self._sig.status_message.emit(tr_i18n("plugins.discover_phase_download"))
        try:
            overwrite_merge_app_tree(
                self._slug,
                self._ref_kind,  # type: ignore[arg-type]
                self._tag_name,
                progress=lambda cur, tot: self._sig.download_progress.emit(
                    cur, tot if tot is not None else 0
                ),
                on_phase=lambda phase: self._emit_extract_phase(phase),
            )
        except Exception as exc:
            self._sig.finished.emit("", False, format_download_error(exc), "")
            return

        self._sig.status_message.emit(tr_i18n("plugins.discover_phase_pip"))
        self._sig.pip_phase_started.emit()

        def _pip_line(line: str) -> None:
            self._sig.pip_log_line.emit(line)

        from core.plugins.plugin_requirements_install import install_plugin_requirements_txt

        project_root = resolve_project_root()
        pip_code, pip_detail = install_plugin_requirements_txt(
            project_root, on_output_line=_pip_line
        )
        pip_payload = json.dumps(
            {"pip": pip_code, "detail": pip_detail}, ensure_ascii=False
        )
        self._sig.finished.emit("", True, "", pip_payload)

    def _emit_extract_phase(self, phase: str) -> None:
        if phase == "extract":
            self._sig.status_message.emit(tr_i18n("plugins.app_update_phase_merge"))

def _resolve_plugin_for_manifest_entry(entry: str, mgr: object | None):
    if mgr is None:
        return None
    e = entry.strip()
    for p in mgr.plugins:
        cls = p.__class__
        full = f"{cls.__module__}:{cls.__qualname__}"
        if full == e:
            return p
        if ":" not in e and cls.__module__ == e:
            return p
    return None


def _display_title_for_offline_entry(entry: str) -> str:
    e = entry.strip()
    if ":" in e:
        return e.rpartition(":")[2]
    return e.rpartition(".")[2] if "." in e else e


class PluginSettingsTab(QWidget):
    """顶部 Tab：管理插件 / 发现插件；管理页为两列卡片，点击进入该插件的设置 Widget。"""

    def __init__(self, ctx: SettingsUIContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._plg_ctx = PluginSettingsUIContext.from_settings_ui_context(ctx)
        self._contrib_widgets: dict[str, QWidget] = {}
        self._discover_cache: list[RegistryPluginRecord] | None = None
        self._discover_busy = False
        self._discover_fetched_once = False
        self._download_busy: set[str] = set()
        self._discover_download_buttons: dict[str, QPushButton] = {}
        self._app_update_busy = False
        self._outer = QStackedWidget(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._outer)

        list_page = QWidget()
        lp_lay = QVBoxLayout(list_page)
        lp_lay.setContentsMargins(0, 0, 0, 0)

        self._manage_discover_tabs = SegmentedTabNav()
        self._manage_discover_tabs.currentChanged.connect(self._on_plugin_subtab_changed)

        manage_host = QWidget()
        mh_lay = QVBoxLayout(manage_host)
        mh_lay.setContentsMargins(4, 8, 4, 8)
        self._manage_scroll = QScrollArea()
        self._manage_scroll.setWidgetResizable(True)
        self._manage_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setSpacing(12)
        self._manage_scroll.setWidget(self._grid_host)
        mh_lay.addWidget(self._manage_scroll)
        self._manage_discover_tabs.add_tab(manage_host, tr_i18n("plugins.tab_manage"))

        discover_host = QWidget()
        dv = QVBoxLayout(discover_host)
        dv.setContentsMargins(4, 8, 4, 8)
        toolbar = QHBoxLayout()
        self._discover_refresh_btn = QPushButton(tr_i18n("plugins.discover_refresh"))
        self._discover_refresh_btn.clicked.connect(self._refresh_discover_catalog)
        self._app_update_btn = QPushButton(tr_i18n("plugins.app_self_update_btn"))
        self._app_update_btn.clicked.connect(self._on_app_self_update)
        self._discover_version_lbl = QLabel()
        toolbar.addWidget(self._discover_refresh_btn)
        toolbar.addWidget(self._app_update_btn)
        toolbar.addStretch(1)
        toolbar.addWidget(self._discover_version_lbl)
        dv.addLayout(toolbar)
        self._discover_registry_hint = QLabel()
        self._discover_registry_hint.setOpenExternalLinks(True)
        self._discover_registry_hint.setWordWrap(True)
        dv.addWidget(self._discover_registry_hint)
        self._discover_status = QLabel()
        self._discover_status.setWordWrap(True)
        self._discover_status.setVisible(False)
        dv.addWidget(self._discover_status)

        self._discover_table_hint = QLabel()
        self._discover_table_hint.setWordWrap(True)
        self._discover_table_hint.setVisible(False)
        dv.addWidget(self._discover_table_hint)

        self._discover_table = QTableWidget(0, 4)
        self._discover_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._discover_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._discover_table.setAlternatingRowColors(True)
        self._discover_table.setShowGrid(True)
        self._discover_table.setWordWrap(True)
        self._discover_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._discover_table.verticalHeader().setVisible(False)
        vh = self._discover_table.verticalHeader()
        vh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        vh.setMinimumSectionSize(28)
        self._discover_table.setStyleSheet(
            "QTableWidget { gridline-color: palette(mid); }\n"
            "QHeaderView::section { padding: 4px 8px; font-weight: bold; }\n"
            "QTableWidget::item { padding: 4px 8px; }\n"
            "QTableWidget::item:selected,\n"
            "QTableWidget::item:selected:active,\n"
            "QTableWidget::item:selected:!active,\n"
            "QTableWidget::item:selected:focus {\n"
            "  background-color: palette(base);\n"
            "  color: palette(text);\n"
            "}\n"
            "QTableWidget::item:alternate:selected,\n"
            "QTableWidget::item:alternate:selected:active,\n"
            "QTableWidget::item:alternate:selected:!active {\n"
            "  background-color: palette(alternate-base);\n"
            "  color: palette(text);\n"
            "}\n"
            "QTableWidget:focus { outline: none; }\n"
            "QTableCornerButton::section { background: palette(button); }\n"
        )
        hh = self._discover_table.horizontalHeader()
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        dv.addWidget(self._discover_table, stretch=1)

        self._discover_fetch_signals = _DiscoverFetchSignals(self)
        self._discover_fetch_signals.finished.connect(self._on_discover_catalog_finished)

        self._manage_discover_tabs.add_tab(discover_host, tr_i18n("plugins.tab_discover"))

        self._plugin_mcp_tab = PluginMcpTab(self._ctx, self)
        self._manage_discover_tabs.add_tab(self._plugin_mcp_tab, tr_i18n("plugins.tab_mcp"))

        lp_lay.addWidget(self._manage_discover_tabs, stretch=1)
        self._outer.addWidget(list_page)

        detail = QWidget()
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(4, 8, 4, 8)
        head = QHBoxLayout()
        self._back_btn = QPushButton(tr_i18n("plugins.back"))
        self._back_btn.clicked.connect(lambda: self._outer.setCurrentIndex(0))
        head.addWidget(self._back_btn)
        self._detail_title = QLabel()
        self._detail_title.setWordWrap(True)
        head.addWidget(self._detail_title, stretch=1)
        dl.addLayout(head)
        self._detail_stack_host = QWidget()
        self._detail_stack_layout = QVBoxLayout(self._detail_stack_host)
        self._detail_stack_layout.setContentsMargins(0, 8, 0, 0)
        dl.addWidget(self._detail_stack_host, stretch=1)
        self._outer.addWidget(detail)

        self._outer.setCurrentIndex(0)
        self._discover_registry_hint.setText(tr_i18n("plugins.discover_registry_hint_html"))
        self._discover_apply_table_headers()
        self._repaint_discover_catalog_grid()
        self._refresh_cards()
        self._refresh_discover_version_badge()

    def apply_i18n(self) -> None:
        self._manage_discover_tabs.set_tab_text(0, tr_i18n("plugins.tab_manage"))
        self._manage_discover_tabs.set_tab_text(1, tr_i18n("plugins.tab_discover"))
        self._manage_discover_tabs.set_tab_text(2, tr_i18n("plugins.tab_mcp"))
        self._plugin_mcp_tab.apply_i18n()
        self._back_btn.setText(tr_i18n("plugins.back"))
        self._discover_refresh_btn.setText(tr_i18n("plugins.discover_refresh"))
        self._app_update_btn.setText(tr_i18n("plugins.app_self_update_btn"))
        self._refresh_discover_version_badge()
        self._discover_registry_hint.setText(tr_i18n("plugins.discover_registry_hint_html"))
        self._discover_apply_table_headers()
        self._repaint_discover_catalog_grid()
        self._refresh_cards()

    def _on_plugin_subtab_changed(self, index: int) -> None:
        if index != 1 or self._discover_fetched_once or self._discover_busy:
            return
        self._discover_fetched_once = True
        self._refresh_discover_catalog()

    def _refresh_discover_catalog(self) -> None:
        if self._discover_busy:
            return
        self._discover_busy = True
        self._discover_refresh_btn.setEnabled(False)
        self._discover_status.setText(tr_i18n("plugins.discover_loading"))
        self._discover_status.setVisible(True)
        QThreadPool.globalInstance().start(
            _DiscoverFetchTask(DEFAULT_REGISTRY_JSON_URL, self._discover_fetch_signals)
        )

    @Slot(list, str)
    def _on_discover_catalog_finished(self, rows: list, err: str) -> None:
        self._discover_busy = False
        self._discover_refresh_btn.setEnabled(True)
        self._discover_status.clear()
        self._discover_status.setVisible(False)
        if err:
            self._discover_status.setText(tr_i18n("plugins.discover_error", detail=err))
            self._discover_status.setVisible(True)
            message_fail(self, tr_i18n("plugins.discover_error_title"), err)
            return
        cast_rows = [r for r in rows if isinstance(r, RegistryPluginRecord)]
        self._discover_cache = cast_rows
        self._repaint_discover_catalog_grid()

    def _discover_apply_table_headers(self) -> None:
        self._discover_table.setHorizontalHeaderLabels(
            [
                tr_i18n("plugins.discover_col_name"),
                tr_i18n("plugins.discover_col_author"),
                tr_i18n("plugins.discover_col_desc"),
                tr_i18n("plugins.discover_col_actions"),
            ]
        )

    def _refresh_discover_version_badge(self) -> None:
        v = read_local_version(resolve_project_root()).strip()
        if not v:
            self._discover_version_lbl.setText(tr_i18n("plugins.app_update_version_unknown"))
        else:
            self._discover_version_lbl.setText(
                tr_i18n("plugins.app_update_version_fmt", version=v)
            )

    def _on_app_self_update(self) -> None:
        if self._app_update_busy:
            return
        slug = default_app_github_repo_slug().strip()
        if not slug or slug.count("/") < 1:
            message_fail(
                self,
                tr_i18n("plugins.app_update_fail_title"),
                tr_i18n("plugins.app_update_bad_repo_body"),
            )
            return
        warn = QMessageBox.warning(
            self,
            tr_i18n("plugins.app_update_warn_title"),
            tr_i18n("plugins.app_update_warn_body"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if warn != QMessageBox.StandardButton.Yes:
            return
        tags = _blocking_fetch_tag_names(normalize_repo_slug(slug))
        dlg_pick = _PickRepoRefDialog(
            self,
            repo_slug=slug,
            tag_names=tags,
            title_i18n="plugins.repo_ref_pick_title_app",
            repo_hint_i18n="plugins.repo_ref_pick_repo",
        )
        if dlg_pick.exec() != QDialog.DialogCode.Accepted:
            return
        rk, tg = dlg_pick.ref_choice()
        if rk == "tag" and not tg.strip():
            message_fail(
                self,
                tr_i18n("plugins.repo_ref_tag_invalid_title"),
                tr_i18n("plugins.repo_ref_tag_invalid_body"),
            )
            return
        self._app_update_busy = True
        dlg = _DiscoverInstallProgressDialog(
            self,
            slug,
            window_title_key="plugins.app_update_progress_title",
        )
        sigs = _DownloadSignals(dlg)
        sigs.download_progress.connect(dlg.on_download_progress)
        sigs.status_message.connect(dlg.set_phase_label)
        sigs.pip_log_line.connect(dlg.append_pip_line)
        sigs.pip_phase_started.connect(dlg.on_pip_phase_started)
        sigs.finished.connect(
            lambda rn, ok, de, pj, d=dlg: self._on_app_self_update_finished(
                d, ok, de, pj
            )
        )
        dlg.show()
        QThreadPool.globalInstance().start(_AppSelfUpdateTask(slug, rk, tg, sigs))

    def _on_app_self_update_finished(
        self,
        dlg: _DiscoverInstallProgressDialog,
        ok: bool,
        download_err: str,
        pip_json: str,
    ) -> None:
        self._app_update_busy = False
        dlg.mark_finished(ok, download_err, pip_json)
        if not ok:
            message_fail(
                self,
                tr_i18n("plugins.app_update_fail_title"),
                download_err or tr_i18n("plugins.discover_download_fail_body"),
            )
            return
        self._refresh_discover_version_badge()
        toast_success(
            self,
            tr_i18n("plugins.app_update_ok_title"),
            tr_i18n("plugins.app_update_ok_body"),
        )

    def _repaint_discover_catalog_grid(self) -> None:
        self._discover_table.clearContents()
        self._discover_table.setRowCount(0)
        self._discover_download_buttons.clear()

        if self._discover_cache is None:
            self._discover_table_hint.setText(tr_i18n("plugins.discover_intro"))
            self._discover_table_hint.setVisible(True)
            return
        if not self._discover_cache:
            self._discover_table_hint.setText(tr_i18n("plugins.discover_empty"))
            self._discover_table_hint.setVisible(True)
            return

        self._discover_table_hint.setVisible(False)
        downloaded = load_downloaded_repos()
        items = self._discover_cache
        self._discover_table.setRowCount(len(items))
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

        for row, rec in enumerate(items):
            desc_full = (rec.description or tr_i18n("plugins.discover_no_description")).strip()

            it_name = QTableWidgetItem(rec.name)
            it_name.setToolTip(rec.name)
            it_name.setFlags(flags)
            it_name.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self._discover_table.setItem(row, 0, it_name)

            auth = rec.author or "—"
            it_auth = QTableWidgetItem(auth)
            it_auth.setToolTip(auth)
            it_auth.setFlags(flags)
            it_auth.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self._discover_table.setItem(row, 1, it_auth)

            it_desc = QTableWidgetItem(desc_full)
            it_desc.setToolTip(desc_full)
            it_desc.setFlags(flags)
            it_desc.setTextAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            self._discover_table.setItem(row, 2, it_desc)

            self._discover_table.setCellWidget(
                row,
                3,
                self._make_discover_actions_row(rec, downloaded),
            )

        self._discover_table.resizeRowsToContents()
        self._discover_table.resizeColumnToContents(3)

    def _make_discover_actions_row(
        self,
        rec: RegistryPluginRecord,
        downloaded: set[str],
    ) -> QWidget:
        host = QWidget()
        host.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Maximum)
        outer = QVBoxLayout(host)
        outer.setContentsMargins(4, 2, 4, 2)
        outer.setSpacing(0)
        outer.addStretch(1)

        row = QWidget()
        row.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Maximum)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        repo_norm = normalize_repo_slug(rec.repo) if rec.repo.strip() else ""
        dl_btn = QPushButton()

        if not rec.repo.strip():
            dl_btn.setText(tr_i18n("plugins.discover_download"))
            dl_btn.setEnabled(False)
            dl_btn.setToolTip(tr_i18n("plugins.discover_no_repo_tooltip"))
        elif repo_norm in self._download_busy:
            dl_btn.setText(tr_i18n("plugins.discover_downloading"))
            dl_btn.setEnabled(False)
        elif repo_norm in downloaded:
            dl_btn.setText(tr_i18n("plugins.discover_update"))
            dl_btn.setToolTip(tr_i18n("plugins.discover_update_tooltip"))
            dl_btn.clicked.connect(
                lambda checked=False, r=rec, b=dl_btn: self._start_repo_download(
                    r, b, overwrite=True
                )
            )
            self._discover_download_buttons[repo_norm] = dl_btn
        else:
            dl_btn.setText(tr_i18n("plugins.discover_download"))
            dl_btn.setToolTip(tr_i18n("plugins.discover_download_tooltip"))
            dl_btn.clicked.connect(
                lambda checked=False, r=rec, b=dl_btn: self._start_repo_download(
                    r, b, overwrite=False
                )
            )
            self._discover_download_buttons[repo_norm] = dl_btn

        lay.addWidget(dl_btn)

        gh_btn = QPushButton(tr_i18n("plugins.discover_open_github_short"))
        if rec.repo.strip():
            gh_btn.clicked.connect(
                lambda *, u=rec.github_url(): QDesktopServices.openUrl(QUrl(u))
            )
        else:
            gh_btn.setEnabled(False)
        lay.addWidget(gh_btn)

        for b in (dl_btn, gh_btn):
            b.setMinimumWidth(max(b.sizeHint().width() + 8, 56))

        outer.addWidget(row)
        outer.addStretch(1)
        return host

    def _start_repo_download(
        self, rec: RegistryPluginRecord, btn: QPushButton, *, overwrite: bool
    ) -> None:
        repo = rec.repo.strip()
        norm = normalize_repo_slug(repo)
        if norm in self._download_busy or not norm:
            return
        tags = _blocking_fetch_tag_names(norm)
        dlg_pick = _PickRepoRefDialog(self, repo_slug=repo, tag_names=tags)
        if dlg_pick.exec() != QDialog.DialogCode.Accepted:
            return
        rk, tg = dlg_pick.ref_choice()
        if rk == "tag" and not tg.strip():
            message_fail(
                self,
                tr_i18n("plugins.repo_ref_tag_invalid_title"),
                tr_i18n("plugins.repo_ref_tag_invalid_body"),
            )
            return
        self._download_busy.add(norm)
        btn.setEnabled(False)
        btn.setText(tr_i18n("plugins.discover_downloading"))
        dlg = _DiscoverInstallProgressDialog(self, repo)
        sigs = _DownloadSignals(dlg)
        sigs.download_progress.connect(dlg.on_download_progress)
        sigs.status_message.connect(dlg.set_phase_label)
        sigs.pip_log_line.connect(dlg.append_pip_line)
        sigs.pip_phase_started.connect(dlg.on_pip_phase_started)
        sigs.finished.connect(
            lambda rn, ok, de, pj, d=dlg: self._on_download_finished_with_dialog(
                d, rn, ok, de, pj
            )
        )
        dlg.show()
        catalog_name = (rec.name or "").strip()
        QThreadPool.globalInstance().start(
            _DownloadRepoTask(
                repo,
                catalog_name,
                sigs,
                ref_kind=rk,
                tag_name=tg,
                overwrite=overwrite,
            )
        )

    def _on_download_finished_with_dialog(
        self,
        dlg: _DiscoverInstallProgressDialog,
        repo_norm: str,
        ok: bool,
        download_err: str,
        pip_json: str,
    ) -> None:
        dlg.mark_finished(ok, download_err, pip_json)
        self._on_repo_download_finished(repo_norm, ok, download_err, pip_json)

    def _registry_entry_for_repo_norm(self, repo_norm: str) -> str:
        cache = self._discover_cache
        if not cache:
            return ""
        for rec in cache:
            if normalize_repo_slug(rec.repo) == repo_norm:
                return (rec.entry or "").strip()
        return ""

    @Slot(str, bool, str, str)
    def _on_repo_download_finished(
        self,
        repo_norm: str,
        ok: bool,
        download_err: str,
        pip_json: str,
    ) -> None:
        self._download_busy.discard(repo_norm)
        if not ok:
            message_fail(
                self,
                tr_i18n("plugins.discover_download_fail_title"),
                download_err or tr_i18n("plugins.discover_download_fail_body"),
            )
            self._repaint_discover_catalog_grid()
            return

        pip_code, pip_tail = _parse_pip_install_result_json(pip_json)
        pip_bad = pip_code in (
            "pip_failed",
            "pip_timeout",
            "pip_exception",
        )
        if pip_bad:
            dlg = tr_i18n("plugins.plugin_pip_fail_dialog_intro")
            if pip_tail:
                dlg = (
                    dlg
                    + "\n\n"
                    + tr_i18n("plugins.plugin_pip_detail_heading")
                    + "\n"
                    + pip_tail
                )
            message_fail(self, tr_i18n("plugins.plugin_pip_fail_title"), dlg)
            self._repaint_discover_catalog_grid()
            return

        entry_line = self._registry_entry_for_repo_norm(repo_norm)
        mark_repo_downloaded(
            repo_norm,
            manifest_entry=entry_line if entry_line else None,
        )
        base = tr_i18n("plugins.discover_download_ok_body")
        detail = ""
        if entry_line:
            try:
                outcome = append_plugin_manifest_entry_if_missing(
                    entry_line, enabled=True
                )
                if outcome == "added":
                    detail = tr_i18n("plugins.manifest_auto_added")
                elif outcome == "exists":
                    detail = tr_i18n("plugins.manifest_auto_exists")
                self._refresh_cards()
            except OSError as exc:
                message_fail(
                    self,
                    tr_i18n("plugins.manifest_auto_fail_title"),
                    str(exc),
                )
                detail = tr_i18n("plugins.manifest_auto_fail_hint")
        else:
            detail = tr_i18n("plugins.manifest_auto_skip_no_entry")

        pip_lines: list[str] = []
        if pip_code == "pip_ok":
            pip_lines.append(tr_i18n("plugins.plugin_pip_ok"))
        elif pip_code == "pip_skip_no_requirements":
            pip_lines.append(tr_i18n("plugins.plugin_pip_skip"))

        sections = [base]
        if pip_lines:
            sections.extend(pip_lines)
        if detail:
            sections.append(detail)
        toast_success(
            self,
            tr_i18n("plugins.discover_download_ok_title"),
            "\n\n".join(sections),
        )
        self._repaint_discover_catalog_grid()

    def _contributions_by_plugin(self) -> dict[str, list[SettingsUIContribution]]:
        by_pid: defaultdict[str, list[SettingsUIContribution]] = defaultdict(list)
        for c in collect_settings_contributions():
            key = c.plugin_id or f"_:{c.page_id}"
            by_pid[key].append(c)
        for lst in by_pid.values():
            lst.sort(key=lambda x: x.order)
        return dict(by_pid)

    def _tools_contribs_by_plugin(self) -> dict[str, list[ToolsTabContribution]]:
        by_pid: defaultdict[str, list[ToolsTabContribution]] = defaultdict(list)
        for c in collect_tools_tab_contributions():
            key = c.plugin_id or f"_:{c.tab_id}"
            by_pid[key].append(c)
        for lst in by_pid.values():
            lst.sort(key=lambda x: x.order)
        return dict(by_pid)

    def _widget_for_contribution(self, c: SettingsUIContribution) -> QWidget:
        if c.page_id not in self._contrib_widgets:
            self._contrib_widgets[c.page_id] = c.build(self._plg_ctx)
        return self._contrib_widgets[c.page_id]

    def _widget_for_tools_tab(self, c: ToolsTabContribution) -> QWidget:
        key = f"tools_tab:{c.tab_id}"
        if key not in self._contrib_widgets:
            self._contrib_widgets[key] = c.build(self._plg_ctx)
        return self._contrib_widgets[key]

    def _clear_grid(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _refresh_cards(self) -> None:
        self._clear_grid()
        mgr = get_plugin_manager()
        by_settings = self._contributions_by_plugin()
        by_tools = self._tools_contribs_by_plugin()

        rows: list[
            tuple[
                str,
                str,
                list[SettingsUIContribution],
                list[ToolsTabContribution],
                str | None,
                bool | None,
                str,
                str,
                str,
            ]
        ] = []
        seen_plugin_ids: set[str] = set()
        manifest_items = read_plugin_manifest_items()

        if manifest_items:
            for item in manifest_items:
                entry_raw = item.get("entry")
                if not isinstance(entry_raw, str):
                    continue
                entry = entry_raw.strip()
                enabled_yaml = bool(item.get("enabled", True))
                plugin = _resolve_plugin_for_manifest_entry(entry, mgr)
                if plugin is not None:
                    pid = plugin.plugin_id
                    seen_plugin_ids.add(pid)
                    ver = str(plugin.plugin_version)
                    s_cs = by_settings.get(pid, [])
                    t_cs = by_tools.get(pid, [])
                    dname = str(plugin.plugin_name).strip() or pid
                    desc = str(plugin.plugin_description or "").strip()
                    auth = str(plugin.plugin_author or "").strip()
                else:
                    pid = entry.strip()
                    ver = "—"
                    s_cs = []
                    t_cs = []
                    dname = _display_title_for_offline_entry(entry)
                    desc = ""
                    auth = ""
                rows.append((pid, ver, s_cs, t_cs, entry, enabled_yaml, dname, desc, auth))
        else:
            if mgr is not None:
                for p in mgr.plugins:
                    pid = p.plugin_id
                    seen_plugin_ids.add(pid)
                    rows.append(
                        (
                            pid,
                            str(p.plugin_version),
                            by_settings.get(pid, []),
                            by_tools.get(pid, []),
                            None,
                            None,
                            str(p.plugin_name).strip() or pid,
                            str(p.plugin_description or "").strip(),
                            str(p.plugin_author or "").strip(),
                        )
                    )

            for key in sorted(set(by_settings.keys()) | set(by_tools.keys())):
                lst_s = by_settings.get(key, [])
                lst_t = by_tools.get(key, [])
                if key.startswith("_:"):
                    disp = (
                        lst_s[0].nav_label
                        if lst_s
                        else (lst_t[0].title if lst_t else key)
                    )
                    rows.append((disp, "—", lst_s, lst_t, None, None, disp, "", ""))
                    continue
                if key not in seen_plugin_ids:
                    rows.append((key, "—", lst_s, lst_t, None, None, key, "", ""))

        if not rows:
            tip = QLabel(tr_i18n("plugins.empty_manage"))
            tip.setWordWrap(True)
            self._grid.addWidget(tip, 0, 0, 1, 2)
            return

        for i, row in enumerate(rows):
            pid, ver, s_cs, t_cs, manifest_entry, enabled_yaml, dname, desc, auth = row
            card = self._make_card(
                pid,
                ver,
                s_cs,
                t_cs,
                manifest_entry,
                enabled_yaml,
                dname,
                desc,
                auth,
            )
            r, co = divmod(i, 2)
            self._grid.addWidget(card, r, co)

    def _make_card(
        self,
        plugin_id: str,
        version: str,
        settings_cs: list[SettingsUIContribution],
        tools_cs: list[ToolsTabContribution],
        manifest_entry: str | None,
        enabled_yaml: bool | None,
        display_name: str,
        description: str,
        author: str,
    ) -> QFrame:
        box = QFrame()
        box.setFrameShape(QFrame.Shape.StyledPanel)
        box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        lay = QVBoxLayout(box)
        lay.setSpacing(6)
        title_row = QHBoxLayout()
        title = QLabel(display_name.strip() or plugin_id)
        f = title.font()
        f.setBold(True)
        title.setFont(f)
        title_row.addWidget(title, stretch=1)
        if manifest_entry is not None and enabled_yaml is not None:
            st_lbl = QLabel(tr_i18n("plugins.manage_enable_status_label"))
            st_lbl.setStyleSheet("color: palette(mid);")
            st_val = QLabel(
                tr_i18n("plugins.manage_status_enabled")
                if enabled_yaml
                else tr_i18n("plugins.manage_status_disabled")
            )
            st_val.setStyleSheet("color: palette(mid);")
            title_row.addWidget(st_lbl, alignment=Qt.AlignmentFlag.AlignRight)
            title_row.addWidget(st_val, alignment=Qt.AlignmentFlag.AlignRight)
        lay.addLayout(title_row)
        id_show = plugin_id.strip()
        name_show = (display_name.strip() or plugin_id).strip()
        if id_show and id_show != name_show:
            id_lbl = QLabel(tr_i18n("plugins.manage_plugin_id", plugin_id=id_show))
            id_lbl.setStyleSheet("color: palette(mid);")
            id_lbl.setWordWrap(True)
            lay.addWidget(id_lbl)
        desc_txt = description.strip()
        if desc_txt:
            desc_lbl = QLabel(desc_txt)
            desc_lbl.setWordWrap(True)
            desc_lbl.setStyleSheet("color: palette(mid);")
            lay.addWidget(desc_lbl)
        meta_parts: list[str] = [tr_i18n("plugins.version_label", version=version)]
        auth_txt = author.strip()
        if auth_txt:
            meta_parts.append(tr_i18n("plugins.manage_author", author=auth_txt))
        ver_lbl = QLabel(" · ".join(meta_parts))
        ver_lbl.setStyleSheet("color: palette(mid);")
        ver_lbl.setWordWrap(True)
        lay.addWidget(ver_lbl)
        has_ui = bool(settings_cs or tools_cs)

        row_act = QHBoxLayout()
        row_act.setSpacing(8)
        btn_uninstall = QPushButton(tr_i18n("plugins.manage_uninstall"))
        btn_toggle = QPushButton()
        btn_cfg = QPushButton(tr_i18n("plugins.manage_view_config"))
        dn_card = display_name.strip() or plugin_id

        if manifest_entry is None:
            btn_uninstall.setEnabled(False)
            btn_toggle.setEnabled(False)
            tip_na = tr_i18n("plugins.manage_no_manifest_tooltip")
            btn_uninstall.setToolTip(tip_na)
            btn_toggle.setToolTip(tip_na)
        else:
            ent_fixed = manifest_entry.strip()
            assert enabled_yaml is not None

            def _uninstall(*, ent: str = ent_fixed, name: str = dn_card) -> None:
                self._on_manage_uninstall(ent, name)

            btn_uninstall.clicked.connect(_uninstall)

            if enabled_yaml:
                btn_toggle.setText(tr_i18n("plugins.manage_disable"))
                btn_toggle.setToolTip(tr_i18n("plugins.manage_disable_tooltip"))
            else:
                btn_toggle.setText(tr_i18n("plugins.manage_enable"))
                btn_toggle.setToolTip(tr_i18n("plugins.manage_enable_tooltip"))

            def _toggle(*, ent: str = ent_fixed, cur: bool = enabled_yaml) -> None:
                self._on_manage_set_enabled(ent, not cur)

            btn_toggle.clicked.connect(_toggle)

        row_act.addWidget(btn_uninstall)
        row_act.addWidget(btn_toggle)

        if has_ui:

            def _open_plg(
                *,
                _title: str = display_name.strip() or plugin_id,
                _v: str = version,
                _sc: list[SettingsUIContribution] = settings_cs,
                _tc: list[ToolsTabContribution] = tools_cs,
            ) -> None:
                self._open_detail(_title, _v, _sc, _tc)

            btn_cfg.clicked.connect(_open_plg)
            btn_cfg.setToolTip(tr_i18n("plugins.manage_plugin_settings_tooltip"))
            row_act.addWidget(btn_cfg)
        # else: btn_cfg is never shown — plugin has no UI contribution
        lay.addLayout(row_act)

        lay.addStretch(0)
        return box

    def _on_manage_uninstall(self, manifest_entry: str, display_name: str) -> None:
        ent = manifest_entry.strip()
        if not ent:
            return
        r = QMessageBox.question(
            self,
            tr_i18n("plugins.manage_uninstall_confirm_title"),
            tr_i18n(
                "plugins.manage_uninstall_confirm_body",
                name=display_name or ent,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
            return
        try:
            removed = remove_plugin_manifest_entry(ent)
        except OSError as exc:
            message_fail(
                self,
                tr_i18n("plugins.manifest_write_failed_title"),
                str(exc),
            )
            return
        if not removed:
            message_fail(
                self,
                tr_i18n("plugins.manage_uninstall_fail_title"),
                tr_i18n("plugins.manage_uninstall_manifest_miss"),
            )
            return

        self._unmark_downloaded_repo_for_manifest_entry(ent)

        folder_note = ""
        d = infer_plugin_package_directory(ent)
        if d is not None and d.is_dir():
            plugins_root = Path("plugins").resolve()
            try:
                tgt = d.resolve()
            except OSError as exc:
                folder_note = str(exc)
            else:
                if tgt == plugins_root:
                    folder_note = tr_i18n("plugins.manage_uninstall_skip_folder")
                elif plugins_root in tgt.parents:
                    try:
                        shutil.rmtree(tgt)
                    except OSError as exc:
                        folder_note = str(exc)
                else:
                    folder_note = tr_i18n("plugins.manage_uninstall_skip_folder")

        self._refresh_cards()
        self._repaint_discover_catalog_grid()
        toast_success(
            self,
            tr_i18n("plugins.manage_uninstall_ok_title"),
            tr_i18n("plugins.restart_hint"),
        )
        if folder_note:
            toast_info(
                self,
                tr_i18n("plugins.manage_uninstall_folder_note_title"),
                folder_note,
            )

    def _unmark_downloaded_repo_for_manifest_entry(self, manifest_entry: str) -> None:
        if unmark_repo_for_manifest_entry(manifest_entry):
            return
        ent = normalize_manifest_entry(manifest_entry.strip())
        if not ent:
            return
        cache = self._discover_cache
        if not cache:
            return
        for rec in cache:
            re = (rec.entry or "").strip()
            if re and normalize_manifest_entry(re) == ent:
                unmark_repo_downloaded(rec.repo)
                break

    def _on_manage_set_enabled(self, manifest_entry: str, enabled: bool) -> None:
        ent = manifest_entry.strip()
        if not ent:
            return
        try:
            ok = set_plugin_manifest_enabled(ent, enabled)
        except OSError as exc:
            message_fail(
                self,
                tr_i18n("plugins.manifest_write_failed_title"),
                str(exc),
            )
            return
        if not ok:
            message_fail(
                self,
                tr_i18n("plugins.manifest_write_failed_title"),
                tr_i18n("plugins.manifest_write_failed_body"),
            )
            return
        toast_info(
            self,
            tr_i18n("plugins.manifest_saved_title"),
            tr_i18n("plugins.restart_hint"),
        )
        self._refresh_cards()

    def _discard_cached_widgets_in_subtree(self, root: QWidget) -> None:
        """Drop plugin-built widgets from cache before ``deleteLater`` destroys their C++ objects."""
        subtree: set[QWidget] = {root}
        subtree.update(root.findChildren(QWidget))
        drop = [k for k, v in self._contrib_widgets.items() if v in subtree]
        for k in drop:
            del self._contrib_widgets[k]

    def _clear_detail_content(self) -> None:
        while self._detail_stack_layout.count():
            item = self._detail_stack_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                self._discard_cached_widgets_in_subtree(w)
                w.deleteLater()

    def _open_detail(
        self,
        display_title: str,
        version: str,
        settings_cs: list[SettingsUIContribution],
        tools_cs: list[ToolsTabContribution],
    ) -> None:
        self._detail_title.setText(
            tr_i18n("plugins.detail_heading", name=display_title, version=version)
        )
        self._clear_detail_content()
        tabs_spec: list[tuple[str, QWidget]] = []
        for c in sorted(settings_cs, key=lambda x: x.order):
            tabs_spec.append((c.nav_label, self._widget_for_contribution(c)))
        for c in sorted(tools_cs, key=lambda x: x.order):
            tabs_spec.append((c.title, self._widget_for_tools_tab(c)))
        if len(tabs_spec) == 1:
            self._detail_stack_layout.addWidget(tabs_spec[0][1])
        elif tabs_spec:
            nav = SegmentedTabNav()
            for label, w in tabs_spec:
                nav.add_tab(w, label)
            self._detail_stack_layout.addWidget(nav)
        self._outer.setCurrentIndex(1)
