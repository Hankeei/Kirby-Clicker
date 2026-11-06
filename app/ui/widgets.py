"""Clay surfaces, the patterned backdrop and the tiny rhythm strip."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.paths import asset_path
from . import theme


class PatternBackdrop(QWidget):
    """Kirby wall-paper behind the whole window, tiled at its natural scale.

    The tile is 1080 px - wider than the clicker ever gets - so resizing
    extends the pattern by repeating it instead of stretching or squashing it,
    and the repeat line stays off screen at every supported window size.
    """

    _tile: QPixmap | None = None

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Root")
        if PatternBackdrop._tile is None:
            pixmap = QPixmap(str(asset_path("pattern.png")))
            PatternBackdrop._tile = pixmap

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        tile = PatternBackdrop._tile
        if tile is not None and not tile.isNull():
            painter.drawTiledPixmap(self.rect(), tile)
            # Quiet wash so the little footer/mascot labels stay readable on
            # top of the pattern without hiding it.
            painter.fillRect(self.rect(), QColor(255, 255, 255, 92))
        else:
            painter.fillRect(self.rect(), QColor(theme.GROUND))
        painter.end()


class Card(QFrame):
    """Large cream reading surface that floats on the pale ground."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(16, 14, 16, 14)
        self._root.setSpacing(10)
        theme.clay_shadow(self, blur=34, dy=10, alpha=42)

    def body(self) -> QVBoxLayout:
        return self._root


class Cushion(QFrame):
    """Pastel pad that groups a few related controls."""

    def __init__(self, tone: str = "mint", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Cushion")
        self.setProperty("tone", tone)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(12, 9, 12, 9)
        self._root.setSpacing(6)
        theme.clay_shadow(self, blur=16, dy=4, alpha=26)

    def body(self) -> QVBoxLayout:
        return self._root


class RhythmStrip(QWidget):
    """Tiny music-box equalizer of recent click gaps - no labels, no axes.

    Bars fade from Kirby's body pink at the top to his foot red at the bottom;
    idle shows only faint dots so it reads as a paused visualiser, not a chart.
    """

    SLOTS = 24

    def __init__(self, parent: QWidget | None = None, width: int = 120, height: int = 24):
        super().__init__(parent)
        self._values: list[float] = []
        self.setFixedSize(width, height)
        self.setToolTip("Recent click rhythm")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def set_data(self, values: list[float]) -> None:
        self._values = [max(0.0, float(v)) for v in values[-self.SLOTS:]]
        self.update()

    def values(self) -> tuple[float, ...]:
        return tuple(self._values)

    def clear(self) -> None:
        if not self._values:
            return
        self._values = []
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.contentsRect()
        if rect.width() < 16 or rect.height() < 8:
            return

        slot = rect.width() / self.SLOTS
        bar_width = max(2.0, slot - 2.2)
        bottom = rect.bottom() - 1

        if not self._values:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#e9e3ee"))
            for index in range(self.SLOTS):
                x = rect.left() + index * slot + (slot - 2.4) / 2
                painter.drawRoundedRect(QRectF(x, bottom - 2.0, 2.4, 2.4), 1.2, 1.2)
            painter.end()
            return

        painter.setPen(Qt.NoPen)

        peak = max(max(self._values), 1.0)
        start = self.SLOTS - len(self._values)
        usable = rect.height() - 2
        for index, value in enumerate(self._values):
            ratio = min(1.0, value / peak)
            height = max(3.0, ratio * usable)
            x = rect.left() + (start + index) * slot + (slot - bar_width) / 2
            top = bottom - height
            # Each bar fades Kirby body pink at its top to foot red at its base.
            gradient = QLinearGradient(0, top, 0, bottom)
            gradient.setColorAt(0.0, QColor(theme.KIRBY_PINK))
            gradient.setColorAt(1.0, QColor(theme.KIRBY_RED))
            painter.setBrush(gradient)
            painter.drawRoundedRect(
                QRectF(x, top, bar_width, height), 1.5, 1.5
            )
        painter.end()


class SegmentedTabs(QWidget):
    """Pill switch plus a stack; a tab widget without native chrome."""

    currentChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._buttons: list[QPushButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._switching = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        bar = QHBoxLayout()
        bar.setContentsMargins(4, 0, 4, 0)
        bar.setSpacing(4)
        bar.setAlignment(Qt.AlignLeft)
        layout.addLayout(bar)
        self._bar = bar
        self._stack = QStackedWidget()
        layout.addWidget(self._stack, 1)

    def addTab(self, widget: QWidget, label: str) -> int:
        index = self._stack.addWidget(widget)
        button = QPushButton(label)
        button.setObjectName("Segment")
        button.setCheckable(True)
        button.setFixedHeight(26)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(lambda _checked, i=index: self.setCurrentIndex(i))
        self._group.addButton(button, index)
        self._bar.addWidget(button)
        self._buttons.append(button)
        return index

    def currentIndex(self) -> int:
        return self._stack.currentIndex()

    def setCurrentIndex(self, index: int) -> None:
        if index < 0 or index >= len(self._buttons):
            return
        if index == self.currentIndex() and self._buttons[index].isChecked():
            return
        self._switching = True
        try:
            self._stack.setCurrentIndex(index)
            self._buttons[index].setChecked(True)
        finally:
            self._switching = False
        self.currentChanged.emit(index)

    def count(self) -> int:
        return len(self._buttons)


def muted(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    label.setWordWrap(True)
    return label


def field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("FieldLabel")
    return label
