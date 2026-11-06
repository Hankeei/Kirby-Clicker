"""Small always-on-top overlay used in compact mode."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core.paths import app_icon_path
from . import theme
from .widgets import RhythmStrip


class CompactOverlay(QWidget):
    arm_requested = Signal()
    method_requested = Signal()
    restore_requested = Signal()
    moved = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Compact")
        self.setWindowFlags(
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_X11DoNotAcceptFocus, True)
        self.setWindowTitle("Kirby Clicker — compact")
        icon_file = app_icon_path()
        if icon_file.exists():
            self.setWindowIcon(QIcon(str(icon_file)))
        self.setStyleSheet(theme.stylesheet())
        self.setFixedSize(188, 104)
        self._drag_offset = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(4)
        self.note = QLabel("♪")
        self.note.setObjectName("Muted")
        self.note.setFixedWidth(12)
        top.addWidget(self.note, 0)
        self.method_button = QPushButton("Random")
        self.method_button.setFixedHeight(18)
        self.method_button.setCursor(Qt.PointingHandCursor)
        self.method_button.setStyleSheet(
            f"QPushButton {{ color:{theme.MUTED}; background:transparent; border:none;"
            "padding:0px; font-size:8pt; font-weight:600; text-align:left; }"
            f"QPushButton:hover {{ color:{theme.INK_2}; }}"
        )
        self.method_button.setToolTip("Cycle the timing method")
        self.method_button.clicked.connect(self.method_requested)
        self.full_button = QPushButton("⤢")
        self.full_button.setObjectName("Icon")
        self.full_button.setFixedSize(24, 20)
        self.full_button.setToolTip("Back to the full window")
        self.full_button.clicked.connect(self.restore_requested)
        top.addWidget(self.method_button, 1)
        top.addWidget(self.full_button, 0)
        root.addLayout(top)

        middle = QHBoxLayout()
        middle.setSpacing(7)
        self.dot = QLabel()
        self.dot.setObjectName("LiveDot")
        self.dot.setFixedSize(10, 10)
        self.state_button = QPushButton("OFF")
        self.state_button.setObjectName("StatePill")
        self.state_button.setFixedHeight(28)
        self.state_button.setToolTip("Toggle ON / OFF")
        self.state_button.clicked.connect(self.arm_requested)
        middle.addWidget(self.dot, 0, Qt.AlignVCenter)
        middle.addWidget(self.state_button, 1)
        root.addLayout(middle)

        self.rhythm = RhythmStrip(width=164, height=24)
        root.addWidget(self.rhythm, 0, Qt.AlignHCenter)
        self.set_state(False, False, "Random", [])

    def set_state(
        self,
        armed: bool,
        clicking: bool,
        method_text: str,
        gaps: list[float],
    ) -> None:
        self.method_button.setText(method_text)
        self.state_button.setText("ON" if armed else "OFF")
        self._set_active(self.state_button, armed)
        self.dot.setStyleSheet(f"background:{self._dot_colour(armed, clicking)}; border-radius:5px;")
        self.rhythm.set_data(gaps)

    @staticmethod
    def _dot_colour(armed: bool, clicking: bool) -> str:
        if clicking:
            return theme.PINK
        if armed:
            return "#7fd6b4"
        return "#cfc9d6"

    @staticmethod
    def _set_active(button: QPushButton, active: bool) -> None:
        button.setProperty("active", active)
        button.style().unpolish(button)
        button.style().polish(button)

    # -- dragging (works despite WS_EX_NOACTIVATE) -----------------------
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            self.moved.emit()
            event.accept()
