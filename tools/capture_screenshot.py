"""Capture real Kirby Clicker screenshots of the running GUI.

Modes: default (recorder tab), --min (the smallest allowed window), --armed
(ON + dry-run clicking, so Kirby is eating and the cat dances), --auto (auto
tab, Pikachu Kirby), --compact (music-box overlay), --binds (bind editor
dialog), --settings (settings dialog with the music block, signature and
linktree).
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.backends import ClickBackend, ClickResult  # noqa: E402
from app.ui import main_window as main_window_module  # noqa: E402
from app.ui import theme  # noqa: E402
from app.ui.dialogs import BindEditorDialog  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


def _arg_value(flag: str) -> str | None:
    if flag not in sys.argv:
        return None
    index = sys.argv.index(flag)
    return sys.argv[index + 1] if index + 1 < len(sys.argv) else None


class SilentBackend(ClickBackend):
    """Counts presses without touching the OS mouse."""

    name = "silent"

    def press(self, button: str, target, own_pid: int) -> ClickResult:
        return ClickResult(True)

    def release(self, button: str) -> ClickResult:
        return ClickResult(True)

    def close(self) -> None:
        pass


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(theme.palette())
    app.setFont(theme.body_font())
    window = MainWindow(BASE)
    window.show()
    window.raise_()
    window.activateWindow()
    # Screenshots should not capture transient startup warnings.
    window._notice_timer.stop()
    window.notice.clear()

    auto_mode = "--auto" in sys.argv
    compact_mode = "--compact" in sys.argv
    armed = "--armed" in sys.argv
    binds_mode = "--binds" in sys.argv
    settings_mode = "--settings" in sys.argv
    min_mode = "--min" in sys.argv
    if not compact_mode:
        # Ignore a persisted compact preference during screenshots.
        window.settings.compact_enabled = False
        # Capture the new default (taller) layout rather than an old saved size.
        width, height = (
            (main_window_module.COMPACT_MIN_W, main_window_module.COMPACT_MIN_H)
            if min_mode
            else (main_window_module.COMPACT_W, main_window_module.COMPACT_H)
        )
        window.resize(width, height)

    if auto_mode or compact_mode:
        main_window_module.create_backend = lambda _name: SilentBackend()
        window.tabs.setCurrentIndex(1)
        window.auto_min_spin.setValue(10.0)
        window.auto_max_spin.setValue(18.0)
        method = _arg_value("--method") or "blatant"
        index = window.auto_method_combo.findData(method)
        if index >= 0:
            window.auto_method_combo.setCurrentIndex(index)

    if armed:
        # Profile screenshots use the dry-run preview so no real clicks are sent.
        window.dry_check.setChecked(True)

    if not (auto_mode or compact_mode):
        window.tabs.setCurrentIndex(0)

    if armed or auto_mode or compact_mode:
        # Screenshots simulate the hold by calling the handlers directly; a stray
        # physical mouse event must not end the simulated hold mid-capture.
        if window.trigger_monitor is not None:
            window.trigger_monitor.pressed.disconnect(window._on_trigger_pressed)
            window.trigger_monitor.released.disconnect(window._on_trigger_released)

    out = BASE / "screenshots" / "app.png"
    if min_mode:
        out = BASE / "screenshots" / "app_min.png"
    if armed:
        out = BASE / "screenshots" / "app_armed.png"
    elif auto_mode:
        method = _arg_value("--method") or ""
        out = BASE / "screenshots" / (
            f"auto_{method}.png" if method else "auto_tab.png"
        )
    elif compact_mode:
        out = BASE / "screenshots" / "compact.png"
    elif binds_mode:
        out = BASE / "screenshots" / "binds.png"
    elif settings_mode:
        out = BASE / "screenshots" / "settings.png"

    if binds_mode:
        QTimer.singleShot(400, lambda: _grab_binds(window, out))
        QTimer.singleShot(1800, app.quit)
    elif settings_mode:
        QTimer.singleShot(400, window._open_settings)
        QTimer.singleShot(900, lambda: _grab(window.settings_dialog, out))
        QTimer.singleShot(1400, window.settings_dialog.accept)
        QTimer.singleShot(1600, app.quit)
    elif compact_mode:
        QTimer.singleShot(300, window._toggle_arm)
        QTimer.singleShot(500, window._on_trigger_pressed)
        QTimer.singleShot(900, window._enter_compact)
        QTimer.singleShot(2400, lambda: _grab(window.compact_overlay, out))
        QTimer.singleShot(2600, window._on_trigger_released)
        QTimer.singleShot(2700, window._toggle_arm)
        QTimer.singleShot(2800, window._restore_full)
        QTimer.singleShot(3000, app.quit)
    elif auto_mode:
        # Show the controls enabled (OFF) with a representative rhythm sample.
        QTimer.singleShot(200, lambda: window.rhythm.set_data(
            [62, 58, 74, 55, 66, 71, 52, 60, 69, 57, 63, 78, 54, 61, 67, 59, 72, 56, 64, 60]
        ))
        QTimer.singleShot(500, lambda: _grab(window, out))
        QTimer.singleShot(700, app.quit)
    elif armed:
        QTimer.singleShot(300, window._toggle_arm)
        QTimer.singleShot(600, window._on_trigger_pressed)
        QTimer.singleShot(2100, lambda: _grab(window, out))
        QTimer.singleShot(2400, window._on_trigger_released)
        QTimer.singleShot(2500, window._toggle_arm)
        QTimer.singleShot(2700, app.quit)
    else:
        QTimer.singleShot(1400, lambda: _grab(window, out))
        QTimer.singleShot(1700, app.quit)

    return app.exec()


def _grab_binds(window, out: Path) -> None:
    dialog = BindEditorDialog(window.binds, str(window.binds_path), window)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    QTimer.singleShot(450, lambda: _grab(dialog, out))
    QTimer.singleShot(1000, dialog.reject)


def _grab(widget, out: Path) -> None:
    if widget is None:
        print(f"FAILED to capture {out}: widget is None")
        return
    notice = getattr(widget, "notice", None)
    if notice is not None:
        notice.clear()
    out.parent.mkdir(parents=True, exist_ok=True)
    pixmap = widget.grab()
    ok = pixmap.save(str(out), "PNG")
    print(f"{'saved' if ok else 'FAILED to save'} {out} ({pixmap.width()}x{pixmap.height()})")


if __name__ == "__main__":
    raise SystemExit(main())
