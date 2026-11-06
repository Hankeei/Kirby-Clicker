"""Entry point: python main.py  (or py -3.13 main.py)."""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.core.paths import app_icon_path, data_directory, migration_source
from app.ui import theme
from app.ui.main_window import MainWindow


def _set_app_id() -> None:
    """Give the process its own taskbar identity so the app icon is used."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "KirbyClicker.Desktop.1"
        )
    except Exception:  # noqa: BLE001 - best effort only
        pass


def main() -> int:
    _set_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName("Kirby Clicker")
    app.setApplicationDisplayName("Kirby Clicker")
    icon_file = app_icon_path()
    if icon_file.exists():
        app.setWindowIcon(QIcon(str(icon_file)))
    app.setStyle("Fusion")
    app.setPalette(theme.palette())
    app.setFont(theme.body_font())

    if "--selftest" in sys.argv:
        # Frozen-build check: confirm the bundled gif/audio/icon really load.
        from app.ui.music import selftest

        out = os.environ.get("KIRBYCLICKER_SELFTEST_OUT", "")
        out_path = Path(out) if out else Path.cwd() / "selftest.json"
        selftest(out_path)
        return 0

    data_dir = data_directory()
    window = MainWindow(data_dir)
    window.show()
    if migration_source() is not None:
        window.log_migration(migration_source(), data_dir)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
