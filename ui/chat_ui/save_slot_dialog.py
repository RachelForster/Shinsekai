"""Save/load slot picker for the desktop chat window."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem, QVBoxLayout

from core.sprite.save_slots import SaveSlotSummary
from i18n import tr


class SaveSlotDialog(QDialog):
    def __init__(
        self,
        *,
        mode: str,
        slots: list[SaveSlotSummary],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.mode = "load" if mode == "load" else "save"
        self.slots = list(slots)
        self.selected_slot_id: str = ""
        self.setModal(True)
        self.resize(560, 520)
        self.setWindowTitle(
            tr(
                "desktop.menu.save_slot_load_title"
                if self.mode == "load"
                else "desktop.menu.save_slot_save_title"
            )
        )

        layout = QVBoxLayout(self)
        hint = QLabel(
            tr(
                "desktop.menu.save_slot_load_hint"
                if self.mode == "load"
                else "desktop.menu.save_slot_save_hint"
            )
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.slot_list = QListWidget()
        self.slot_list.itemDoubleClicked.connect(self._on_double_clicked)
        self.slot_list.currentItemChanged.connect(
            lambda _cur, _prev: self._update_button_state()
        )
        layout.addWidget(self.slot_list)

        buttons = (
            QDialogButtonBox.StandardButton.Open
            if self.mode == "load"
            else QDialogButtonBox.StandardButton.Save
        ) | QDialogButtonBox.StandardButton.Cancel
        self.button_box = QDialogButtonBox(buttons)
        self.button_box.accepted.connect(self._accept_selected)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self._populate()
        self._update_button_state()

    def _populate(self) -> None:
        first_enabled_row = -1
        for row, summary in enumerate(self.slots):
            item = QListWidgetItem(self._format_summary(summary))
            item.setData(Qt.ItemDataRole.UserRole, summary.slot_id)
            if self.mode == "load" and not summary.exists:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            elif first_enabled_row < 0:
                first_enabled_row = row
            self.slot_list.addItem(item)
        if first_enabled_row >= 0:
            self.slot_list.setCurrentRow(first_enabled_row)

    def _format_summary(self, summary: SaveSlotSummary) -> str:
        if not summary.exists:
            return f"{summary.label}\n{tr('desktop.menu.save_slot_empty')}"
        saved_at = summary.saved_at.replace("T", " ")
        stats = tr(
            "desktop.menu.save_slot_stats",
            turns=summary.turn_count,
            messages=summary.message_count,
        )
        preview = summary.preview or tr("desktop.menu.save_slot_no_preview")
        return f"{summary.label}  |  {saved_at}\n{stats}\n{preview}"

    def _current_slot_id(self) -> str:
        item = self.slot_list.currentItem()
        if item is None or not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or "")

    def _update_button_state(self) -> None:
        button = self.button_box.button(
            QDialogButtonBox.StandardButton.Open
            if self.mode == "load"
            else QDialogButtonBox.StandardButton.Save
        )
        if button is not None:
            button.setEnabled(bool(self._current_slot_id()))

    def _accept_selected(self) -> None:
        self.selected_slot_id = self._current_slot_id()
        if self.selected_slot_id:
            self.accept()

    def _on_double_clicked(self, item: QListWidgetItem) -> None:
        if item.flags() & Qt.ItemFlag.ItemIsEnabled:
            self._accept_selected()
