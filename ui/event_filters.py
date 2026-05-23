"""Global event filters installed on every QApplication entry point."""

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QComboBox, QSlider


class NoWheelOnComboSlider(QObject):
    """Blocks mouse-wheel events on all QComboBox and QSlider widgets.

    Installing this on the QApplication prevents accidental value changes
    while the user is scrolling through a settings page.
    """

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Wheel and isinstance(
            obj, (QComboBox, QSlider)
        ):
            return True
        return super().eventFilter(obj, event)


def install_no_wheel_filter(app: QApplication) -> None:
    app.installEventFilter(NoWheelOnComboSlider(app))
