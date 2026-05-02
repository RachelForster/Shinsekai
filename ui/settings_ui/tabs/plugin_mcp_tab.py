"""插件设置 — MCP 服务与工具管理（独立页，由 :class:`plugin_tab.PluginSettingsTab` 嵌入）。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import yaml
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from i18n import tr as tr_i18n
from llm.tools.mcp_config_file import (
    DEFAULT_MCP_CONFIG_PATH,
    default_mcp_config,
    read_mcp_config,
    write_mcp_config,
)
from llm.tools.mcp_tool_setup import (
    preview_mcp_tools_from_config,
    reload_mcp_tools_from_config,
)
from llm.tools.tool_manager import ToolManager
from ui.settings_ui.context import SettingsUIContext
from ui.settings_ui.feedback import message_fail, toast_success


def _table_style_apple_like() -> str:
    return (
        "QTableWidget { gridline-color: palette(mid); }\n"
        "QHeaderView::section { padding: 4px 8px; font-weight: bold; }\n"
        "QTableWidget::item { padding: 4px 8px; }\n"
        "QTableWidget::item:selected,\n"
        "QTableWidget::item:selected:active { background-color: palette(base); color: palette(text); }\n"
        "QTableWidget:focus { outline: none; }\n"
    )


class _McpServerEditDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        transport_default: str,
        entry: dict | None = None,
    ) -> None:
        super().__init__(parent)
        self._entry = entry
        self._saved: dict | None = None
        self.setWindowTitle(
            tr_i18n("plugins.mcp_dialog_title_edit")
            if entry
            else tr_i18n("plugins.mcp_dialog_title_add")
        )
        self.resize(480, 420)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self._enabled = QCheckBox(tr_i18n("plugins.mcp_col_enabled"))
        self._prefix = QLineEdit()
        self._prefix.setPlaceholderText(tr_i18n("plugins.mcp_prefix_placeholder"))
        self._timeout = QSpinBox()
        self._timeout.setRange(0, 86400)
        self._timeout.setSpecialValueText(tr_i18n("plugins.mcp_timeout_default"))
        self._timeout.setValue(0)
        self._transport = QComboBox()
        self._transport.addItem("SSE", "sse")
        self._transport.addItem("stdio", "stdio")
        idx = 0 if transport_default.strip().lower() != "stdio" else 1
        self._transport.setCurrentIndex(idx)

        self._url = QLineEdit()
        self._headers_json = QPlainTextEdit()
        self._headers_json.setPlaceholderText("{ }")
        self._headers_json.setMaximumBlockCount(200)
        self._headers_json.setFixedHeight(72)

        self._command = QLineEdit()
        self._args_json = QPlainTextEdit()
        self._args_json.setPlaceholderText('["-y", "package"]')
        self._args_json.setMaximumBlockCount(50)
        self._args_json.setFixedHeight(64)

        form.addRow(self._enabled)
        form.addRow(tr_i18n("plugins.mcp_prefix"), self._prefix)
        form.addRow(tr_i18n("plugins.mcp_call_timeout"), self._timeout)
        form.addRow(tr_i18n("plugins.mcp_transport"), self._transport)
        form.addRow(tr_i18n("plugins.mcp_sse_url"), self._url)
        form.addRow(tr_i18n("plugins.mcp_sse_headers_json"), self._headers_json)
        form.addRow(tr_i18n("plugins.mcp_stdio_command"), self._command)
        form.addRow(tr_i18n("plugins.mcp_stdio_args_json"), self._args_json)
        root.addLayout(form)

        self._transport.currentIndexChanged.connect(self._sync_transport_ui)
        self._sync_transport_ui()

        bbox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bbox.accepted.connect(self._try_accept)
        bbox.rejected.connect(self.reject)
        root.addWidget(bbox)

        if entry:
            self._fill_from_entry(entry)

    def _sync_transport_ui(self) -> None:
        is_sse = self._transport.currentData() == "sse"
        self._url.setVisible(is_sse)
        self._headers_json.setVisible(is_sse)
        self._command.setVisible(not is_sse)
        self._args_json.setVisible(not is_sse)

    def _fill_from_entry(self, entry: dict) -> None:
        self._enabled.setChecked(entry.get("enabled") is not False)
        self._prefix.setText(str(entry.get("name_prefix") or ""))
        ct = entry.get("call_timeout")
        if ct is not None:
            try:
                self._timeout.setValue(int(float(ct)))
            except (TypeError, ValueError):
                self._timeout.setValue(0)
        else:
            self._timeout.setValue(0)
        tr = str(entry.get("transport") or "sse").strip().lower()
        self._transport.setCurrentIndex(1 if tr == "stdio" else 0)
        self._url.setText(str(entry.get("url") or ""))
        hdr = entry.get("headers")
        if isinstance(hdr, dict) and hdr:
            try:
                self._headers_json.setPlainText(
                    json.dumps(hdr, ensure_ascii=False, indent=2)
                )
            except Exception:
                self._headers_json.setPlainText("{}")
        else:
            self._headers_json.setPlainText("{}")
        self._command.setText(str(entry.get("command") or ""))
        args = entry.get("args")
        if isinstance(args, list) and args:
            try:
                self._args_json.setPlainText(
                    json.dumps(args, ensure_ascii=False)
                )
            except Exception:
                self._args_json.setPlainText("[]")
        else:
            self._args_json.setPlainText("[]")

    def _try_accept(self) -> None:
        try:
            self._saved = self._validated_result()
        except ValueError as e:
            message_fail(
                self,
                tr_i18n("plugins.mcp_validate_title"),
                str(e),
            )
            return
        self.accept()

    def _validated_result(self) -> dict:
        transport = str(self._transport.currentData() or "sse")
        row: dict = {
            "enabled": self._enabled.isChecked(),
            "name_prefix": self._prefix.text().strip(),
            "transport": transport,
        }
        if self._timeout.value() > 0:
            row["call_timeout"] = float(self._timeout.value())
        if transport == "sse":
            url = self._url.text().strip()
            if not url:
                raise ValueError(tr_i18n("plugins.mcp_err_need_url"))
            row["url"] = url
            raw_h = self._headers_json.toPlainText().strip()
            if raw_h:
                try:
                    parsed = json.loads(raw_h)
                except json.JSONDecodeError as e:
                    raise ValueError(
                        tr_i18n("plugins.mcp_err_headers_json", detail=str(e))
                    ) from e
                if not isinstance(parsed, dict):
                    raise ValueError(tr_i18n("plugins.mcp_err_headers_object"))
                row["headers"] = {str(k): str(v) for k, v in parsed.items()}
        else:
            cmd = self._command.text().strip()
            if not cmd:
                raise ValueError(tr_i18n("plugins.mcp_err_need_command"))
            row["command"] = cmd
            raw_a = self._args_json.toPlainText().strip()
            if raw_a:
                try:
                    parsed = json.loads(raw_a)
                except json.JSONDecodeError as e:
                    raise ValueError(
                        tr_i18n("plugins.mcp_err_args_json", detail=str(e))
                    ) from e
                if not isinstance(parsed, list):
                    raise ValueError(tr_i18n("plugins.mcp_err_args_array"))
                row["args"] = [str(x) for x in parsed]
            else:
                row["args"] = []
        return row

    def get_result(self) -> dict:
        if self._saved is None:
            raise ValueError("dialog not accepted")
        return dict(self._saved)


class _PreviewSignals(QObject):
    finished = Signal(list)
    failed = Signal(str)


class _PreviewTask(QRunnable):
    def __init__(self, payload: dict, sig: _PreviewSignals) -> None:
        super().__init__()
        self._payload = payload
        self._sig = sig
        self.setAutoDelete(True)

    def run(self) -> None:
        path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".yaml", delete=False, encoding="utf-8"
            ) as tf:
                yaml.safe_dump(
                    self._payload,
                    tf,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                )
                path = Path(tf.name)
            rows = preview_mcp_tools_from_config(path)
            self._sig.finished.emit(rows)
        except Exception as e:
            self._sig.failed.emit(str(e))
        finally:
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass


class PluginMcpTab(QWidget):
    def __init__(self, ctx: SettingsUIContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._config_path = DEFAULT_MCP_CONFIG_PATH
        self._servers: list[dict] = []
        self._busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)

        hint = QLabel()
        hint.setWordWrap(True)
        hint.setOpenExternalLinks(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        self._hint = hint
        layout.addWidget(hint)

        glob_row = QHBoxLayout()
        self._global_enabled = QCheckBox()
        self._global_enabled.toggled.connect(self._on_global_toggled)
        glob_row.addWidget(self._global_enabled)
        glob_row.addWidget(QLabel(tr_i18n("plugins.mcp_default_timeout")))
        self._default_timeout = QSpinBox()
        self._default_timeout.setRange(1, 86400)
        self._default_timeout.setValue(300)
        glob_row.addWidget(self._default_timeout)
        glob_row.addStretch(1)
        layout.addLayout(glob_row)

        srv_box = QGroupBox()
        self._server_group = srv_box
        sb_lay = QVBoxLayout(srv_box)
        toolbar = QHBoxLayout()
        self._btn_add_sse = QPushButton()
        self._btn_add_sse.clicked.connect(lambda: self._add_server("sse"))
        toolbar.addWidget(self._btn_add_sse)
        self._btn_add_stdio = QPushButton()
        self._btn_add_stdio.clicked.connect(lambda: self._add_server("stdio"))
        toolbar.addWidget(self._btn_add_stdio)
        self._btn_save = QPushButton()
        self._btn_save.clicked.connect(self._on_save)
        toolbar.addWidget(self._btn_save)
        self._btn_open_file = QPushButton()
        self._btn_open_file.clicked.connect(self._on_open_yaml)
        toolbar.addWidget(self._btn_open_file)
        toolbar.addStretch(1)
        sb_lay.addLayout(toolbar)

        self._server_table = QTableWidget(0, 6)
        self._server_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._server_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._server_table.setAlternatingRowColors(True)
        self._server_table.verticalHeader().setVisible(False)
        self._server_table.setStyleSheet(_table_style_apple_like())
        hh = self._server_table.horizontalHeader()
        for i in range(6):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        sb_lay.addWidget(self._server_table)
        layout.addWidget(srv_box)

        tools_box = QGroupBox()
        self._tools_group = tools_box
        tl = QVBoxLayout(tools_box)
        tbar = QHBoxLayout()
        self._btn_refresh_tools = QPushButton()
        self._btn_refresh_tools.clicked.connect(self._on_refresh_tools)
        tbar.addWidget(self._btn_refresh_tools)
        self._tools_status = QLabel()
        self._tools_status.setWordWrap(True)
        self._tools_status.setStyleSheet("color: palette(mid);")
        tbar.addWidget(self._tools_status, stretch=1)
        tl.addLayout(tbar)
        self._tools_intro = QLabel()
        self._tools_intro.setWordWrap(True)
        self._tools_intro.setStyleSheet("color: palette(mid);")
        tl.addWidget(self._tools_intro)
        self._tools_table = QTableWidget(0, 4)
        self._tools_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._tools_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tools_table.setAlternatingRowColors(True)
        self._tools_table.verticalHeader().setVisible(False)
        self._tools_table.setStyleSheet(_table_style_apple_like())
        th = self._tools_table.horizontalHeader()
        for i in range(4):
            th.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        tl.addWidget(self._tools_table, stretch=1)
        layout.addWidget(tools_box, stretch=1)

        self._preview_signals = _PreviewSignals(self)
        self._preview_signals.finished.connect(self._on_preview_done)
        self._preview_signals.failed.connect(self._on_preview_fail)

        self.apply_i18n()
        self._load_from_disk()

    def apply_i18n(self) -> None:
        self._hint.setText(tr_i18n("plugins.mcp_hint_html"))
        self._global_enabled.setText(tr_i18n("plugins.mcp_global_enable"))
        self._server_group.setTitle(tr_i18n("plugins.mcp_servers_group"))
        self._btn_add_sse.setText(tr_i18n("plugins.mcp_add_sse"))
        self._btn_add_stdio.setText(tr_i18n("plugins.mcp_add_stdio"))
        self._btn_save.setText(tr_i18n("plugins.mcp_save_apply"))
        self._btn_open_file.setText(tr_i18n("plugins.mcp_open_yaml"))
        self._tools_group.setTitle(tr_i18n("plugins.mcp_tools_group"))
        self._btn_refresh_tools.setText(tr_i18n("plugins.mcp_refresh_tools"))
        self._tools_intro.setText(tr_i18n("plugins.mcp_tools_intro"))
        self._apply_server_headers()
        self._apply_tools_headers()
        self._render_server_table()

    def _apply_server_headers(self) -> None:
        self._server_table.setHorizontalHeaderLabels(
            [
                tr_i18n("plugins.mcp_col_enabled"),
                tr_i18n("plugins.mcp_col_prefix"),
                tr_i18n("plugins.mcp_col_transport"),
                tr_i18n("plugins.mcp_col_connection"),
                tr_i18n("plugins.mcp_col_edit"),
                tr_i18n("plugins.mcp_col_delete"),
            ]
        )

    def _apply_tools_headers(self) -> None:
        self._tools_table.setHorizontalHeaderLabels(
            [
                tr_i18n("plugins.mcp_col_prefix"),
                tr_i18n("plugins.mcp_col_registered_name"),
                tr_i18n("plugins.mcp_col_tool_name"),
                tr_i18n("plugins.mcp_col_description"),
            ]
        )

    def _on_global_toggled(self, checked: bool) -> None:
        self._server_table.setEnabled(checked)
        self._btn_add_sse.setEnabled(checked)
        self._btn_add_stdio.setEnabled(checked)
        self._btn_refresh_tools.setEnabled(checked)
        self._tools_table.setEnabled(checked)

    def _load_from_disk(self) -> None:
        cfg = read_mcp_config(self._config_path)
        self._global_enabled.setChecked(cfg.get("enabled") is not False)
        try:
            self._default_timeout.setValue(int(float(cfg.get("default_call_timeout", 300))))
        except (TypeError, ValueError):
            self._default_timeout.setValue(300)
        self._servers = list(cfg.get("servers") or [])
        self._render_server_table()
        self._on_global_toggled(self._global_enabled.isChecked())

    def _render_server_table(self) -> None:
        self._server_table.clearContents()
        self._server_table.setRowCount(len(self._servers))
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        for row, entry in enumerate(self._servers):
            en = entry.get("enabled") is not False
            it_en = QTableWidgetItem(tr_i18n("plugins.mcp_yes") if en else tr_i18n("plugins.mcp_no"))
            it_en.setFlags(flags)
            self._server_table.setItem(row, 0, it_en)
            it_pf = QTableWidgetItem(str(entry.get("name_prefix") or ""))
            it_pf.setFlags(flags)
            self._server_table.setItem(row, 1, it_pf)
            tr = str(entry.get("transport") or "")
            it_tr = QTableWidgetItem(tr.upper())
            it_tr.setFlags(flags)
            self._server_table.setItem(row, 2, it_tr)
            if tr.strip().lower() == "stdio":
                cmd = str(entry.get("command") or "")
                args = entry.get("args")
                if isinstance(args, list) and args:
                    summary = cmd + " " + " ".join(str(a) for a in args[:6])
                    if len(args) > 6:
                        summary += "…"
                else:
                    summary = cmd
            else:
                summary = str(entry.get("url") or "")
            it_sum = QTableWidgetItem(summary)
            it_sum.setToolTip(summary)
            it_sum.setFlags(flags)
            self._server_table.setItem(row, 3, it_sum)

            edit_btn = QPushButton(tr_i18n("plugins.mcp_edit"))
            edit_btn.clicked.connect(
                lambda checked=False, r=row: self._edit_server(r)
            )
            del_btn = QPushButton(tr_i18n("plugins.mcp_delete"))
            del_btn.clicked.connect(
                lambda checked=False, r=row: self._delete_server(r)
            )
            self._server_table.setCellWidget(row, 4, edit_btn)
            self._server_table.setCellWidget(row, 5, del_btn)

    def _add_server(self, transport: str) -> None:
        dlg = _McpServerEditDialog(self, transport, None)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._servers.append(dlg.get_result())
        except ValueError:
            return
        self._render_server_table()

    def _edit_server(self, row: int) -> None:
        if row < 0 or row >= len(self._servers):
            return
        entry = dict(self._servers[row])
        tr = str(entry.get("transport") or "sse")
        dlg = _McpServerEditDialog(self, tr, entry)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._servers[row] = dlg.get_result()
        except ValueError:
            return
        self._render_server_table()

    def _delete_server(self, row: int) -> None:
        if row < 0 or row >= len(self._servers):
            return
        r = QMessageBox.question(
            self,
            tr_i18n("plugins.mcp_delete_confirm_title"),
            tr_i18n("plugins.mcp_delete_confirm_body"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
            return
        del self._servers[row]
        self._render_server_table()

    def _collect_payload(self) -> dict:
        return {
            "enabled": self._global_enabled.isChecked(),
            "default_call_timeout": float(self._default_timeout.value()),
            "servers": list(self._servers),
        }

    def _on_save(self) -> None:
        data = self._collect_payload()
        try:
            write_mcp_config(data, self._config_path)
        except Exception as e:
            message_fail(
                self,
                tr_i18n("plugins.mcp_save_fail_title"),
                str(e),
            )
            return
        try:
            reload_mcp_tools_from_config(ToolManager(), self._config_path)
        except ImportError:
            message_fail(
                self,
                tr_i18n("plugins.mcp_need_package_title"),
                tr_i18n("plugins.mcp_reload_need_package"),
            )
            return
        except Exception as e:
            message_fail(
                self,
                tr_i18n("plugins.mcp_reload_fail_title"),
                str(e),
            )
            return
        toast_success(
            self,
            tr_i18n("plugins.mcp_save_ok_title"),
            tr_i18n("plugins.mcp_save_ok_body"),
        )

    def _on_open_yaml(self) -> None:
        p = self._config_path.resolve()
        if not p.parent.is_dir():
            p.parent.mkdir(parents=True, exist_ok=True)
        if not p.is_file():
            write_mcp_config(default_mcp_config(), self._config_path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _on_refresh_tools(self) -> None:
        if self._busy:
            return
        try:
            __import__("mcp")
        except ImportError:
            message_fail(
                self,
                tr_i18n("plugins.mcp_need_package_title"),
                tr_i18n("plugins.mcp_need_package_body"),
            )
            return
        self._busy = True
        self._btn_refresh_tools.setEnabled(False)
        self._tools_status.setText(tr_i18n("plugins.mcp_preview_loading"))
        QThreadPool.globalInstance().start(
            _PreviewTask(self._collect_payload(), self._preview_signals)
        )

    @Slot(list)
    def _on_preview_done(self, rows: list) -> None:
        self._busy = False
        self._btn_refresh_tools.setEnabled(True)
        self._tools_status.clear()
        valid = [x for x in rows if isinstance(x, dict)]
        self._tools_table.setRowCount(len(valid))
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        for i, item in enumerate(valid):
            it0 = QTableWidgetItem(str(item.get("prefix") or ""))
            it0.setFlags(flags)
            it1 = QTableWidgetItem(str(item.get("registered_name") or ""))
            it1.setFlags(flags)
            it2 = QTableWidgetItem(str(item.get("name") or ""))
            it2.setFlags(flags)
            it3 = QTableWidgetItem(str(item.get("description") or ""))
            it3.setFlags(flags)
            self._tools_table.setItem(i, 0, it0)
            self._tools_table.setItem(i, 1, it1)
            self._tools_table.setItem(i, 2, it2)
            self._tools_table.setItem(i, 3, it3)
        if not valid:
            self._tools_status.setText(tr_i18n("plugins.mcp_preview_empty"))

    @Slot(str)
    def _on_preview_fail(self, msg: str) -> None:
        self._busy = False
        self._btn_refresh_tools.setEnabled(True)
        self._tools_status.clear()
        message_fail(
            self,
            tr_i18n("plugins.mcp_preview_fail_title"),
            msg,
        )
