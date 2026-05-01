"""插件设置页：管理（卡片网格）与「发现」占位。"""

from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.plugins.plugin_host import (
    collect_settings_contributions,
    get_plugin_manager,
    read_plugin_manifest_items,
    set_plugin_manifest_enabled,
)
from i18n import tr as tr_i18n
from sdk.plugin_host_context import PluginSettingsUIContext
from sdk.types import SettingsUIContribution

from ui.settings_ui.context import SettingsUIContext
from ui.settings_ui.feedback import message_fail, toast_info


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
        dv.setContentsMargins(16, 24, 16, 24)
        ph = QLabel(tr_i18n("plugins.discover_placeholder"))
        ph.setWordWrap(True)
        ph.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        dv.addWidget(ph)
        dv.addStretch(1)
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
        self._refresh_cards()

    def apply_i18n(self) -> None:
        self._sub_tabs.setTabText(0, tr_i18n("plugins.tab_manage"))
        self._sub_tabs.setTabText(1, tr_i18n("plugins.tab_discover"))
        self._back_btn.setText(tr_i18n("plugins.back"))
        self._refresh_cards()

    def _contributions_by_plugin(self) -> dict[str, list[SettingsUIContribution]]:
        by_pid: defaultdict[str, list[SettingsUIContribution]] = defaultdict(list)
        for c in collect_settings_contributions():
            key = c.plugin_id or f"_:{c.page_id}"
            by_pid[key].append(c)
        for lst in by_pid.values():
            lst.sort(key=lambda x: x.order)
        return dict(by_pid)

    def _widget_for_contribution(self, c: SettingsUIContribution) -> QWidget:
        if c.page_id not in self._contrib_widgets:
            self._contrib_widgets[c.page_id] = c.build(self._plg_ctx)
        return self._contrib_widgets[c.page_id]

    def _clear_grid(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _refresh_cards(self) -> None:
        self._clear_grid()
        mgr = get_plugin_manager()
        by_pid = self._contributions_by_plugin()

        rows: list[
            tuple[str, str, list[SettingsUIContribution], str | None, bool | None]
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
                    contribs = by_pid.get(pid, [])
                else:
                    pid = _display_title_for_offline_entry(entry)
                    ver = "—"
                    contribs = []
                rows.append((pid, ver, contribs, entry, enabled_yaml))
        else:
            if mgr is not None:
                for p in mgr.plugins:
                    pid = p.plugin_id
                    seen_plugin_ids.add(pid)
                    rows.append((pid, str(p.plugin_version), by_pid.get(pid, []), None, None))

            for key in sorted(by_pid.keys()):
                lst = by_pid[key]
                if key.startswith("_:"):
                    disp = lst[0].nav_label if lst else key
                    rows.append((disp, "—", lst, None, None))
                    continue
                if key not in seen_plugin_ids:
                    rows.append((key, "—", lst, None, None))

        if not rows:
            tip = QLabel(tr_i18n("plugins.empty_manage"))
            tip.setWordWrap(True)
            self._grid.addWidget(tip, 0, 0, 1, 2)
            return

        for i, row in enumerate(rows):
            pid, ver, contribs, manifest_entry, enabled_yaml = row
            card = self._make_card(pid, ver, contribs, manifest_entry, enabled_yaml)
            r, co = divmod(i, 2)
            self._grid.addWidget(card, r, co)

    def _make_card(
        self,
        plugin_id: str,
        version: str,
        contribs: list[SettingsUIContribution],
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
        if not contribs:
            btn.setEnabled(False)
            btn.setToolTip(tr_i18n("plugins.no_settings_tooltip"))
        else:

            def _go(
                *,
                _pid: str = plugin_id,
                _v: str = version,
                _cs: list[SettingsUIContribution] = contribs,
            ) -> None:
                self._open_detail(_pid, _v, _cs)

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

    def _clear_detail_content(self) -> None:
        while self._detail_stack_layout.count():
            item = self._detail_stack_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _open_detail(
        self,
        plugin_id: str,
        version: str,
        contribs: list[SettingsUIContribution],
    ) -> None:
        self._detail_title.setText(
            tr_i18n("plugins.detail_heading", name=plugin_id, version=version)
        )
        self._clear_detail_content()
        if len(contribs) == 1:
            self._detail_stack_layout.addWidget(self._widget_for_contribution(contribs[0]))
        else:
            tw = QTabWidget()
            for c in contribs:
                tw.addTab(self._widget_for_contribution(c), c.nav_label)
            self._detail_stack_layout.addWidget(tw)
        self._outer.setCurrentIndex(1)
