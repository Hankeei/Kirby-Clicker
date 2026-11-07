"""Modal dialogs: process picker and hotkey editor."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.binds import (
    ACTION_LABELS,
    BIND_ACTIONS,
    BindError,
    BindSet,
    canonical_key,
    is_mouse_key,
    key_name_from_vk,
)
from ..core.backends import BACKENDS
from ..core.windows import Target, WindowInfo, enumerate_visible_windows
from . import theme
from .widgets import Cushion, field_label, muted


class ProcessPickerDialog(QDialog):
    def __init__(self, own_pid: int, current: Target, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select process")
        self.resize(700, 440)
        self.setStyleSheet(theme.stylesheet())
        self.own_pid = own_pid
        self.selected: Target = current
        self._windows: list[WindowInfo] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("SELECT PROCESS")
        title.setObjectName("PanelTitle")
        title.setFont(theme.panel_title_font())
        layout.addWidget(title)
        hint = QLabel("Target selection applies to the Selected app scope.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Executable", "Window title"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 190)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.doubleClicked.connect(lambda _index: self._accept())
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.reload)
        buttons.addWidget(self.refresh_button)
        buttons.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.Cancel)
        use_button = QPushButton("Use selected")
        use_button.setProperty("accent", True)
        box.addButton(use_button, QDialogButtonBox.AcceptRole)
        box.accepted.connect(self._accept)
        box.rejected.connect(self.reject)
        buttons.addWidget(box)
        layout.addLayout(buttons)

        self.reload()

    def reload(self) -> None:
        self._windows = enumerate_visible_windows(self.own_pid)
        self.table.setRowCount(0)
        self._add_row("Any process", "Cursor window — this app always excluded", Target.any_target(), current=False)
        for window in self._windows:
            target = Target.from_window(window)
            selected = (
                not self.selected.any_process
                and self.selected.hwnd == window.hwnd
                and self.selected.pid == window.pid
            )
            self._add_row(window.exe, window.title, target, current=selected)
        if self.table.rowCount() == 1:
            self.table.selectRow(0)

    def _add_row(self, exe: str, title: str, target: Target, current: bool) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        exe_item = QTableWidgetItem(("→ " if current else "") + exe)
        title_item = QTableWidgetItem(title)
        exe_item.setData(Qt.UserRole, target)
        self.table.setItem(row, 0, exe_item)
        self.table.setItem(row, 1, title_item)
        if current:
            self.table.selectRow(row)
        if row == 0 and self.selected.any_process:
            self.table.selectRow(0)

    def _accept(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        self.selected = item.data(Qt.UserRole) or Target.any_target()
        self.accept()

    def selected_target(self) -> Target:
        return self.selected


class KeyCaptureButton(QPushButton):
    """Shows one binding. Clicking it asks the dialog to capture the next input."""

    def __init__(self, key: str, parent: QWidget | None = None):
        super().__init__(key, parent)
        self.key_name = key

    def set_key(self, key: str) -> None:
        self.key_name = key
        self.setText(key)


def _qt_key_name(event: QKeyEvent) -> str | None:
    key = int(event.key())
    if Qt.Key_F1 <= key <= Qt.Key_F24:
        return f"F{key - int(Qt.Key_F1) + 1}"
    if int(Qt.Key_A) <= key <= int(Qt.Key_Z):
        return chr(key)
    if int(Qt.Key_0) <= key <= int(Qt.Key_9):
        return chr(key)
    names = {
        int(Qt.Key_Space): "SPACE",
        int(Qt.Key_Tab): "TAB",
        int(Qt.Key_Return): "ENTER",
        int(Qt.Key_Enter): "ENTER",
        int(Qt.Key_Insert): "INSERT",
        int(Qt.Key_Delete): "DELETE",
        int(Qt.Key_Home): "HOME",
        int(Qt.Key_End): "END",
        int(Qt.Key_PageUp): "PAGEUP",
        int(Qt.Key_PageDown): "PAGEDOWN",
        int(Qt.Key_Up): "UP",
        int(Qt.Key_Down): "DOWN",
        int(Qt.Key_Left): "LEFT",
        int(Qt.Key_Right): "RIGHT",
        int(Qt.Key_Shift): "LSHIFT",
        int(Qt.Key_Control): "LCTRL",
        int(Qt.Key_Alt): "LALT",
        int(Qt.Key_Backspace): "BACKSPACE",
        int(Qt.Key_Escape): "ESC",
    }
    return names.get(key)


def _qt_mouse_name(button: Qt.MouseButton) -> str | None:
    return {
        Qt.LeftButton: "MOUSE1",
        Qt.RightButton: "MOUSE2",
        Qt.MiddleButton: "MOUSE3",
        Qt.BackButton: "MOUSE4",
        Qt.ForwardButton: "MOUSE5",
    }.get(button)


class BindEditorDialog(QDialog):
    def __init__(self, binds: BindSet, path_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit binds — Kirby Clicker")
        self.resize(560, 410)
        self.setStyleSheet(theme.stylesheet())
        self.binds = binds
        self._captures: dict[str, KeyCaptureButton] = {}
        self._capture_action: str | None = None
        self._capture_previous = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("BINDS")
        title.setObjectName("PanelTitle")
        title.setFont(theme.panel_title_font())
        layout.addWidget(title)
        hint = QLabel("Click a box, then press a key. Esc cancels.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        grid = QGridLayout()
        grid.setVerticalSpacing(9)
        grid.setHorizontalSpacing(12)
        for row, action in enumerate(BIND_ACTIONS):
            label = QLabel(ACTION_LABELS[action])
            grid.addWidget(label, row, 0)
            capture = KeyCaptureButton(binds.get(action))
            capture.setToolTip(
                "Mouse buttons (MOUSE1–MOUSE5) are allowed for the trigger only."
                if action == "trigger"
                else "Keyboard keys only — Windows global hotkeys cannot be mouse buttons."
            )
            capture.clicked.connect(lambda _checked=False, a=action: self.begin_capture(a))
            grid.addWidget(capture, row, 1)
            self._captures[action] = capture
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addStretch(1)

        path_label = QLabel(f"File: {path_text}")
        path_label.setObjectName("Muted")
        path_label.setWordWrap(True)
        layout.addWidget(path_label)

        box = QDialogButtonBox(QDialogButtonBox.Cancel)
        save_button = QPushButton("Save binds")
        save_button.setProperty("accent", True)
        box.addButton(save_button, QDialogButtonBox.AcceptRole)
        box.accepted.connect(self._accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    # -- capture -----------------------------------------------------------
    def begin_capture(self, action: str) -> None:
        self.stop_capture(restore=True)
        self._capture_action = action
        self._capture_previous = self._captures[action].key_name
        self._captures[action].setText("press a key or click…")
        self._captures[action].setFocus(Qt.OtherFocusReason)
        QApplication.instance().installEventFilter(self)

    def stop_capture(self, restore: bool = False) -> None:
        action, self._capture_action = self._capture_action, None
        if action is None:
            return
        QApplication.instance().removeEventFilter(self)
        if restore:
            self._captures[action].setText(self._capture_previous)
        else:
            self._captures[action].setText(self._captures[action].key_name)

    def _reject_capture(self, message: str) -> None:
        action = self._capture_action
        if action:
            self._captures[action].setText(message)

    def eventFilter(self, obj, event) -> bool:
        if self._capture_action is None:
            return super().eventFilter(obj, event)
        if event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:
                self.stop_capture(restore=True)
                return True
            name = _qt_key_name(event)
            native = int(event.nativeVirtualKey())
            if not name and native:
                name = key_name_from_vk(native)
                if native == 0x10:
                    name = "LSHIFT"
                elif native == 0x11:
                    name = "LCTRL"
                elif native == 0x12:
                    name = "LALT"
            if name:
                self._apply_capture(name)
            return True
        if event.type() == QEvent.MouseButtonPress:
            name = _qt_mouse_name(event.button())
            if name:
                self._apply_capture(name)
            return True
        return super().eventFilter(obj, event)

    def _apply_capture(self, name: str) -> None:
        action = self._capture_action
        if action is None:
            return
        try:
            name = canonical_key(name)
        except BindError:
            self._reject_capture("unsupported — try again")
            return
        mouse = is_mouse_key(name)
        if action == "trigger" and not mouse:
            self._reject_capture("trigger needs a mouse button")
            self._capture_previous = self._captures[action].key_name
            return
        if action != "trigger" and mouse:
            self._reject_capture("mouse only for trigger")
            return
        self._captures[action].key_name = name
        self.stop_capture()
        self._captures[action].setFocus(Qt.OtherFocusReason)

    def done(self, result: int) -> None:
        self.stop_capture()
        super().done(result)

    def _accept(self) -> None:
        candidate = BindSet(
            record=self._captures["record"].key_name,
            toggle=self._captures["toggle"].key_name,
            trigger=self._captures["trigger"].key_name,
            quit=self._captures["quit"].key_name,
            rebind=self._captures["rebind"].key_name,
            selector=self._captures["selector"].key_name,
            scope=self.binds.scope,
            target_exe=self.binds.target_exe,
            path=self.binds.path,
            extra=dict(self.binds.extra),
        )
        try:
            candidate.validate()
        except BindError as exc:
            QMessageBox.warning(self, "Invalid binds", str(exc))
            return
        self.binds = candidate
        self.accept()


class SettingsDialog(QDialog):
    """Secondary options that no longer live in the main window.

    The widgets are hosted here but assigned onto the main window (``backend_combo``,
    ``scope_restricted``, ...) so the window's existing handlers and enable/disable
    logic keep working unchanged.
    """

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Settings — Kirby Clicker")
        self.setModal(True)
        self.setMinimumSize(486, 596)
        self.setStyleSheet(theme.stylesheet())
        self._build()
        self.resize(486, 596)

    def _build(self) -> None:
        window = self.window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        heading = QLabel("SETTINGS")
        heading.setObjectName("PanelTitle")
        heading.setFont(theme.panel_title_font())
        layout.addWidget(heading)

        # -- clicking -----------------------------------------------------
        clicking = Cushion("mint")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(7)
        grid.addWidget(field_label("Backend"), 0, 0)
        window.backend_combo = QComboBox()
        for key, (label, tip) in BACKENDS.items():
            window.backend_combo.addItem(label, key)
            window.backend_combo.setItemData(window.backend_combo.count() - 1, tip, Qt.ToolTipRole)
        window.backend_combo.setCurrentIndex(
            max(0, window.backend_combo.findData(window.backend_name))
        )
        grid.addWidget(window.backend_combo, 0, 1)
        grid.addWidget(field_label("Record button"), 1, 0)
        window.button_combo = QComboBox()
        for name in ("left", "right", "middle"):
            window.button_combo.addItem(name, name)
        window.button_combo.setCurrentText(window.record_button_name)
        grid.addWidget(window.button_combo, 1, 1)
        window.dry_check = QCheckBox("Dry run")
        window.dry_check.setToolTip("Click nothing; report intended timings only")
        window.dry_check.setChecked(window.dry_run)
        grid.addWidget(window.dry_check, 2, 0, 1, 2)
        grid.setColumnStretch(1, 1)
        clicking.body().addLayout(grid)
        layout.addWidget(clicking)

        # -- scope and target ---------------------------------------------
        scope = Cushion("lavender")
        radios = QHBoxLayout()
        radios.setSpacing(14)
        window.scope_restricted = QRadioButton("Selected app")
        window.scope_restricted.setToolTip("Clicks go only to the selected process")
        window.scope_anywhere = QRadioButton("Anywhere")
        window.scope_anywhere.setToolTip("Clicks go to the window under the cursor")
        window.scope_group = QButtonGroup(window)
        window.scope_group.addButton(window.scope_restricted)
        window.scope_group.addButton(window.scope_anywhere)
        radios.addWidget(window.scope_restricted)
        radios.addWidget(window.scope_anywhere)
        radios.addStretch(1)
        scope.body().addLayout(radios)

        target_row = QHBoxLayout()
        target_row.setSpacing(6)
        window.target_combo = QComboBox()
        window.target_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        window.target_combo.setMinimumContentsLength(16)
        window.target_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        window.target_pick_button = QPushButton("Pick…")
        window.target_pick_button.setFixedWidth(70)
        window.target_pick_button.setToolTip("Choose a visible window")
        window.target_refresh_button = QPushButton("↻")
        window.target_refresh_button.setFixedWidth(34)
        window.target_refresh_button.setToolTip("Refresh the window list")
        target_row.addWidget(window.target_combo, 1)
        target_row.addWidget(window.target_pick_button)
        target_row.addWidget(window.target_refresh_button)
        scope.body().addLayout(target_row)
        window.target_detail = muted("Cursor window")
        scope.body().addWidget(window.target_detail)
        layout.addWidget(scope)

        # -- files ---------------------------------------------------------
        files = Cushion("butter")
        files_row = QHBoxLayout()
        files_row.setSpacing(6)
        window.profile_delete_button = QPushButton("Delete")
        window.profile_import_button = QPushButton("Import…")
        window.profile_export_button = QPushButton("Export…")
        for button in (
            window.profile_delete_button,
            window.profile_import_button,
            window.profile_export_button,
        ):
            files_row.addWidget(button, 1)
        files.body().addLayout(files_row)
        window.edit_binds_button = QPushButton("Edit binds…")
        window.edit_binds_button.setToolTip("Record, ON/OFF, hold, stop and picker keys")
        files.body().addWidget(window.edit_binds_button)
        layout.addWidget(files)

        # -- music ---------------------------------------------------------
        music = Cushion("blue")
        window.music_check = QCheckBox("Background music")
        window.music_check.setToolTip("Loop luolei.mp3 in the background, ON or OFF")
        window.music_check.setChecked(window.settings.music_enabled)
        music.body().addWidget(window.music_check)
        volume_row = QHBoxLayout()
        volume_row.setSpacing(8)
        volume_row.addWidget(field_label("Volume"))
        window.music_slider = QSlider(Qt.Horizontal)
        window.music_slider.setRange(0, 100)
        window.music_slider.setValue(round(window.settings.music_volume * 100))
        window.music_slider.setToolTip("Background music volume")
        window.music_slider.setAccessibleName("Music volume")
        volume_row.addWidget(window.music_slider, 1)
        window.music_value = muted(f"{window.music_slider.value()}%")
        window.music_value.setMinimumWidth(34)
        window.music_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        volume_row.addWidget(window.music_value)
        music.body().addLayout(volume_row)
        layout.addWidget(music)

        layout.addWidget(muted(f"Kirby Clicker · {window.base_dir}"))

        done = QPushButton("Done")
        done.setObjectName("Primary")
        done.clicked.connect(self.accept)
        layout.addWidget(done, 0, Qt.AlignRight)

        signature = QLabel("vibe coded by @hankeei <3")
        signature.setObjectName("Signature")
        signature.setAlignment(Qt.AlignHCenter)
        layout.addWidget(signature)
        window.link_button = QPushButton("https://linktr.ee/hankeei")
        window.link_button.setObjectName("LinkButton")
        window.link_button.setFlat(True)
        window.link_button.setCursor(Qt.PointingHandCursor)
        window.link_button.setAccessibleName("Linktree")
        window.link_button.setToolTip("Open the Linktree page in your browser")
        window.link_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://linktr.ee/hankeei"))
        )
        layout.addWidget(window.link_button, 0, Qt.AlignHCenter)

        # -- wiring ------------------------------------------------------
        window.backend_combo.currentIndexChanged.connect(window._on_backend_changed)
        window.button_combo.currentIndexChanged.connect(window._on_button_changed)
        window.dry_check.toggled.connect(window._on_dry_run_toggled)
        window.scope_restricted.setChecked(window.binds.scope == "restricted")
        window.scope_anywhere.setChecked(window.binds.scope != "restricted")
        window.scope_restricted.toggled.connect(
            lambda checked: window._on_scope_toggled("restricted", checked)
        )
        window.scope_anywhere.toggled.connect(
            lambda checked: window._on_scope_toggled("anywhere", checked)
        )
        window.target_combo.currentIndexChanged.connect(window._on_target_changed)
        window.target_pick_button.clicked.connect(window._open_process_picker)
        window.target_refresh_button.clicked.connect(lambda: window._refresh_targets(announce=True))
        window.profile_delete_button.clicked.connect(window._delete_profile)
        window.profile_import_button.clicked.connect(window._import_profile)
        window.profile_export_button.clicked.connect(window._export_profile)
        window.edit_binds_button.clicked.connect(window._open_bind_editor)
        window.music_check.toggled.connect(window._on_music_toggled)
        window.music_slider.valueChanged.connect(window._on_music_volume_changed)

