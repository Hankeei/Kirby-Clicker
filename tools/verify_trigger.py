"""GUI-level arm + mouse-trigger routing check.

Drives the real MainWindow: F9 arms, a simulated physical trigger press starts
the active tab's clicker, the release stops it. The auto tab's backend is
replaced with a silent one and the profile tab uses dry-run, so no clicks leave
the app.

Run:  py -3.13 tools/verify_trigger.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import win32  # noqa: E402
from app.core.backends import ClickBackend, ClickResult  # noqa: E402
from app.ui import main_window as main_window_module  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

VK_F9 = 0x78
KEYEVENTF_KEYUP = 0x0002


class SilentBackend(ClickBackend):
    name = "silent"

    def press(self, button, target, own_pid) -> ClickResult:
        return ClickResult(True)

    def release(self, button) -> ClickResult:
        return ClickResult(True)


def tap(vk: int) -> None:
    win32.user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.03)
    win32.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow(BASE)
    window.show()
    # The window restores the last-used tab; this check starts on Recorder.
    window.tabs.setCurrentIndex(0)
    window.dry_check.setChecked(True)
    main_window_module.create_backend = lambda _name: SilentBackend()
    # A stray physical mouse event must not end a simulated hold.
    if window.trigger_monitor is not None:
        window.trigger_monitor.pressed.disconnect(window._on_trigger_pressed)
        window.trigger_monitor.released.disconnect(window._on_trigger_released)

    results: dict[str, bool] = {}

    def arm() -> None:
        results["arm_hotkey"] = window.arm.armed
        print(f"F9 arm: {'PASS' if window.arm.armed else 'FAIL'} ({window.state_text()})")

    def profile_press() -> None:
        results["profile_press"] = window._trigger_session is window.player and window.player is not None
        print(
            "profile trigger press: "
            f"{'PASS' if results['profile_press'] else 'FAIL'} "
            f"(mode={window.mode}, clicking={window.arm.clicking})"
        )

    def profile_release() -> None:
        stopped = window.player is None and window.mode == "setup"
        results["profile_release"] = stopped
        print(
            f"profile trigger release: {'PASS' if stopped else 'FAIL'} "
            f"({window.state_text()})"
        )
        window.tabs.setCurrentIndex(1)

    def auto_check() -> None:
        results["auto_arm"] = window.arm.armed
        print(f"still armed on auto tab: {'PASS' if window.arm.armed else 'FAIL'}")
        window._on_trigger_pressed()

    def auto_release() -> None:
        results["auto_press"] = window.auto_session is None and window.arm.clicking is False
        print(
            "auto trigger press/release: "
            f"{'PASS' if window.auto_session is None else 'FAIL'} "
            f"({window.state_text()})"
        )
        tap(VK_F9)

    def check_disarm() -> None:
        results["disarm"] = not window.arm.armed
        print(f"F9 disarm: {'PASS' if results['disarm'] else 'FAIL'} ({window.state_text()})")
        app.quit()

    QTimer.singleShot(400, lambda: tap(VK_F9))
    QTimer.singleShot(800, arm)
    QTimer.singleShot(900, window._on_trigger_pressed)
    QTimer.singleShot(1300, profile_press)
    QTimer.singleShot(1500, window._on_trigger_released)
    QTimer.singleShot(1800, profile_release)
    QTimer.singleShot(2300, auto_check)
    QTimer.singleShot(2700, window._on_trigger_released)
    QTimer.singleShot(2900, auto_release)
    QTimer.singleShot(3400, check_disarm)

    app.exec()
    window.close()
    ok = all(results.values())
    print("RESULT:", "PASS" if ok else f"FAIL {results}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
