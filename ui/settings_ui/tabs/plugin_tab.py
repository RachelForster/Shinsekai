"""插件设置页：管理插件（卡片网格）与从远程索引「发现插件」。"""


from __future__ import annotations

import json
from collections import defaultdict

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QAbstractItemView,
    QStackedWidget,
    QTabWidget,
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
    read_plugin_manifest_items,
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
    download_github_repo_sources,
    format_download_error,
    load_downloaded_repos,
    mark_repo_downloaded,
    normalize_repo_slug,
)
from i18n import tr as tr_i18n
from sdk.plugin_host_context import PluginSettingsUIContext
from sdk.types import SettingsUIContribution, ToolsTabContribution

from ui.settings_ui.context import SettingsUIContext
from ui.settings_ui.feedback import message_fail, toast_info, toast_success


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
    """repo_norm, ok, download_error (empty if ok), pip_result_json (empty if not ok)."""

    finished = Signal(str, bool, str, str)


class _DownloadRepoTask(QRunnable):
    def __init__(self, repo: str, sig: _DownloadSignals) -> None:
        super().__init__()
        self._repo = repo
        self._sig = sig
        self.setAutoDelete(True)

    def run(self) -> None:
        norm = normalize_repo_slug(self._repo)
        try:
            dest = download_github_repo_sources(self._repo)
        except Exception as exc:
            self._sig.finished.emit(norm, False, format_download_error(exc), "")
            return
        pip_code, pip_detail = install_plugin_requirements_txt(dest)
        pip_payload = json.dumps(
            {"pip": pip_code, "detail": pip_detail}, ensure_ascii=False
        )
        self._sig.finished.emit(norm, True, "", pip_payload)


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
        self._outer = QStackedWidget(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._outer)

        list_page = QWidget()
        lp_lay = QVBoxLayout(list_page)
        lp_lay.setContentsMargins(0, 0, 0, 0)
        sub_tabs = QTabWidget()
        self._sub_tabs = sub_tabs

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
        sub_tabs.addTab(manage_host, tr_i18n("plugins.tab_manage"))

        discover_host = QWidget()
        dv = QVBoxLayout(discover_host)
        dv.setContentsMargins(4, 8, 4, 8)
        toolbar = QHBoxLayout()
        self._discover_refresh_btn = QPushButton(tr_i18n("plugins.discover_refresh"))
        self._discover_refresh_btn.clicked.connect(self._refresh_discover_catalog)
        toolbar.addWidget(self._discover_refresh_btn)
        toolbar.addStretch(1)
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
        self._download_signals = _DownloadSignals(self)
        self._download_signals.finished.connect(self._on_repo_download_finished)
        sub_tabs.currentChanged.connect(self._on_plugin_subtab_changed)

        sub_tabs.addTab(discover_host, tr_i18n("plugins.tab_discover"))

        lp_lay.addWidget(sub_tabs)
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

    def apply_i18n(self) -> None:
        self._sub_tabs.setTabText(0, tr_i18n("plugins.tab_manage"))
        self._sub_tabs.setTabText(1, tr_i18n("plugins.tab_discover"))
        self._back_btn.setText(tr_i18n("plugins.back"))
        self._discover_refresh_btn.setText(tr_i18n("plugins.discover_refresh"))
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
        elif repo_norm in downloaded:
            dl_btn.setText(tr_i18n("plugins.discover_downloaded"))
            dl_btn.setEnabled(False)
            dl_btn.setToolTip(tr_i18n("plugins.discover_downloaded_tooltip"))
        elif repo_norm in self._download_busy:
            dl_btn.setText(tr_i18n("plugins.discover_downloading"))
            dl_btn.setEnabled(False)
        else:
            dl_btn.setText(tr_i18n("plugins.discover_download"))
            dl_btn.setToolTip(tr_i18n("plugins.discover_download_tooltip"))
            dl_btn.clicked.connect(
                lambda checked=False, r=rec.repo, b=dl_btn: self._start_repo_download(r, b)
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

    def _start_repo_download(self, repo: str, btn: QPushButton) -> None:
        norm = normalize_repo_slug(repo)
        if norm in self._download_busy or not norm:
            return
        self._download_busy.add(norm)
        btn.setEnabled(False)
        btn.setText(tr_i18n("plugins.discover_downloading"))
        QThreadPool.globalInstance().start(_DownloadRepoTask(repo, self._download_signals))

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
        if ok:
            mark_repo_downloaded(repo_norm)
            base = tr_i18n("plugins.discover_download_ok_body")
            entry_line = self._registry_entry_for_repo_norm(repo_norm)
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

            pip_code, pip_tail = _parse_pip_install_result_json(pip_json)
            pip_bad = pip_code in (
                "pip_failed",
                "pip_timeout",
                "pip_exception",
            )
            pip_lines: list[str] = []
            if pip_code == "pip_ok":
                pip_lines.append(tr_i18n("plugins.plugin_pip_ok"))
            elif pip_code == "pip_skip_no_requirements":
                pip_lines.append(tr_i18n("plugins.plugin_pip_skip"))
            elif pip_bad:
                pip_lines.append(tr_i18n("plugins.plugin_pip_fail_toast_hint"))

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
        else:
            message_fail(
                self,
                tr_i18n("plugins.discover_download_fail_title"),
                download_err or tr_i18n("plugins.discover_download_fail_body"),
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
                else:
                    pid = _display_title_for_offline_entry(entry)
                    ver = "—"
                    s_cs = []
                    t_cs = []
                rows.append((pid, ver, s_cs, t_cs, entry, enabled_yaml))
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
                    rows.append((disp, "—", lst_s, lst_t, None, None))
                    continue
                if key not in seen_plugin_ids:
                    rows.append((key, "—", lst_s, lst_t, None, None))

        if not rows:
            tip = QLabel(tr_i18n("plugins.empty_manage"))
            tip.setWordWrap(True)
            self._grid.addWidget(tip, 0, 0, 1, 2)
            return

        for i, row in enumerate(rows):
            pid, ver, s_cs, t_cs, manifest_entry, enabled_yaml = row
            card = self._make_card(pid, ver, s_cs, t_cs, manifest_entry, enabled_yaml)
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
    ) -> QFrame:
        box = QFrame()
        box.setFrameShape(QFrame.Shape.StyledPanel)
        box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        lay = QVBoxLayout(box)
        title_row = QHBoxLayout()
        title = QLabel(plugin_id)
        f = title.font()
        f.setBold(True)
        title.setFont(f)
        title_row.addWidget(title, stretch=1)
        if manifest_entry is not None and enabled_yaml is not None:
            cb = QCheckBox(tr_i18n("plugins.enable_switch"))
            cb.setChecked(enabled_yaml)
            cb.setToolTip(tr_i18n("plugins.toggle_tooltip"))

            def _on_toggled(checked: bool, *, ent: str = manifest_entry) -> None:
                self._persist_manifest_toggle(ent, cb, checked)

            cb.toggled.connect(_on_toggled)
            title_row.addWidget(cb, alignment=Qt.AlignmentFlag.AlignRight)
        lay.addLayout(title_row)
        ver_lbl = QLabel(tr_i18n("plugins.version_label", version=version))
        ver_lbl.setStyleSheet("color: palette(mid);")
        lay.addWidget(ver_lbl)
        btn = QPushButton(tr_i18n("plugins.open_settings"))
        has_ui = bool(settings_cs or tools_cs)
        if not has_ui:
            btn.setEnabled(False)
            btn.setToolTip(tr_i18n("plugins.no_settings_tooltip"))
        else:

            def _go(
                *,
                _pid: str = plugin_id,
                _v: str = version,
                _sc: list[SettingsUIContribution] = settings_cs,
                _tc: list[ToolsTabContribution] = tools_cs,
            ) -> None:
                self._open_detail(_pid, _v, _sc, _tc)

            btn.clicked.connect(_go)
        lay.addWidget(btn)
        lay.addStretch(0)
        return box

    def _persist_manifest_toggle(self, entry: str, cb: QCheckBox, checked: bool) -> None:
        try:
            ok = set_plugin_manifest_enabled(entry, checked)
        except OSError as exc:
            ok = False
            err_detail = str(exc)
        else:
            err_detail = ""
        if not ok:
            cb.blockSignals(True)
            cb.setChecked(not checked)
            cb.blockSignals(False)
            body = err_detail or tr_i18n("plugins.manifest_write_failed_body")
            message_fail(self, tr_i18n("plugins.manifest_write_failed_title"), body)
            return
        toast_info(
            self,
            tr_i18n("plugins.manifest_saved_title"),
            tr_i18n("plugins.restart_hint"),
        )

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
        plugin_id: str,
        version: str,
        settings_cs: list[SettingsUIContribution],
        tools_cs: list[ToolsTabContribution],
    ) -> None:
        self._detail_title.setText(
            tr_i18n("plugins.detail_heading", name=plugin_id, version=version)
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
            tw = QTabWidget()
            for label, w in tabs_spec:
                tw.addTab(w, label)
            self._detail_stack_layout.addWidget(tw)
        self._outer.setCurrentIndex(1)
