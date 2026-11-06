"""Global hotkey check: drive the real window with injected key events only.

No mouse clicks are sent. The script starts Kirby Clicker, focuses its own dummy
window and sends F8 twice (start/stop recording), F9 twice (arm/disarm), then
Ctrl+F12 (the quit fallback used when F12 is already owned by another app).

Run:  py -3.13 tools/verify_hotkeys.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

from app.core import win32  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

VK_F8 = 0x77
VK_F9 = 0x78
VK_F12 = 0x7B
VK_CONTROL = 0x11
KEYEVENTF_KEYUP = 0x0002


def tap(vk: int, ctrl: bool = False) -> None:
    if ctrl:
        win32.user32.keybd_event(VK_CONTROL, 0, 0, 0)
    win32.user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.03)
    win32.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    if ctrl:
        win32.user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow(BASE)
    window.show()

    dummy = QWidget()
    dummy.setWindowTitle("Hotkey focus target")
    dummy.setGeometry(950, 620, 260, 120)
    label = QLabel("focus target (no clicks)", dummy)
    label.move(20, 40)
    dummy.show()
    dummy.raise_()
    dummy.activateWindow()

    result = {"record": False, "stop": False, "arm": False, "disarm": False, "quit": False}

    def check_recording() -> None:
        result["record"] = window.mode == "recording"
        print(f"F8 start while unfocused: {'PASS' if result['record'] else 'FAIL'} (mode={window.mode})")
        tap(VK_F8)

    def check_stopped() -> None:
        result["stop"] = window.mode == "setup"
        print(f"F8 stop while unfocused: {'PASS' if result['stop'] else 'FAIL'} (mode={window.mode})")
        tap(VK_F9)

    def check_armed() -> None:
        result["arm"] = window.arm.armed
        print(f"F9 arm while unfocused: {'PASS' if result['arm'] else 'FAIL'} ({window.state_text()})")
        tap(VK_F9)

    def check_disarmed() -> None:
        result["disarm"] = not window.arm.armed
        print(f"F9 disarm: {'PASS' if result['disarm'] else 'FAIL'} ({window.state_text()})")
        tap(VK_F12, ctrl=bool(window.fallback_hotkeys.get("quit")))

    def check_quit() -> None:
        result["quit"] = not window.isVisible()
        print(f"Ctrl+F12 quit while disarmed: {'PASS' if result['quit'] else 'FAIL'}")
        dummy.close()
        app.quit()

    QTimer.singleShot(500, lambda: tap(VK_F8))
    QTimer.singleShot(1000, check_recording)
    QTimer.singleShot(1500, check_stopped)
    QTimer.singleShot(1900, check_armed)
    QTimer.singleShot(2300, check_disarmed)
    QTimer.singleShot(2800, check_quit)

    app.exec()
    return 0 if all(result.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
