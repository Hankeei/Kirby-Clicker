"""Exercise the Rust EXE against a dedicated dummy window (never a game).

Uses PySide6 only as a test target; the shipped EXE does not depend on Python/Qt.
Physical-device capture still requires a manual check.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from app.core import win32


class Target(QWidget):
    def __init__(self):
        super().__init__()
        self.down = self.up = 0
        self.setWindowTitle("Kirby Clicker Native Verification Target")
        self.setGeometry(180, 180, 420, 240)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        layout = QVBoxLayout(self)
        label = QLabel("Rust click delivery test\nClicks are confined to this window.")
        label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(label)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.down += 1

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.up += 1


def main() -> int:
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "dist/KirbyClicker.exe"
    app = QApplication([])
    target = Target()
    target.show()
    original = win32.get_cursor_pos()
    output = BASE / "build/native-input"
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    child = None
    try:
        for backend in ("background", "foreground"):
            target.down = target.up = 0
            target.raise_()
            target.activateWindow()
            for _ in range(10):
                app.processEvents()
                time.sleep(0.02)
            point = target.mapToGlobal(target.rect().center())
            win32.user32.SetCursorPos(point.x(), point.y())
            report_path = output / f"{backend}.json"
            report_path.unlink(missing_ok=True)
            env = os.environ.copy()
            env["KIRBYCLICKER_SELFTEST_OUT"] = str(report_path)
            child = subprocess.Popen([str(exe), "--verify-input", str(int(target.winId())), str(os.getpid()), backend], env=env)
            deadline = time.monotonic() + 15
            while child.poll() is None and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.003)
            if child.poll() is None:
                child.kill()
                child.wait()
                raise RuntimeError("Native verification timed out")
            for _ in range(10):
                app.processEvents()
                time.sleep(0.01)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            delivered = target.down == target.up and target.down >= 6
            report.update(delivered_down=target.down, delivered_up=target.up, delivery_pass=delivered, exit_code=child.returncode)
            reports.append(report)
            print(json.dumps(report, ensure_ascii=False))
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.wait()
        win32.user32.SetCursorPos(*original)
        target.close()
    (output / "results.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    return 0 if all(r.get("ok") and r["delivery_pass"] and r["exit_code"] == 0 for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
