"""Visible top-level window enumeration and the playback Target model."""

from __future__ import annotations

from dataclasses import dataclass

from . import win32


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    pid: int
    exe: str
    title: str


@dataclass(frozen=True)
class Target:
    any_process: bool = True
    hwnd: int = 0
    pid: int = 0
    exe: str = ""
    title: str = ""

    @classmethod
    def any_target(cls) -> "Target":
        return cls(any_process=True)

    @classmethod
    def from_window(cls, window: WindowInfo) -> "Target":
        return cls(
            any_process=False,
            hwnd=window.hwnd,
            pid=window.pid,
            exe=window.exe,
            title=window.title,
        )

    @property
    def label(self) -> str:
        if self.any_process:
            return "Any process"
        return f"{self.exe} — {self.title}" if self.exe else (self.title or "selected window")

    @property
    def short_label(self) -> str:
        return "any process" if self.any_process else (self.exe or "selected window")


def enumerate_visible_windows(own_pid: int) -> list[WindowInfo]:
    result: list[WindowInfo] = []
    seen: set[int] = set()

    @win32.WNDENUMPROC
    def callback(hwnd, _lparam):
        hwnd = int(hwnd)
        if hwnd in seen:
            return True
        if not win32.user32.IsWindowVisible(hwnd):
            return True
        title = win32.window_title(hwnd)
        if not title.strip():
            return True
        pid = win32.window_pid(hwnd)
        if not pid or pid == own_pid:
            return True
        exstyle = win32.user32.GetWindowLongW(hwnd, win32.GWL_EXSTYLE)
        if exstyle & win32.WS_EX_TOOLWINDOW:
            return True
        if win32.is_cloaked(hwnd):
            return True
        exe = win32.process_exe(pid)
        if not exe:
            exe = f"pid {pid}"
        seen.add(hwnd)
        result.append(WindowInfo(hwnd=hwnd, pid=pid, exe=exe, title=title.strip()))
        return True

    win32.user32.EnumWindows(callback, 0)
    result.sort(key=lambda w: (w.exe.lower(), w.title.lower()))
    return result


def find_window_by_exe(windows: list[WindowInfo], exe: str) -> WindowInfo | None:
    target = (exe or "").strip().lower()
    if not target:
        return None
    for window in windows:
        if window.exe.lower() == target:
            return window
    # Be forgiving about a missing ".exe" suffix in a hand-edited bind file.
    stem = target[:-4] if target.endswith(".exe") else target
    for window in windows:
        if window.exe.lower().rsplit(".", 1)[0] == stem:
            return window
    return None


def owns_own_window(own_pid: int, x: int, y: int) -> bool:
    _hwnd, _root, pid = win32.window_under_point(x, y)
    return pid == own_pid
