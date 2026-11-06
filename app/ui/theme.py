"""Claymorphism light theme: cream surfaces on a pale ground, pastel cushions.

One light direction everywhere: surfaces are lighter at the top-left, warm
white borders catch the light, and a soft outer shadow drops to the bottom.
Text is flat and crisp - no shadows, no glow.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

GROUND = "#f1f2fa"
INK = "#383139"
INK_2 = "#48404b"
PINK = "#f6a3ca"
CREAM = "#fffdf7"
MINT = "#c0efdc"
LAVENDER = "#ded0f9"
BUTTER = "#f9e7a8"
BLUE = "#c5e5fb"

# Sampled from the Kirby art: body pink (top of the equalizer) and foot red.
KIRBY_PINK = "#d890a0"
KIRBY_RED = "#d83010"

MUTED = "#8b8592"
HAIRLINE = "#e4e1ec"
SHADOW = QColor(56, 49, 57, 40)

_FAMILY_FALLBACKS = ("Instrument Sans", "Segoe UI Variable", "Segoe UI")

_ui_family: str | None = None


def ui_font_family() -> str:
    """Instrument Sans when present, else Segoe UI Variable, else Segoe UI."""
    global _ui_family
    if _ui_family:
        return _ui_family
    try:
        available = {name.lower(): name for name in QFontDatabase.families()}
    except Exception:  # noqa: BLE001 - font discovery must never block startup
        available = {}
    for candidate in _FAMILY_FALLBACKS:
        match = available.get(candidate.lower())
        if match:
            _ui_family = match
            return _ui_family
    _ui_family = "Segoe UI"
    return _ui_family


def ui_font(size: float, weight: QFont.Weight = QFont.Normal, tracking: float | None = None) -> QFont:
    font = QFont(ui_font_family())
    font.setPointSizeF(float(size))
    font.setWeight(weight)
    if tracking is not None:
        font.setLetterSpacing(QFont.PercentageSpacing, tracking)
    return font


def body_font() -> QFont:
    return ui_font(9.5)


def title_font() -> QFont:
    # Bold, tight tracking; the app name is the only large type in the window.
    return ui_font(13.5, QFont.Bold, tracking=96.0)


def panel_title_font() -> QFont:
    return ui_font(8.0, QFont.DemiBold, tracking=104.0)


def heading_font(size: float = 9.0) -> QFont:
    return ui_font(size, QFont.DemiBold, tracking=99.0)


def mono_font(size: float = 9.0) -> QFont:
    font = QFont("Consolas")
    font.setPointSizeF(float(size))
    return font


def clay_shadow(widget: QWidget, blur: int = 30, dy: int = 8, alpha: int = 40) -> QGraphicsDropShadowEffect:
    """Soft outer shadow - the inflated look of a clay surface."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(float(blur))
    effect.setOffset(0.0, float(dy))
    colour = QColor(SHADOW)
    colour.setAlpha(alpha)
    effect.setColor(colour)
    widget.setGraphicsEffect(effect)
    return effect


def palette() -> QPalette:
    """Light palette so native bits (tab bar, dialogs, popups) match the theme."""
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(GROUND))
    pal.setColor(QPalette.WindowText, QColor(INK))
    pal.setColor(QPalette.Base, QColor(CREAM))
    pal.setColor(QPalette.AlternateBase, QColor("#f7f5fb"))
    pal.setColor(QPalette.Text, QColor(INK))
    pal.setColor(QPalette.Button, QColor(CREAM))
    pal.setColor(QPalette.ButtonText, QColor(INK))
    pal.setColor(QPalette.Highlight, QColor(PINK))
    pal.setColor(QPalette.HighlightedText, QColor(INK))
    pal.setColor(QPalette.ToolTipBase, QColor(CREAM))
    pal.setColor(QPalette.ToolTipText, QColor(INK))
    pal.setColor(QPalette.PlaceholderText, QColor(MUTED))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor("#b0aab6"))
    return pal


def stylesheet() -> str:
    family = ui_font_family()
    return f"""
* {{
    outline: none;
}}
QWidget {{
    color: {INK};
    font-family: "{family}";
    font-size: 9.5pt;
}}
QMainWindow, QDialog, QWidget#Root {{
    background: {GROUND};
}}
QLabel {{
    background: transparent;
}}
QLabel#Wordmark {{
    color: {INK};
    font-size: 13.5pt;
    font-weight: 700;
}}
QLabel#Muted {{
    color: {MUTED};
    font-size: 8.5pt;
}}
QLabel#Signature {{
    color: {MUTED};
    font-size: 8pt;
    font-style: italic;
}}
QPushButton#LinkButton {{
    color: {MUTED};
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 0px 2px;
    font-size: 8pt;
    font-style: italic;
    font-weight: 400;
    text-decoration: underline;
    text-align: center;
}}
QPushButton#LinkButton:hover {{
    color: #b86d94;
    background: transparent;
    border-color: transparent;
    padding: 0px 2px;
}}
QPushButton#LinkButton:pressed {{
    color: #9c5479;
    background: transparent;
    border-color: transparent;
    padding: 0px 2px;
}}
QPushButton#LinkButton:focus {{
    color: #b86d94;
    border: 2px solid {INK_2};
}}
QLabel#FieldLabel {{
    color: {INK_2};
    font-size: 8.5pt;
    font-weight: 600;
}}
QLabel#LiveDot {{
    background: #cfc9d6;
    border-radius: 5px;
}}
QFrame#Card {{
    background: {CREAM};
    border: 1px solid #f4e2ea;
    border-radius: 22px;
}}
QFrame#Cushion {{
    background: {CREAM};
    border: 1px solid #ffffff;
    border-radius: 16px;
}}
QFrame#Cushion[tone="mint"] {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #d6f8e9, stop:1 {MINT});
}}
QFrame#Cushion[tone="lavender"] {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #e9e0fb, stop:1 {LAVENDER});
}}
QFrame#Cushion[tone="butter"] {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fdf1c4, stop:1 {BUTTER});
}}
QFrame#Cushion[tone="blue"] {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #d9eefd, stop:1 {BLUE});
}}
QPushButton {{
    color: {INK};
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #fffffb, stop:0.55 {CREAM}, stop:1 #f4f0e7);
    border: 1px solid #ffffff;
    border-radius: 14px;
    padding: 5px 14px;
    font-weight: 600;
    font-size: 9pt;
}}
QPushButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #ffffff, stop:0.55 #fffefb, stop:1 #f7f4ec);
    padding-top: 4px;
    padding-bottom: 6px;
}}
QPushButton:pressed {{
    background: #ebe6db;
    border-color: #f5f1e8;
    padding-top: 6px;
    padding-bottom: 4px;
}}
QPushButton:disabled {{
    color: #b0aab6;
    background: #f7f5ef;
    border-color: #fbf9f3;
}}
QPushButton:focus {{
    border: 3px solid #48404b;
}}
QPushButton#Primary {{
    color: #47203a;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #fbbeda, stop:0.5 {PINK}, stop:1 #ec93c0);
    border: 1px solid #ffe6f1;
    border-radius: 18px;
    padding: 7px 18px;
    font-weight: 700;
    font-size: 10pt;
}}
QPushButton#Primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #fdcbe1, stop:0.5 #f8b1d3, stop:1 #ef9ec7);
    padding-top: 6px;
    padding-bottom: 8px;
}}
QPushButton#Primary:pressed {{
    background: #e785b5;
    padding-top: 8px;
    padding-bottom: 6px;
}}
QPushButton#Primary:disabled {{
    color: #a89ba5;
    background: #f5e7ee;
    border-color: #fbf1f6;
}}
QPushButton#StatePill {{
    border-radius: 15px;
    padding: 4px 12px;
    font-weight: 700;
    min-width: 34px;
}}
QPushButton#StatePill[active="true"] {{
    color: #47203a;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #fbbeda, stop:1 #ee96c2);
    border: 1px solid #ffe6f1;
}}
QPushButton#Icon {{
    border-radius: 15px;
    padding: 0px;
    font-size: 11pt;
    font-weight: 400;
}}
QComboBox, QDoubleSpinBox {{
    color: {INK};
    background: {CREAM};
    border: 1px solid #ffffff;
    border-radius: 15px;
    padding: 4px 12px;
    min-height: 20px;
    selection-background-color: {PINK};
    selection-color: {INK};
}}
QComboBox:hover, QDoubleSpinBox:hover {{
    background: #fffefa;
}}
QComboBox:focus, QDoubleSpinBox:focus {{
    border: 2px solid #48404b;
}}
QComboBox::drop-down {{
    border: none;
    width: 18px;
}}
QComboBox::down-arrow {{
    width: 8px;
    height: 8px;
}}
QComboBox QAbstractItemView {{
    background: {CREAM};
    color: {INK};
    border: 1px solid {HAIRLINE};
    border-radius: 12px;
    padding: 4px;
    outline: none;
    selection-background-color: #f9d3e7;
    selection-color: {INK};
}}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 0px;
    border: none;
}}
QCheckBox {{
    color: {INK_2};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid #ded9e8;
    border-radius: 5px;
    background: {CREAM};
}}
QCheckBox::indicator:checked {{
    background: {PINK};
    border-color: #eb93c0;
}}
QRadioButton {{
    color: {INK_2};
    spacing: 7px;
}}
QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid #ded9e8;
    border-radius: 7px;
    background: {CREAM};
}}
QRadioButton::indicator:checked {{
    background: {PINK};
    border-color: #eb93c0;
}}
QRadioButton::indicator:disabled {{
    background: #f5f3ee;
    border-color: #ebe7f1;
}}
QPushButton#Segment {{
    color: {MUTED};
    background: transparent;
    border: 1px solid transparent;
    border-radius: 13px;
    padding: 4px 16px;
    font-weight: 600;
    font-size: 8.5pt;
}}
QPushButton#Segment:hover:!checked {{
    color: {INK_2};
    background: #e9e8f4;
    padding: 4px 16px;
}}
QPushButton#Segment:checked {{
    color: {INK};
    background: {CREAM};
    border: 1px solid #ffffff;
}}
QPushButton#Segment:pressed {{
    background: #ece9f5;
    padding: 4px 16px;
}}
QPushButton#Segment:focus {{
    border: 3px solid #48404b;
}}
QSlider::groove:horizontal {{
    height: 8px;
    background: #e6e3f0;
    border-radius: 4px;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {BLUE}, stop:1 {PINK});
    border-radius: 4px;
}}
QSlider::handle:horizontal {{
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 9px;
    background-color: #f8b1d3;
    border: 1px solid #ffffff;
}}
QSlider::handle:horizontal:hover {{
    background: #f8a9cf;
}}
QSlider::handle:horizontal:disabled {{
    background: #e7e2ec;
    border-color: #f4f1f6;
}}
QSlider::groove:horizontal:disabled {{
    background: #efedf5;
}}
QWidget#Compact {{
    background: {CREAM};
    border: 1px solid #ffffff;
    border-radius: 20px;
}}
QListWidget, QTextEdit, QTableWidget {{
    background: {CREAM};
    color: {INK};
    border: 1px solid #ffffff;
    border-radius: 16px;
    padding: 4px;
}}
QListWidget::item {{
    border-radius: 10px;
    padding: 5px 6px;
}}
QListWidget::item:selected {{
    background: #f9d3e7;
    color: {INK};
}}
QTableWidget {{
    gridline-color: {HAIRLINE};
    selection-background-color: #f9d3e7;
    selection-color: {INK};
}}
QHeaderView::section {{
    background: transparent;
    color: {MUTED};
    border: none;
    border-bottom: 1px solid {HAIRLINE};
    padding: 5px;
    font-weight: 600;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #dcd7e8;
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: #c9c2d8;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: #dcd7e8;
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
QToolTip {{
    background: {CREAM};
    color: {INK};
    border: 1px solid {HAIRLINE};
    border-radius: 8px;
    padding: 5px 8px;
}}
QMessageBox {{
    background: {GROUND};
}}
QDialogButtonBox QPushButton {{
    min-width: 76px;
}}
"""
