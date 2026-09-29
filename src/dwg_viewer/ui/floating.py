from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget


class FloatingToolWindow(QDialog):
    """A non-modal tool window that floats above the main window without
    squeezing the central layout.
    """

    closed = Signal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent, Qt.Tool)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self._layout = layout

    def set_content(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def closeEvent(self, event) -> None:
        super().closeEvent(event)
        self.closed.emit()
