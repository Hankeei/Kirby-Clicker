"""Kirby Clicker main window - a compact clay-styled control surface.

Only primary controls live here: the mascot, ON/OFF state pill, record, the
profile picker, timing method and CPS bounds, plus one tiny equalizer strip.
Logs, counters, CPS readouts and the old side panels are gone; everything
secondary (backend, scope, binds, music, files) is in the settings dialog.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QMovie, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..core.autoclicker import (
    AutoClickerSession,
    MAX_CPS,
    METHOD_DESCRIPTIONS,
    METHOD_GAUSSIAN,
    METHOD_GAUSSIAN_POISSON,
    METHOD_LABELS,
    METHOD_SHORT_LABELS,
    METHOD_STATIC,
    METHODS,
    MIN_CPS,
    clamp_sigma,
    normalise_method,
    sync_bounds,
    validate_cps,
)
from ..core.backends import BACKENDS, create_backend
from ..core.binds import BindError, BindSet, ensure_bind_file, save_binds
from ..core.hotkeys import HotkeyManager
from ..core.player import PlaybackSession, PlaybackSnapshot
from ..core.paths import app_icon_path, asset_path
from ..core.profile import (
    ClickProfile,
    ProfileFormatError,
    load_profile,
    next_recording_path,
    rename_profile_file,
    save_profile,
)
from ..core.recorder import MouseHookThread, RecorderEngine
from ..core.settings import load_settings, save_settings
from ..core.transfer import FILE_SUFFIX, export_profile, import_profile_file
from ..core.trigger import ArmState, MouseButtonMonitor, button_label, resolve_trigger_kind
from ..core.win32 import is_window
from ..core.windows import Target, WindowInfo, enumerate_visible_windows, find_window_by_exe
from . import theme
from .compact import CompactOverlay
from .dialogs import BindEditorDialog, ProcessPickerDialog, SettingsDialog
from .music import MusicPlayer, ToggleSounds
from .widgets import (
    Card,
    Cushion,
    PatternBackdrop,
    RhythmStrip,
    SegmentedTabs,
    field_label,
    muted,
)

COMPACT_W, COMPACT_H = 560, 437
COMPACT_MIN_W, COMPACT_MIN_H = 440, 250
MASCOT_HEIGHT = 48
# Kirby bites the Record pill: sprite height, how far left of the pill he
# starts, and how much of the sprite sits above the pill's top edge so the
# mouth's lower lip lands exactly on it.
BITE_HEIGHT = 76
BITE_X_SHIFT = 0.62
BITE_LIP_RATIO = 0.32
# Breathing room between the cream cards and the patterned window edge.
GUTTER_LEFT = 24
GUTTER_RIGHT = 24


class MainWindow(QMainWindow):
    def __init__(self, base_dir: Path | None = None):
        super().__init__()
        self.base_dir = Path(base_dir or Path(__file__).resolve().parents[2])
        self.profiles_dir = self.base_dir / "profiles"
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self.binds_path = self.base_dir / "binds.txt"
        self.settings_path = self.base_dir / "settings.json"
        self.settings = load_settings(self.settings_path)
        self.own_pid = os.getpid()

        self.mode = "setup"  # setup | recording | armed
        self.profile: ClickProfile | None = None
        self.target = Target.any_target()
        self.windows: list[WindowInfo] = []
        self.backend_name = self.settings.click_backend
        self.record_button_name = "left"
        self.dry_run = False
        # One master arm flag; clicks fire only while the mouse trigger is held.
        self.arm = ArmState()

        self.recorder: RecorderEngine | None = None
        self.hook: MouseHookThread | None = None
        self.player: PlaybackSession | None = None
        self.hotkeys: HotkeyManager | None = None
        self.trigger_monitor: MouseButtonMonitor | None = None
        self.auto_session: AutoClickerSession | None = None
        self._trigger_session = None  # PlaybackSession or AutoClickerSession
        self.compact_overlay: CompactOverlay | None = None
        self._compact = False
        self._full_geometry = None
        self._auto_loaded = False
        self._syncing_auto = False
        self.blocked_hotkeys: set[str] = set()
        self.fallback_hotkeys: dict[str, str] = {}
        self._startup_errors: list[str] = []
        self._loading_profile = False
        self._messages: list[str] = []
        self.toggle_sounds = ToggleSounds(self)
        self.music = MusicPlayer(asset_path("luolei.mp3"), self)
        self.music.set_volume(self.settings.music_volume)

        try:
            self.binds = ensure_bind_file(self.binds_path)
        except Exception as exc:  # noqa: BLE001
            self.binds = BindSet(path=self.binds_path)
            self._startup_errors.append(f"Could not read binds: {exc}")

        self.setWindowTitle("Kirby Clicker")
        icon_file = app_icon_path()
        if icon_file.exists():
            self.setWindowIcon(QIcon(str(icon_file)))
        self.resize(COMPACT_W, COMPACT_H)
        self.setMinimumSize(COMPACT_MIN_W, COMPACT_MIN_H)
        geometry = self.settings.window_geometry
        if geometry and 320 <= geometry[2] <= 760 and 240 <= geometry[3] <= 560:
            self.setGeometry(*geometry)
        self.setStyleSheet(theme.stylesheet())
        self._build_ui()
        self._initialise()

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ================================================================= UI ==
    def _build_ui(self) -> None:
        root = PatternBackdrop()
        self._root = root
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(GUTTER_LEFT, 12, GUTTER_RIGHT, 10)
        layout.setSpacing(6)

        header = QWidget()
        header.setFixedHeight(52)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(2, 0, 4, 0)
        header_layout.setSpacing(6)

        # The mascot stands where the wordmark used to be.  It is purely
        # decorative, so it must never take mouse events from the user.
        self.mascot = QLabel()
        self.mascot.setObjectName("Mascot")
        self.mascot.setFixedSize(90, 52)
        self.mascot.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.mascot.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.mascot.setToolTip("Kirby Clicker")
        self._mascot_cache: dict[str, QPixmap] = {}
        header_layout.addWidget(self.mascot)
        header_layout.addStretch(1)

        self.cat_label = QLabel()
        self.cat_label.setObjectName("Cat")
        self.cat_label.setFixedSize(36, 36)
        self.cat_label.setAlignment(Qt.AlignCenter)
        self.cat_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.cat_label.setToolTip("Dancing cat — dances while the clicker is ON")
        self.cat_movie = QMovie(str(asset_path("cat.gif")))
        if self.cat_movie.isValid():
            self.cat_movie.setScaledSize(QSize(34, 34))
            self.cat_label.setMovie(self.cat_movie)
            self.cat_movie.jumpToFrame(0)
        else:
            self.cat_label.hide()
        header_layout.addWidget(self.cat_label, 0, Qt.AlignVCenter)

        self.live_dot = QLabel()
        self.live_dot.setObjectName("LiveDot")
        self.live_dot.setFixedSize(10, 10)
        header_layout.addWidget(self.live_dot, 0, Qt.AlignVCenter)

        self.arm_button = QPushButton("OFF")
        self.arm_button.setObjectName("StatePill")
        self.arm_button.setFixedHeight(30)
        self.arm_button.setMinimumWidth(62)
        self.arm_button.setCursor(Qt.PointingHandCursor)
        self.arm_button.setAccessibleName("Power")
        self.arm_button.clicked.connect(self._toggle_arm)
        header_layout.addWidget(self.arm_button)

        self.settings_button = QPushButton("⚙")
        self.settings_button.setObjectName("Icon")
        self.settings_button.setFixedSize(30, 30)
        self.settings_button.setCursor(Qt.PointingHandCursor)
        self.settings_button.setAccessibleName("Settings")
        self.settings_button.setToolTip("Settings · backend, scope, binds, files")
        self.settings_button.clicked.connect(self._open_settings)
        header_layout.addWidget(self.settings_button)

        self.compact_button = QPushButton("⤢")
        self.compact_button.setObjectName("Icon")
        self.compact_button.setFixedSize(30, 30)
        self.compact_button.setCursor(Qt.PointingHandCursor)
        self.compact_button.setAccessibleName("Compact")
        self.compact_button.setToolTip("Compact overlay")
        self.compact_button.clicked.connect(self._enter_compact)
        header_layout.addWidget(self.compact_button)
        layout.addWidget(header)

        self.tabs = SegmentedTabs()
        self._scrolls: list[QScrollArea] = []
        self.tabs.addTab(self._scrollable(self._build_recorder_tab()), "Recorder")
        self.tabs.addTab(self._scrollable(self._build_auto_tab()), "Auto")
        self.tabs.setCurrentIndex(1 if self.settings.active_tab else 0)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(4, 0, 4, 0)
        footer.setSpacing(10)
        self.notice = muted("")
        self.notice.setWordWrap(False)
        # Long hints must never widen the window's minimum size.
        self.notice.setMinimumWidth(1)
        footer.addWidget(self.notice, 1)
        self.rhythm = RhythmStrip(height=24)
        footer.addWidget(self.rhythm, 0, Qt.AlignRight | Qt.AlignVCenter)
        layout.addLayout(footer)

        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.timeout.connect(lambda: self.notice.setText(""))

        # Secondary options live in a modal dialog; its widgets are owned by
        # the window so the existing handlers and enablement logic still apply.
        self.settings_dialog = SettingsDialog(self)

    def _scrollable(self, page: QWidget) -> QWidget:
        """Wrap a tab page so a very small window scrolls instead of clipping."""
        scroll = QScrollArea()
        scroll.setWidget(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }"
            "QScrollBar:vertical { background: transparent; width: 6px; margin: 2px 0; }"
            "QScrollBar::handle:vertical { background: #e6d2dc; border-radius: 3px;"
            " min-height: 24px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {"
            " background: transparent; }"
        )
        scroll.viewport().setAutoFillBackground(False)
        self._scrolls.append(scroll)
        return scroll

    def _build_recorder_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 10, 0, 10)
        outer.setSpacing(10)

        card = Card()
        self._recorder_card = card
        card.body().addStretch(1)
        cushion = Cushion("mint")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.record_button = QPushButton("●  Record  F8")
        self.record_button.setObjectName("Primary")
        self.record_button.setMinimumHeight(40)
        self.record_button.setMinimumWidth(136)
        self.record_button.setCursor(Qt.PointingHandCursor)
        self.record_button.clicked.connect(self._toggle_recording)
        row.addWidget(self.record_button)
        row.addStretch(1)

        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(96)
        self.profile_combo.setFixedHeight(34)
        self.profile_combo.setToolTip("Saved profiles")
        self.profile_combo.currentIndexChanged.connect(lambda _i: self._update_controls())
        row.addWidget(self.profile_combo)

        self.profile_load_button = QPushButton("Load")
        self.profile_load_button.setFixedHeight(34)
        self.profile_load_button.setCursor(Qt.PointingHandCursor)
        self.profile_load_button.setToolTip("Load the picked profile")
        self.profile_load_button.clicked.connect(self._load_selected_profile)
        row.addWidget(self.profile_load_button)
        cushion.body().addLayout(row)
        card.body().addWidget(cushion)
        card.body().addStretch(1)
        outer.addWidget(card, 1)

        # Profile housekeeping lives in its own card so the Record card above
        # only contains recording controls.
        tools = Card()
        self._profile_tools_card = tools
        tools_header = QHBoxLayout()
        tools_header.setSpacing(8)
        tools_title = QLabel("PROFILES")
        tools_title.setObjectName("PanelTitle")
        tools_title.setFont(theme.panel_title_font())
        tools_title.setStyleSheet(f"color: {theme.MUTED};")
        tools_header.addWidget(tools_title)
        tools_rule = QFrame()
        tools_rule.setObjectName("TitleRule")
        tools_rule.setFixedHeight(1)
        tools_rule.setStyleSheet(f"background: {theme.HAIRLINE}; border: none;")
        tools_header.addWidget(tools_rule, 1)
        tools.body().addLayout(tools_header)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.profile_rename_button = QPushButton("Rename")
        self.profile_rename_button.setFixedHeight(30)
        self.profile_rename_button.setCursor(Qt.PointingHandCursor)
        self.profile_rename_button.setToolTip("Rename the picked profile")
        self.profile_rename_button.clicked.connect(lambda: self._rename_profile())
        actions.addWidget(self.profile_rename_button)
        self.profile_folder_button = QPushButton("Open folder")
        self.profile_folder_button.setFixedHeight(30)
        self.profile_folder_button.setCursor(Qt.PointingHandCursor)
        self.profile_folder_button.setToolTip("Open the profiles folder in Explorer")
        self.profile_folder_button.clicked.connect(self._open_profiles_folder)
        actions.addWidget(self.profile_folder_button)
        actions.addStretch(1)
        tools.body().addLayout(actions)
        outer.addWidget(tools)

        self._recorder_page = page
        # Kirby hangs over the Record pill, so the sprite lives on the window
        # backdrop instead of inside the (clipping) tab page.
        self.bite_label = QLabel(self._root)
        self.bite_label.setObjectName("Bite")
        self.bite_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        bite_pixmap = QPixmap(str(asset_path("mascot_bite.png")))
        if bite_pixmap.isNull():
            self.bite_label.hide()
        else:
            self._bite_pixmap = bite_pixmap.scaledToHeight(BITE_HEIGHT, Qt.SmoothTransformation)
            self.bite_label.setPixmap(self._bite_pixmap)
            self.bite_label.setFixedSize(self._bite_pixmap.size())
            self.bite_label.setToolTip("Kirby is chomping the Record button")
            self.bite_label.raise_()
        return page

    def _place_bite(self) -> None:
        bite = getattr(self, "bite_label", None)
        if bite is None or bite.pixmap().isNull():
            return
        if self.tabs.currentIndex() != 0 or self._compact:
            bite.hide()
            return
        # Anchor to the Record pill, not the card: the mouth's lower lip rests
        # on the pill's top edge (it never dips through the button) and the
        # pill's left end sits inside the open mouth, so Kirby reads as
        # chomping down on the button.
        pill_pos = self.record_button.mapTo(self._root, QPoint(0, 0))
        x = pill_pos.x() - round(bite.width() * BITE_X_SHIFT)
        y = pill_pos.y() - round(bite.height() * BITE_LIP_RATIO)
        bite.move(max(0, x), y)
        bite.show()
        bite.raise_()

    def _build_auto_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 10, 0, 0)
        outer.setSpacing(8)

        card = Card()

        method_row = QHBoxLayout()
        method_row.setSpacing(8)
        self.auto_method_combo = QComboBox()
        self.auto_method_combo.setFixedHeight(34)
        for key in METHODS:
            self.auto_method_combo.addItem(METHOD_LABELS[key], key)
        self.auto_method_combo.setCurrentIndex(
            max(0, self.auto_method_combo.findData(normalise_method(self.settings.auto_method)))
        )
        self.auto_method_combo.setToolTip(
            METHOD_DESCRIPTIONS[normalise_method(self.settings.auto_method)]
        )
        method_row.addWidget(self.auto_method_combo, 1)

        self.auto_sigma_spin = QDoubleSpinBox()
        self.auto_sigma_spin.setRange(5.0, 40.0)
        self.auto_sigma_spin.setDecimals(1)
        self.auto_sigma_spin.setSingleStep(1.0)
        self.auto_sigma_spin.setSuffix(" %")
        self.auto_sigma_spin.setFixedWidth(78)
        self.auto_sigma_spin.setFixedHeight(34)
        self.auto_sigma_spin.setValue(clamp_sigma(self.settings.auto_sigma) * 100.0)
        self.auto_sigma_spin.setToolTip("Spread around the CPS bounds")
        self.auto_sigma_label = field_label("σ")
        self.auto_sigma_label.setToolTip("Sigma")
        method_row.addWidget(self.auto_sigma_label)
        method_row.addWidget(self.auto_sigma_spin)
        method_cushion = Cushion("mint")
        method_cushion.body().addLayout(method_row)
        card.body().addWidget(method_cushion)

        self.auto_min_spin = QDoubleSpinBox()
        self.auto_min_spin.setRange(1.0, 50.0)
        self.auto_min_spin.setDecimals(1)
        self.auto_min_spin.setSingleStep(0.5)
        self.auto_min_spin.setSuffix(" CPS")
        self.auto_min_spin.setValue(self.settings.auto_min_cps)
        self.auto_min_spin.setFixedWidth(86)
        self.auto_min_spin.setFixedHeight(32)
        self.auto_max_spin = QDoubleSpinBox()
        self.auto_max_spin.setRange(1.0, 50.0)
        self.auto_max_spin.setDecimals(1)
        self.auto_max_spin.setSingleStep(0.5)
        self.auto_max_spin.setSuffix(" CPS")
        self.auto_max_spin.setValue(self.settings.auto_max_cps)
        self.auto_max_spin.setFixedWidth(86)
        self.auto_max_spin.setFixedHeight(32)

        # Sliders cover the practical 1-30 CPS band; the spin boxes can still
        # be typed up to the engine limit of 50 CPS.
        self.auto_min_slider = QSlider(Qt.Horizontal)
        self.auto_min_slider.setRange(10, 300)
        self.auto_min_slider.setSingleStep(5)
        self.auto_min_slider.setPageStep(20)
        self.auto_min_slider.setValue(int(round(self.settings.auto_min_cps * 10)))
        self.auto_min_slider.setToolTip("Low bound")
        self.auto_max_slider = QSlider(Qt.Horizontal)
        self.auto_max_slider.setRange(10, 300)
        self.auto_max_slider.setSingleStep(5)
        self.auto_max_slider.setPageStep(20)
        self.auto_max_slider.setValue(int(round(self.settings.auto_max_cps * 10)))
        self.auto_max_slider.setToolTip("High bound")

        low_row = QHBoxLayout()
        low_row.setSpacing(8)
        low_label = field_label("Low")
        low_label.setFixedWidth(34)
        low_row.addWidget(low_label)
        low_row.addWidget(self.auto_min_slider, 1)
        low_row.addWidget(self.auto_min_spin)
        low_cushion = Cushion("butter")
        low_cushion.body().addLayout(low_row)
        card.body().addWidget(low_cushion)

        high_row = QHBoxLayout()
        high_row.setSpacing(8)
        high_label = field_label("High")
        high_label.setFixedWidth(34)
        high_row.addWidget(high_label)
        high_row.addWidget(self.auto_max_slider, 1)
        high_row.addWidget(self.auto_max_spin)
        high_cushion = Cushion("lavender")
        high_cushion.body().addLayout(high_row)
        card.body().addWidget(high_cushion)

        card.body().addStretch(1)
        outer.addWidget(card, 1)

        self.auto_min_spin.valueChanged.connect(lambda _v: self._on_auto_spin("low"))
        self.auto_max_spin.valueChanged.connect(lambda _v: self._on_auto_spin("high"))
        self.auto_min_slider.valueChanged.connect(lambda _v: self._on_auto_slider("low"))
        self.auto_max_slider.valueChanged.connect(lambda _v: self._on_auto_slider("high"))
        self.auto_method_combo.currentIndexChanged.connect(self._on_auto_method_changed)
        self.auto_sigma_spin.valueChanged.connect(self._on_auto_sigma_changed)
        return page

    # ============================================================ startup ==
    def _initialise(self) -> None:
        self._set_mode("setup")
        self._update_scope_ui()
        self._update_arm_ui()
        self._refresh_targets(preferred=None, announce=False)
        restricted = self.binds.scope == "restricted"
        if restricted:
            if self.binds.target_exe:
                match = find_window_by_exe(self.windows, self.binds.target_exe)
                if match:
                    self._refresh_targets(preferred=Target.from_window(match), announce=False)
                else:
                    self._append_log(
                        "warn",
                        f"Bound app {self.binds.target_exe} is not running — pick a target.",
                    )
            else:
                self._append_log("warn", f"Pick an app for {self.binds.target_exe or 'Selected app'} scope.")
        self._refresh_profiles()

        for error in self._startup_errors:
            self._append_log("error", error)

        self._load_newest_profile()
        self._start_hotkeys()
        self._restart_trigger_monitor()
        self._auto_loaded = True
        self._tie_static_bounds()
        self._update_auto_labels()
        self._update_controls()
        if self.settings.compact_enabled:
            QTimer.singleShot(0, self._startup_compact)

    def _startup_compact(self) -> None:
        if self.settings.compact_enabled:
            self._enter_compact()

    def log_migration(self, old_dir: Path, new_dir: Path) -> None:
        self._append_log("accent", f"Data copied from {old_dir} to {new_dir}.")

    def _start_hotkeys(self) -> None:
        if self.hotkeys:
            self.hotkeys.stop()
        # The mouse trigger is served by the WH_MOUSE_LL monitor, not RegisterHotKey.
        self.hotkeys = HotkeyManager(self.binds)
        self.hotkeys.triggered.connect(self._on_hotkey)
        self.hotkeys.log.connect(self._append_log)
        self.hotkeys.registration.connect(self._on_hotkey_registration)
        self.hotkeys.start()
        self.hotkeys.wait_ready()

    def _restart_hotkeys(self) -> None:
        if self.hotkeys:
            self.hotkeys.stop()
            self.hotkeys = None
        self._start_hotkeys()

    def _restart_trigger_monitor(self) -> None:
        if self.trigger_monitor:
            self.trigger_monitor.stop()
            self.trigger_monitor = None
        monitor = MouseButtonMonitor(self.binds.trigger, self.own_pid, self)
        monitor.pressed.connect(self._on_trigger_pressed)
        monitor.released.connect(self._on_trigger_released)
        monitor.hook_error.connect(self._on_trigger_hook_error)
        monitor.start()
        monitor.wait_ready()
        self.trigger_monitor = monitor

    def _on_trigger_hook_error(self, message: str) -> None:
        self._append_log("error", f"Mouse trigger {self.binds.trigger} unavailable: {message}")

    # ============================================================= trigger ==
    def _on_trigger_pressed(self) -> None:
        kind = resolve_trigger_kind(
            armed=self.arm.armed,
            recording=self.mode == "recording",
            busy=self._trigger_session is not None,
            tab_index=self.tabs.currentIndex(),
        )
        if kind is None:
            return
        if kind == "auto":
            self._start_autoclicker(triggered=True)
            if self.auto_session is not None:
                self._trigger_session = self.auto_session
                self.arm.clicking = True
        else:
            if not self.profile or not self.profile.clicks:
                self._append_log("warn", "No profile loaded — record or pick one first.")
                return
            self._start_playback(dry_run=self.dry_run, triggered=True)
            if self.player is not None:
                self._trigger_session = self.player
                self.arm.clicking = True
        self._update_arm_ui()
        self._update_compact_state()

    def _on_trigger_released(self) -> None:
        self.arm.clicking = False
        self._stop_trigger_session(sync=True)
        self._update_arm_ui()
        self._update_compact_state()

    def _stop_trigger_session(self, sync: bool = True) -> None:
        session, self._trigger_session = self._trigger_session, None
        self.arm.clicking = False
        if session is None:
            return
        if session is self.auto_session:
            self._stop_autoclicker(sync=sync)
        elif session is self.player:
            self._stop_playback(sync=sync)

    def _toggle_arm(self) -> None:
        if self.mode == "recording":
            self._append_log("warn", f"Stop recording with {self.binds.record} before turning ON.")
            return
        if self.arm.armed:
            self._disarm_and_stop(sync=False)
            self._append_log("accent", f"OFF — hold {button_label(self.binds.trigger)} does nothing.")
        else:
            self.arm.armed = True
            self._append_log(
                "accent",
                f"ON — hold {button_label(self.binds.trigger)} to click, release to stop.",
            )
            if not self._auto_tab_active() and not (self.profile and self.profile.clicks):
                self._append_log("warn", "No profile loaded yet.")
        self.toggle_sounds.play(self.arm.armed)
        self._update_arm_ui()
        self._set_mode(self.mode)
        self._update_compact_state()

    def _disarm_and_stop(self, sync: bool = True) -> None:
        self._stop_trigger_session(sync=sync)
        if self.mode == "recording":
            self._stop_recording()
        self.arm.disarm()
        self._update_arm_ui()
        self._set_mode(self.mode)
        self._update_compact_state()

    def _update_arm_ui(self) -> None:
        on = self.arm.armed
        self.arm_button.setText("ON" if on else "OFF")
        self.arm_button.setProperty("active", on)
        self.arm_button.style().unpolish(self.arm_button)
        self.arm_button.style().polish(self.arm_button)
        self.arm_button.setToolTip(
            f"{self.binds.toggle} toggles the clicker · hold {button_label(self.binds.trigger)}"
        )
        self._update_dot()
        self._style_record_button(self.mode == "recording")
        self._update_mascot()
        self._update_cat()
        self._sync_music()

    def _update_dot(self) -> None:
        if self.arm.armed and self.arm.clicking:
            colour, tip = theme.PINK, "Clicking"
        elif self.arm.armed:
            colour, tip = "#7fd6b4", "On"
        else:
            colour, tip = "#cfc9d6", "Off"
        self.live_dot.setStyleSheet(f"background:{colour}; border-radius:5px;")
        self.live_dot.setToolTip(tip)

    def _state_word(self) -> str:
        return "ON" if self.arm.armed else "OFF"

    def state_text(self) -> str:
        """ON/OFF state word, also used by the verification scripts."""
        return self._state_word()

    # ============================================================== mascot ==
    def _mascot_file(self) -> str:
        if self.arm.armed:
            return "mascot_eat.png"
        return "mascot_pikachu.png" if self.tabs.currentIndex() == 1 else "mascot_kirby.png"

    def _update_mascot(self) -> None:
        name = self._mascot_file()
        pixmap = self._mascot_cache.get(name)
        if pixmap is None:
            source = QPixmap(str(asset_path(name)))
            if source.isNull():
                return
            pixmap = source.scaledToHeight(MASCOT_HEIGHT, Qt.SmoothTransformation)
            self._mascot_cache[name] = pixmap
        self.mascot.setPixmap(pixmap)

    def _update_cat(self) -> None:
        if not self.cat_movie.isValid():
            return
        if self.arm.armed:
            if self.cat_movie.state() != QMovie.Running:
                self.cat_movie.start()
        else:
            if self.cat_movie.state() != QMovie.NotRunning:
                self.cat_movie.stop()
            self.cat_movie.jumpToFrame(0)

    def _sync_music(self) -> None:
        if not hasattr(self, "music"):
            return
        self.music.set_volume(self.settings.music_volume)
        # Background music: loops while enabled, independent of ON/OFF.
        self.music.set_playing(self.settings.music_enabled)

    def _on_music_toggled(self, enabled: bool) -> None:
        self.settings.music_enabled = bool(enabled)
        save_settings(self.settings_path, self.settings)
        self._sync_music()

    def _on_music_volume_changed(self, value: int) -> None:
        self.settings.music_volume = max(0.0, min(1.0, float(value) / 100.0))
        save_settings(self.settings_path, self.settings)
        label = getattr(self, "music_value", None)
        if label is not None:
            label.setText(f"{int(value)}%")
        self._sync_music()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._place_bite)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._place_bite)


    # ============================================================= profiles ==
    def _load_newest_profile(self) -> None:
        files = sorted(self.profiles_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return
        self._load_profile_path(files[0], announce=True)

    def _load_profile_path(self, path: Path, announce: bool = True) -> bool:
        self._loading_profile = True
        try:
            profile = load_profile(path)
        except ProfileFormatError as exc:
            self._append_log("error", f"Could not load {path.name}: {exc}")
            self._loading_profile = False
            return False
        self._loading_profile = False
        self._set_profile(profile)
        if announce:
            stats = profile.stats
            self._append_log(
                "accent",
                f"Loaded {path.name} — {stats.clicks} clicks @ {stats.avg_cps:.2f} CPS",
            )
        if profile.meta.get("clicks_mismatch"):
            self._append_log("warn", f"{path.name}: {profile.meta['clicks_mismatch']}")
        self._refresh_profiles(select_path=path)
        return True

    def _set_profile(self, profile: ClickProfile) -> None:
        self.profile = profile
        self._update_controls()

    def _refresh_profiles(self, select_path: Path | None = None) -> None:
        current = select_path
        if current is None and self.profile and self.profile.path:
            current = self.profile.path
        if current is None:
            current = self._selected_profile_path()

        files = sorted(self.profiles_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        match_index = -1
        for index, path in enumerate(files):
            self.profile_combo.addItem(path.stem, str(path))
            self.profile_combo.setItemData(index, str(path), Qt.ToolTipRole)
            if current is not None and path.resolve() == current.resolve():
                match_index = index
        if files:
            self.profile_combo.setCurrentIndex(max(0, match_index))
        else:
            self.profile_combo.addItem("No profiles", None)
        self.profile_combo.blockSignals(False)
        self._update_controls()

    def _selected_profile_path(self) -> Path | None:
        stored = self.profile_combo.currentData()
        return Path(stored) if stored else None

    def _load_selected_profile(self, *_args) -> None:
        if self.mode != "setup":
            return
        path = self._selected_profile_path()
        if not path:
            if self.profile:
                return
            self._append_log("warn", "No profile to load — record one first.")
            return
        if self.profile and self.profile.path and path.resolve() == self.profile.path.resolve():
            return
        self._load_profile_path(path, announce=True)

    def _rename_profile(self, new_name: str | None = None) -> None:
        if self.mode != "setup":
            return
        path = self._selected_profile_path()
        if path is None:
            self._append_log("warn", "No profile to rename — record one first.")
            return
        if new_name is None:
            new_name, accepted = QInputDialog.getText(
                self, "Rename profile", "New name:", text=path.stem
            )
            if not accepted:
                return
        try:
            target = rename_profile_file(path, new_name)
        except ProfileFormatError as exc:
            self._append_log("error", f"Rename failed: {exc}")
            QMessageBox.warning(self, "Rename failed", str(exc))
            return
        if self.profile and self.profile.path and self.profile.path.resolve() == path.resolve():
            self.profile.path = target
            self.profile.name = target.stem
        self._refresh_profiles(select_path=target)
        self._append_log("accent", f"Renamed {path.name} → {target.name}")

    def _open_profiles_folder(self) -> None:
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.profiles_dir)))

    def _delete_profile(self) -> None:
        if self.mode != "setup":
            return
        path = self._selected_profile_path()
        if not path:
            return
        answer = QMessageBox.question(
            self,
            "Delete profile",
            f"Delete {path.name}? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            path.unlink()
            self._append_log("warn", f"Deleted {path.name}")
        except OSError as exc:
            self._append_log("error", f"Could not delete {path.name}: {exc}")
            return
        if self.profile and self.profile.path and self.profile.path.resolve() == path.resolve():
            self.profile.path = None
            self.profile.name = "unsaved"
            self._set_profile(self.profile)
        self._refresh_profiles()

    # ============================================================== targets ==
    def _refresh_targets(self, preferred: Target | None = None, announce: bool = False) -> None:
        desired = preferred or self.target
        self.windows = enumerate_visible_windows(self.own_pid)
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        self.target_combo.addItem("Any process", Target.any_target())
        best_index = 0
        for window in self.windows:
            target = Target.from_window(window)
            title = window.title
            if len(title) > 62:
                title = title[:59] + "…"
            self.target_combo.addItem(f"{window.exe} — {title}", target)
            if (
                not desired.any_process
                and desired.hwnd == window.hwnd
                and desired.pid == window.pid
            ):
                best_index = self.target_combo.count() - 1
        if best_index == 0 and self.binds.target_exe and not desired.any_process:
            match = find_window_by_exe(self.windows, self.binds.target_exe)
            if match:
                for index in range(1, self.target_combo.count()):
                    target = self.target_combo.itemData(index)
                    if target and target.hwnd == match.hwnd:
                        best_index = index
                        break
        self.target_combo.setCurrentIndex(best_index)
        self.target_combo.blockSignals(False)
        self.target = self.target_combo.itemData(best_index) or Target.any_target()
        self._update_target_display()
        if announce:
            self._append_log("info", f"{len(self.windows)} windows listed")
        if not self.target.any_process and not is_window(self.target.hwnd):
            self._append_log("warn", f"{self.target.exe} disappeared — target reset")
            self.target = Target.any_target()
            self.target_combo.blockSignals(True)
            self.target_combo.setCurrentIndex(0)
            self.target_combo.blockSignals(False)
            self._update_target_display()

    def _update_target_display(self) -> None:
        if self.binds.scope == "anywhere":
            self.target_detail.setText("Cursor window · this app excluded")
            self.target_combo.setToolTip("Ignored in anywhere scope")
        elif self.target.any_process:
            self.target_detail.setText("Pick an app")
            self.target_combo.setToolTip("Selected app scope needs a target")
        else:
            self.target_detail.setText(f"{self.target.exe} · PID {self.target.pid}")
            self.target_combo.setToolTip(self.target.label)

    def _on_scope_toggled(self, scope: str, checked: bool) -> None:
        if not checked or scope == self.binds.scope:
            return
        previous = self.binds.scope
        self.binds.scope = scope
        try:
            save_binds(self.binds_path, self.binds)
        except Exception as exc:  # noqa: BLE001
            self.binds.scope = previous
            self._sync_scope_radios()
            self._append_log("error", f"Could not save click scope: {exc}")
            return
        self._append_log("info", f"Scope: {scope}")
        self._update_scope_ui()
        self._update_target_display()
        self._update_controls()
        if scope == "restricted" and self.target.any_process:
            self._append_log("warn", "Selected app scope without a target.")

    def _sync_scope_radios(self) -> None:
        restricted = self.binds.scope == "restricted"
        for button, checked in ((self.scope_restricted, restricted), (self.scope_anywhere, not restricted)):
            button.blockSignals(True)
            button.setChecked(checked)
            button.blockSignals(False)

    def _update_scope_ui(self) -> None:
        self._sync_scope_radios()
        scope = "Selected app" if self.binds.scope == "restricted" else "Anywhere"
        self.settings_button.setToolTip(f"Settings · {scope}")

    def _on_target_changed(self, _index: int) -> None:
        target = self.target_combo.currentData()
        if not target:
            return
        changed = target != self.target
        self.target = target
        self._update_target_display()
        if self._loading_profile:
            return
        self.binds.target_exe = "" if target.any_process else target.exe
        try:
            save_binds(self.binds_path, self.binds)
        except Exception as exc:  # noqa: BLE001
            self._append_log("error", f"Could not save target: {exc}")
        if changed:
            self._append_log("info", f"Target: {target.label}")
            self._update_controls()

    def _dialog_parent(self) -> QWidget:
        if getattr(self, "settings_dialog", None) and self.settings_dialog.isVisible():
            return self.settings_dialog
        return self

    def _open_process_picker(self) -> None:
        if self.mode != "setup" or self.auto_session is not None:
            self._append_log("warn", "Stop recording/clicking before changing the target.")
            return
        if self.binds.scope != "restricted":
            self._append_log("warn", "Switch to Selected app scope first.")
            return
        self._activate_window()
        if self.hotkeys:
            self.hotkeys.pause()
        try:
            dialog = ProcessPickerDialog(self.own_pid, self.target, self._dialog_parent())
            if dialog.exec() == QDialog.Accepted:
                target = dialog.selected_target()
                if not target.any_process and not is_window(target.hwnd):
                    self._append_log("warn", f"{target.exe} is gone — list refreshed.")
                    self._refresh_targets(announce=False)
                    return
                self._refresh_targets(preferred=target, announce=False)
                index = 0
                for i in range(self.target_combo.count()):
                    candidate = self.target_combo.itemData(i)
                    if candidate is None:
                        continue
                    if target.any_process and candidate.any_process:
                        index = i
                        break
                    if not candidate.any_process and candidate.hwnd == target.hwnd and candidate.pid == target.pid:
                        index = i
                        break
                self.target_combo.blockSignals(True)
                self.target_combo.setCurrentIndex(index)
                self.target_combo.blockSignals(False)
                self.target = self.target_combo.itemData(index) or Target.any_target()
                self._update_target_display()
                self.binds.target_exe = "" if self.target.any_process else self.target.exe
                try:
                    save_binds(self.binds_path, self.binds)
                except Exception as exc:  # noqa: BLE001
                    self._append_log("error", f"Could not save target: {exc}")
                self._append_log("accent", f"Target: {self.target.label}")
                self._update_controls()
        finally:
            if self.hotkeys:
                self.hotkeys.resume()

    # ================================================================ auto ==
    def _auto_method(self) -> str:
        return normalise_method(self.auto_method_combo.currentData())

    def _on_auto_spin(self, side: str) -> None:
        if self._syncing_auto:
            return
        value = (
            self.auto_min_spin.value() if side == "low" else self.auto_max_spin.value()
        )
        self._apply_auto_bounds(side, float(value))

    def _on_auto_slider(self, side: str) -> None:
        if self._syncing_auto:
            return
        raw = (
            self.auto_min_slider.value() if side == "low" else self.auto_max_slider.value()
        )
        self._apply_auto_bounds(side, raw / 10.0)

    def _apply_auto_bounds(self, side: str, value: float) -> None:
        """Move one bound, pushing the other so low <= high always holds.

        Static mode has no variation, so both bounds are tied: moving or typing
        either one sets both to that value.
        """
        if self._auto_method() == METHOD_STATIC:
            value = min(max(float(value), MIN_CPS), MAX_CPS)
            low = high = value
        else:
            low = value if side == "low" else float(self.auto_min_spin.value())
            high = value if side == "high" else float(self.auto_max_spin.value())
            low, high = sync_bounds(low, high, changed=side)
            low, high = validate_cps(low, high)
        self._syncing_auto = True
        try:
            self.auto_min_spin.setValue(low)
            self.auto_max_spin.setValue(high)
            self.auto_min_slider.setValue(int(round(low * 10)))
            self.auto_max_slider.setValue(int(round(high * 10)))
        finally:
            self._syncing_auto = False
        self._save_auto_settings()

    def _tie_static_bounds(self) -> None:
        """Collapse differing bounds to their midpoint when Static is selected."""
        if self._auto_method() != METHOD_STATIC:
            return
        low = float(self.auto_min_spin.value())
        high = float(self.auto_max_spin.value())
        if low == high:
            return
        self._apply_auto_bounds("low", round((low + high) / 2.0, 1))

    def _on_auto_method_changed(self) -> None:
        if self._syncing_auto:
            return
        self._save_auto_settings()
        self._tie_static_bounds()
        self._update_auto_labels()
        self._update_controls()
        self._update_compact_state()

    def _on_auto_sigma_changed(self) -> None:
        if self._syncing_auto:
            return
        self._save_auto_settings()

    def _save_auto_settings(self) -> None:
        if not self._auto_loaded:
            return
        self.settings.auto_min_cps = float(self.auto_min_spin.value())
        self.settings.auto_max_cps = float(self.auto_max_spin.value())
        self.settings.auto_method = self._auto_method()
        self.settings.auto_sigma = clamp_sigma(self.auto_sigma_spin.value() / 100.0)
        save_settings(self.settings_path, self.settings)

    def _sigma_active(self) -> bool:
        return self._auto_method() in (METHOD_GAUSSIAN, METHOD_GAUSSIAN_POISSON)

    def _update_auto_labels(self) -> None:
        method = self._auto_method()
        self.auto_method_combo.setToolTip(METHOD_DESCRIPTIONS[method])
        editable = self._auto_loaded and self.auto_session is None and self.mode == "setup"
        sigma_ok = self._sigma_active() and editable
        self.auto_sigma_spin.setEnabled(sigma_ok)
        self.auto_sigma_label.setEnabled(sigma_ok)
        self.auto_sigma_spin.setVisible(sigma_ok)
        self.auto_sigma_label.setVisible(sigma_ok)

    def _cycle_auto_method(self) -> None:
        if self.auto_session is not None:
            return
        index = (self.auto_method_combo.currentIndex() + 1) % self.auto_method_combo.count()
        self.auto_method_combo.setCurrentIndex(index)

    def _auto_tab_active(self) -> bool:
        return self.tabs.currentIndex() == 1

    def _on_tab_changed(self, index: int) -> None:
        self.settings.active_tab = 1 if index == 1 else 0
        save_settings(self.settings_path, self.settings)
        self._update_controls()
        self._update_compact_state()
        self._update_mascot()
        self._place_bite()

    def _toggle_autoclicker(self) -> None:
        """Compatibility wrapper used by tests/tools: arm or disarm the clicker."""
        self._toggle_arm()

    def _start_autoclicker(self, triggered: bool = False) -> None:
        if self.auto_session is not None:
            return
        if self.mode == "recording":
            self._show_auto_error(f"Stop recording with {self.binds.record} first.")
            return
        if self.player is not None:
            self._show_auto_error("Profile playback is running — stop it first.")
            return
        low = float(self.auto_min_spin.value())
        high = float(self.auto_max_spin.value())
        try:
            low, high = validate_cps(low, high)
        except ValueError as exc:
            self._show_auto_error(str(exc))
            return

        restricted = self.binds.scope == "restricted"
        if restricted and self.target.any_process:
            self._show_auto_error("Selected app scope needs a target.")
            return
        if not self.target.any_process and not is_window(self.target.hwnd):
            self._show_auto_error(f"Target window is gone: {self.target.label}")
            self._refresh_targets()
            return

        method = self._auto_method()
        sigma = clamp_sigma(self.auto_sigma_spin.value() / 100.0)
        self._save_auto_settings()
        backend = create_backend(self.backend_name)
        session = AutoClickerSession(
            low,
            high,
            self.record_button_name,
            self.target if restricted else Target.any_target(),
            backend,
            self.own_pid,
            restricted=restricted,
            method=method,
            sigma=sigma,
            parent=self,
        )
        session.log.connect(self._append_log)
        session.finished_run.connect(lambda summary, s=session: self._on_auto_finished(s, summary))
        self.auto_session = session

        self.rhythm.clear()
        self._append_log("accent", f"Auto on — {METHOD_LABELS[method]} {low:.1f}–{high:.1f} CPS")
        self._update_auto_labels()
        self._update_controls()
        session.start()

    def _show_auto_error(self, message: str) -> None:
        self._append_log("error", message)

    def _stop_autoclicker(self, sync: bool = True) -> None:
        session = self.auto_session
        if session is None:
            return
        if session is self._trigger_session:
            self._trigger_session = None
        self.arm.clicking = False
        session.stop()
        if sync:
            session.wait(2500)
        if self.auto_session is session:
            self.auto_session = None
            self._update_auto_labels()
            self._update_controls()
            self._update_arm_ui()
            self._update_compact_state()

    def _stop_active(self, sync: bool = True) -> None:
        """Stop whichever click source is running (auto-clicker, playback or recording)."""
        if self.auto_session is not None:
            self._stop_autoclicker(sync=sync)
        if self.player is not None:
            self._stop_playback(sync=sync)
        if self.mode == "recording":
            self._stop_recording()
        self.arm.clicking = False
        self._update_compact_state()

    def _on_auto_finished(self, session: AutoClickerSession, summary: dict) -> None:
        if session is not self.auto_session:
            return
        if session is self._trigger_session:
            self._trigger_session = None
        self.auto_session = None
        self.arm.clicking = False
        self._append_log(
            "accent",
            f"Auto stopped — {int(summary.get('sent', 0))} clicks in "
            f"{float(summary.get('elapsed_s', 0.0)):.1f}s",
        )
        self._update_auto_labels()
        self._update_controls()
        self._update_arm_ui()
        self._update_compact_state()

    # =========================================================== import/export ==
    def _import_profile(self) -> None:
        if self.mode != "setup":
            self._append_log("warn", "Stop recording/clicking before importing.")
            return
        filename, _filter = QFileDialog.getOpenFileName(
            self,
            "Import click profile",
            str(self.profiles_dir),
            "Kirby Clicker exchange (*.rcprofile.json *.json);;"
            "Click profiles (*.txt);;All files (*)",
        )
        if not filename:
            return
        source = Path(filename)
        try:
            outcome = import_profile_file(source, self.profiles_dir)
        except ProfileFormatError as exc:
            self._append_log("error", f"Import rejected: {exc}")
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - a bad file must never crash the app
            self._append_log("error", f"Import failed: {exc}")
            QMessageBox.warning(self, "Import failed", f"Unexpected error:\n{exc}")
            return

        self._load_profile_path(outcome.path, announce=False)
        self._append_log("accent", f"Imported {outcome.source.name} → profiles/{outcome.path.name}")
        if outcome.renamed_from:
            self._append_log("warn", f"Saved as {outcome.path.name} — existing files kept.")
        self._refresh_profiles(select_path=outcome.path)
        self._update_controls()

    def _export_profile(self) -> None:
        if self.mode != "setup":
            self._append_log("warn", "Stop recording/clicking before exporting.")
            return
        if not self.profile or not self.profile.clicks:
            self._append_log("warn", "Nothing to export — record or load a profile first.")
            return
        base = self.profile.path.stem if self.profile.path else self.profile.name
        filename, _filter = QFileDialog.getSaveFileName(
            self,
            "Export click profile",
            str(self.profiles_dir / f"{base}{FILE_SUFFIX}"),
            "Kirby Clicker exchange (*.rcprofile.json);;JSON (*.json)",
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(FILE_SUFFIX) if path.suffix else path.with_name(path.name + FILE_SUFFIX)
        try:
            export_profile(path, self.profile, name=base)
        except ProfileFormatError as exc:
            self._append_log("error", f"Export rejected: {exc}")
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self._append_log("error", f"Export failed: {exc}")
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        self._append_log("accent", f"Exported to {path}")

    # ============================================================ recording ==
    def _toggle_recording(self) -> None:
        if self.mode == "recording":
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        if self.mode == "recording":
            return
        if self.auto_session is not None:
            self._append_log("warn", "Auto-clicker is running — stop it first.")
            return
        if self.arm.armed or self._trigger_session is not None:
            self._disarm_and_stop(sync=True)
        if self.player:
            self._stop_playback(sync=True)
        restricted = self.binds.scope == "restricted"
        if restricted and self.target.any_process:
            self._append_log("warn", "Selected app scope needs a target.")
            return
        if not self.target.any_process and not is_window(self.target.hwnd):
            self._append_log("error", f"Target window is gone: {self.target.label}")
            self._refresh_targets()
            return

        self.recorder = RecorderEngine(
            button=self.record_button_name,
            own_pid=self.own_pid,
            target_pid=self.target.pid if restricted else None,
        )
        self.recorder.start()
        self.hook = MouseHookThread(self.own_pid)
        self.hook.button_event.connect(self._on_hook_event)
        self.hook.hook_error.connect(self._on_hook_error)
        self._set_mode("recording")
        self.rhythm.clear()
        self.hook.start()
        self._append_log("accent", f"Recording {self.record_button_name} clicks")
        self._update_controls()

    def _stop_recording(self) -> None:
        if self.mode != "recording" or not self.recorder:
            return
        self._set_mode("setup")
        if self.hook:
            self.hook.stop()
            self.hook = None
        QApplication.processEvents()
        engine = self.recorder
        self.recorder = None
        recorded = engine.stop()
        if not recorded.clicks:
            self._append_log("warn", "No clicks captured — nothing saved.")
            self._set_mode("setup")
            return

        path = self._unique_recording_path()
        try:
            saved = save_profile(path, recorded)
        except Exception as exc:  # noqa: BLE001
            self._append_log("error", f"Could not save recording: {exc}")
            self._set_profile(recorded)
            return
        self._set_profile(saved)
        self._refresh_profiles(select_path=path)
        self._append_log("accent", f"Saved profiles/{path.name}")
        self._set_mode("setup")
        self._update_controls()

    def _unique_recording_path(self) -> Path:
        """Lowest unused recN.txt, so new recordings are rec1, rec2, rec3..."""
        return next_recording_path(self.profiles_dir)

    def _on_hook_event(self, event: dict) -> None:
        if self.mode != "recording" or not self.recorder:
            return
        if event.get("kind") == "down":
            self.recorder.on_down(
                event["t_ms"], event["button"], event["owner_pid"], event["injected"]
            )
        elif event.get("kind") == "up":
            self.recorder.on_up(
                event["t_ms"], event["button"], event["owner_pid"], event["injected"]
            )

    def _on_hook_error(self, message: str) -> None:
        self._append_log("error", message)
        if self.mode == "recording":
            self._stop_recording()

    def _style_record_button(self, recording: bool) -> None:
        self.record_button.setText(
            f"■  Stop  {self.binds.record}" if recording
            else f"●  Record  {self.binds.record}"
        )

    # ============================================================= playback ==
    def _start_playback(self, dry_run: bool | None = None, triggered: bool = True) -> None:
        if self.mode == "armed":
            return
        if self.auto_session is not None:
            self._append_log("warn", "Auto-clicker is running — stop it first.")
            return
        if self.mode == "recording":
            self._stop_recording()
        if not self.profile or not self.profile.clicks:
            self._append_log("warn", "No profile loaded — record or pick one first.")
            return
        restricted = self.binds.scope == "restricted"
        if restricted and self.target.any_process:
            self._append_log("warn", "Selected app scope needs a target.")
            return
        if not self.target.any_process and not is_window(self.target.hwnd):
            self._append_log("error", f"Target window is gone: {self.target.label}")
            self._refresh_targets()
            return
        use_dry = self.dry_run if dry_run is None else dry_run
        backend = create_backend("foreground") if use_dry else create_backend(self.backend_name)
        session = PlaybackSession(
            profile=self.profile,
            target=self.target if restricted else Target.any_target(),
            backend=backend,
            own_pid=self.own_pid,
            dry_run=use_dry,
            restricted=restricted,
            parent=self,
        )
        session.log.connect(self._append_log)
        session.finished_playback.connect(
            lambda summary, s=session: self._on_playback_finished(s, summary)
        )
        self.player = session
        self._set_mode("armed")
        self.rhythm.clear()
        self._update_controls()
        self.arm.clicking = True
        self._update_dot()
        session.start()

    def _stop_playback(self, sync: bool = True) -> None:
        session = self.player
        if not session:
            if self.mode == "armed":
                self._set_mode("setup")
            return
        if session is self._trigger_session:
            self._trigger_session = None
        self.arm.clicking = False
        session.stop()
        if sync:
            session.wait(2500)
        if self.player is session:
            self.player = None
            self._set_mode("setup")
            self._reset_playback_display()
        self._update_controls()
        self._update_arm_ui()
        self._update_compact_state()

    def _on_playback_finished(self, session: PlaybackSession, _summary: dict) -> None:
        if session is self._trigger_session:
            self._trigger_session = None
        if session is not self.player:
            return
        self.player = None
        self.arm.clicking = False
        self._set_mode("setup")
        self._reset_playback_display()
        self._update_controls()
        self._update_arm_ui()
        self._update_compact_state()

    def _reset_playback_display(self) -> None:
        # Rhythm bars keep the last session's pattern until the next click.
        self._update_arm_ui()

    # ================================================================ binds ==
    def _stop_key(self) -> str:
        return self.fallback_hotkeys.get("quit") or self.binds.quit

    def _on_hotkey_registration(self, failed: list, fallbacks: dict) -> None:
        self.blocked_hotkeys = set(failed)
        self.fallback_hotkeys = dict(fallbacks)
        if fallbacks:
            pairs = ", ".join(f"{key}→{alt}" for key, alt in sorted(fallbacks.items()))
            self._append_log("warn", f"Hotkey fallback: {pairs}")

    def _open_bind_editor(self) -> None:
        if self.mode != "setup" or self.auto_session is not None or self.arm.armed:
            self._append_log("warn", "Turn OFF and stop recording before editing binds.")
            return
        self._activate_window()
        if self.hotkeys:
            self.hotkeys.pause()
        saved = False
        try:
            dialog = BindEditorDialog(self.binds, str(self.binds_path), self._dialog_parent())
            if dialog.exec() == QDialog.Accepted:
                try:
                    save_binds(self.binds_path, dialog.binds)
                except (BindError, OSError) as exc:
                    QMessageBox.warning(self, "Save failed", str(exc))
                    self._append_log("error", f"Could not save binds: {exc}")
                    return
                self.binds = dialog.binds
                saved = True
                self._update_arm_ui()
                self._append_log("accent", "Binds saved")
                self._restart_hotkeys()
                self._restart_trigger_monitor()
        finally:
            if not saved and self.hotkeys:
                self.hotkeys.resume()

    # ============================================================== settings ==
    def _open_settings(self) -> None:
        self._activate_window()
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()
        self.settings_dialog.exec()

    def _on_backend_changed(self, _index: int) -> None:
        self.backend_name = self.backend_combo.currentData() or "foreground"
        self.settings.click_backend = self.backend_name
        save_settings(self.settings_path, self.settings)
        self._append_log("info", f"Backend: {BACKENDS[self.backend_name][0]}")

    def _on_button_changed(self, _index: int) -> None:
        self.record_button_name = self.button_combo.currentData() or "left"
        self.record_button.setToolTip(f"Records {self.record_button_name} clicks")

    def _on_dry_run_toggled(self, checked: bool) -> None:
        self.dry_run = checked
        self._append_log(
            "warn" if checked else "info",
            "Dry run on — no real clicks" if checked else "Dry run off",
        )

    # ================================================================ modes ==
    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        self._style_record_button(mode == "recording")
        self.record_button.setToolTip(
            f"Stop with {self.binds.record}" if mode == "recording"
            else f"Start with {self.binds.record}"
        )
        self._update_controls()

    def _update_controls(self) -> None:
        setup = self.mode == "setup"
        auto_running = self.auto_session is not None
        can_edit = setup and not auto_running and not self.arm.armed
        has_profile = bool(self.profile and self.profile.clicks)
        restricted = self.binds.scope == "restricted"
        target_ready = not restricted or not self.target.any_process
        self.target_combo.setEnabled(can_edit and restricted)
        self.target_refresh_button.setEnabled(can_edit and restricted)
        self.target_pick_button.setEnabled(can_edit and restricted)
        self.scope_restricted.setEnabled(can_edit)
        self.scope_anywhere.setEnabled(can_edit)
        self.backend_combo.setEnabled(can_edit)
        self.button_combo.setEnabled(can_edit)
        self.dry_check.setEnabled(can_edit)
        self.profile_combo.setEnabled(can_edit)
        self.profile_load_button.setEnabled(can_edit)
        self.profile_rename_button.setEnabled(can_edit and self._selected_profile_path() is not None)
        self.profile_folder_button.setEnabled(True)
        self.profile_import_button.setEnabled(can_edit)
        self.profile_export_button.setEnabled(can_edit and has_profile)
        self.profile_delete_button.setEnabled(can_edit and self._selected_profile_path() is not None)
        self.edit_binds_button.setEnabled(can_edit)
        self.arm_button.setEnabled(self.mode != "recording")
        self.record_button.setEnabled(target_ready and not auto_running)
        self.record_button.setToolTip(
            f"Stop with {self.binds.record}" if self.mode == "recording"
            else f"Start with {self.binds.record}"
        )
        editable_auto = not auto_running and setup
        self.auto_method_combo.setEnabled(editable_auto)
        self.auto_min_spin.setEnabled(editable_auto)
        self.auto_max_spin.setEnabled(editable_auto)
        self.auto_min_slider.setEnabled(editable_auto)
        self.auto_max_slider.setEnabled(editable_auto)
        self.auto_sigma_spin.setEnabled(editable_auto and self._sigma_active())
        self.auto_sigma_label.setEnabled(editable_auto and self._sigma_active())
        self._update_arm_ui()

    # ============================================================== hotkeys ==
    def _on_hotkey(self, action: str) -> None:
        if action == "record":
            if self.arm.armed:
                self._disarm_and_stop(sync=True)
            if self.mode == "recording":
                self._stop_recording()
            else:
                self._start_recording()
        elif action == "toggle":
            self._toggle_arm()
        elif action == "quit":
            if self.auto_session is not None:
                self._stop_autoclicker(sync=True)
            if self.mode == "recording":
                self._stop_recording()
            elif self.mode == "armed" or self.arm.armed:
                self._disarm_and_stop(sync=True)
            else:
                self.close()
        elif action == "selector":
            self._open_process_picker()
        elif action == "rebind":
            self._open_bind_editor()

    # ================================================================== tick ==
    def _tick(self) -> None:
        if self.auto_session is not None:
            self._apply_auto_snapshot()
        if self.mode == "recording" and self.recorder:
            self.rhythm.set_data(self.recorder.snapshot().intervals_ms)
        elif self.mode == "armed" and self.player:
            self._apply_playback_snapshot(self.player.snapshot())
        if self._compact:
            self._update_compact_state()

    def _apply_auto_snapshot(self) -> None:
        if self.auto_session is None:
            return
        snap = self.auto_session.snapshot()
        self.rhythm.set_data(list(snap["recent"]))

    def _apply_playback_snapshot(self, snap: PlaybackSnapshot) -> None:
        self.rhythm.set_data(snap.intervals_ms)

    # =============================================================== compact ==
    def _ensure_overlay(self) -> CompactOverlay:
        if self.compact_overlay is None:
            overlay = CompactOverlay()
            overlay.arm_requested.connect(self._toggle_arm)
            overlay.method_requested.connect(self._cycle_auto_method)
            overlay.restore_requested.connect(self._restore_full)
            overlay.moved.connect(self._persist_compact_position)
            self.compact_overlay = overlay
        return self.compact_overlay

    def _enter_compact(self) -> None:
        if self._compact:
            return
        self._full_geometry = self.geometry()
        self._compact = True
        overlay = self._ensure_overlay()
        pos = self.settings.compact_pos
        if pos:
            overlay.move(int(pos[0]), int(pos[1]))
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            overlay.move(
                screen.right() - overlay.width() - 24,
                screen.bottom() - overlay.height() - 48,
            )
        self._update_compact_state()
        overlay.show()
        self.hide()
        self._persist_ui_settings()

    def _restore_full(self) -> None:
        if not self._compact:
            return
        if self.compact_overlay is not None:
            self._persist_compact_position()
            self.compact_overlay.hide()
        self._compact = False
        self.showNormal()
        if self._full_geometry is not None:
            self.setGeometry(self._full_geometry)
        self.raise_()
        self.activateWindow()
        self._persist_ui_settings()
        self._update_controls()

    def _persist_compact_position(self) -> None:
        if self.compact_overlay is None:
            return
        self.settings.compact_pos = [self.compact_overlay.x(), self.compact_overlay.y()]
        save_settings(self.settings_path, self.settings)

    def _persist_ui_settings(self) -> None:
        if not self._compact:
            geom = self.geometry()
            self.settings.window_geometry = [geom.x(), geom.y(), geom.width(), geom.height()]
        if self.compact_overlay is not None:
            self.settings.compact_pos = [self.compact_overlay.x(), self.compact_overlay.y()]
        self.settings.compact_enabled = self._compact
        save_settings(self.settings_path, self.settings)

    def _can_start_active(self) -> bool:
        return resolve_trigger_kind(
            armed=self.arm.armed,
            recording=self.mode == "recording",
            busy=self._trigger_session is not None,
            tab_index=self.tabs.currentIndex(),
        ) is not None

    def _update_compact_state(self) -> None:
        if not self._compact or self.compact_overlay is None:
            return
        self.compact_overlay.set_state(
            self.arm.armed,
            self.arm.clicking,
            METHOD_SHORT_LABELS[self._auto_method()],
            self._recent_gaps(),
        )

    def _recent_gaps(self) -> list[float]:
        if self.auto_session is not None:
            return list(self.auto_session.snapshot()["recent"])
        if self.player is not None:
            return self.player.snapshot().intervals_ms
        if self.mode == "recording" and self.recorder is not None:
            return self.recorder.snapshot().intervals_ms
        # Idle: keep showing the last session's bars instead of blanking.
        return list(self.rhythm.values())

    # ================================================================ helpers ==
    def _activate_window(self) -> None:
        if getattr(self, "settings_dialog", None) and self.settings_dialog.isVisible():
            return
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _append_log(self, level: str, message: str) -> None:
        """Keep the message for diagnostics; surface warnings in the footer."""
        self._messages.append(f"[{level}] {message}")
        if len(self._messages) > 500:
            del self._messages[:-500]
        if level in ("warn", "error") and hasattr(self, "notice"):
            self.notice.setText(message)
            self.notice.setToolTip(message)
            self._notice_timer.start(5000)

    def closeEvent(self, event) -> None:
        self._timer.stop()
        if self.auto_session is not None:
            self._stop_autoclicker(sync=True)
        if self.mode == "recording":
            self._stop_recording()
        if self.player:
            self._stop_playback(sync=True)
        self._persist_ui_settings()
        if self.compact_overlay is not None:
            self.compact_overlay.close()
            self.compact_overlay = None
        self.cat_movie.stop()
        self.music.set_playing(False)
        if self.hook:
            self.hook.stop()
            self.hook = None
        if self.hotkeys:
            self.hotkeys.stop()
            self.hotkeys = None
        if self.trigger_monitor:
            self.trigger_monitor.stop()
            self.trigger_monitor = None
        super().closeEvent(event)
