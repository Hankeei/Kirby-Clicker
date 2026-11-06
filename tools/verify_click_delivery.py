"""Click-delivery check against an isolated dummy window (both backends).

The script creates its own small target window, places the cursor over it and
asks each backend to press/release once.  It only ever clicks that dummy
window, and restores the original cursor position afterwards.

Run:  py -3.13 tools/verify_click_delivery.py
"""

from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from PySide6.QtCore import QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget  # noqa: E402

from app.core import win32  # noqa: E402
from app.core.backends import create_backend  # noqa: E402
from app.core.player import PlaybackSession  # noqa: E402
from app.core.profile import Click, ClickProfile  # noqa: E402
from app.core.windows import Target  # noqa: E402


class DummyTarget(QWidget):
    def __init__(self):
        super().__init__()
        self.presses = 0
        self.releases = 0
        self.setWindowTitle("Kirby Clicker Dummy Target")
        self.setGeometry(220, 180, 360, 220)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setStyleSheet("background:#12201f; color:#d9f5ef; font-size:15pt;")
        layout = QVBoxLayout(self)
        self.label = QLabel("dummy target\n0 clicks")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

    def mousePressEvent(self, event):
        self.presses += 1
        self.label.setText(f"dummy target\n{self.presses} click(s)")
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.releases += 1
        super().mouseReleaseEvent(event)

    def center(self) -> tuple[int, int]:
        point = self.mapToGlobal(self.rect().center())
        return int(point.x()), int(point.y())


def run_backend(name: str, dummy: DummyTarget, own_pid: int) -> bool:
    window = win32.window_under_point(*dummy.center())
    if not window[0]:
        print(f"{name:>10}: FAIL — no window under cursor")
        return False
    pid = win32.window_pid(window[0])
    target = Target(
        any_process=False,
        hwnd=window[1],
        pid=pid,
        exe=win32.process_exe(pid),
        title=dummy.windowTitle(),
    )
    backend = create_backend(name)
    before = dummy.presses
    result = backend.press("left", target, own_pid)
    deadline = time.time() + 0.6
    while time.time() < deadline and dummy.presses <= before:
        QApplication.processEvents()
        time.sleep(0.005)
    released = backend.release("left")
    deadline = time.time() + 0.2
    while time.time() < deadline and dummy.presses <= before:
        QApplication.processEvents()
        time.sleep(0.005)
    backend.close()
    delivered = dummy.presses > before and released.ok
    print(
        f"{name:>10}: {'PASS' if delivered else 'FAIL'} — press={result.ok} "
        f"release={released.ok} received={dummy.presses - before} "
        f"reason={result.reason or 'ok'}"
    )
    return delivered


def run_replay(name: str, dummy: DummyTarget, own_pid: int) -> bool:
    win = win32.window_under_point(*dummy.center())
    if not win[0]:
        print(f"{name:>10}: FAIL — no window under cursor for replay")
        return False
    pid = win32.window_pid(win[0])
    target = Target(
        any_process=False,
        hwnd=win[1],
        pid=pid,
        exe=win32.process_exe(pid),
        title=dummy.windowTitle(),
    )
    profile = ClickProfile(
        clicks=[Click(12, 38), Click(12, 38), Click(12, 38)], button="left", name="replay-check"
    )
    session = PlaybackSession(
        profile=profile,
        target=target,
        backend=create_backend(name),
        own_pid=own_pid,
        dry_run=False,
    )
    before = dummy.presses
    session.start()
    deadline = time.time() + 2.0
    while time.time() < deadline and dummy.presses < before + 3:
        QApplication.processEvents()
        time.sleep(0.005)
    session.stop()
    session.wait(2000)
    delivered = dummy.presses >= before + 3
    print(
        f"{name:>10}: replay {'PASS' if delivered else 'FAIL'} — "
        f"{dummy.presses - before} click(s) delivered, sent={session.summary().get('sent', 0)}"
    )
    return delivered


def main() -> int:
    app = QApplication(sys.argv)
    dummy = DummyTarget()
    dummy.show()
    dummy.raise_()
    dummy.activateWindow()
    for _ in range(10):
        app.processEvents()
        time.sleep(0.02)

    original = win32.get_cursor_pos()
    x, y = dummy.center()
    if not win32.user32.SetCursorPos(x, y):
        print("FAIL: could not move the cursor onto the dummy window")
        return 1
    # A first physical SendInput click on an inactive window can be consumed
    # by activation, so make the dummy foreground before measuring delivery.
    win32.user32.SetForegroundWindow(int(dummy.winId()))
    for _ in range(8):
        app.processEvents()
        time.sleep(0.01)

    # The dummy belongs to this test process, so it is intentionally not treated
    # as the clicker's own window (own_pid is the GUI app, not the harness).
    passed = run_backend("background", dummy, own_pid=0)
    passed = run_backend("foreground", dummy, own_pid=0) and passed
    passed = run_replay("background", dummy, own_pid=0) and passed
    passed = run_replay("foreground", dummy, own_pid=0) and passed

    win32.user32.SetCursorPos(*original)
    QTimer.singleShot(0, app.quit)
    app.exec()
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
