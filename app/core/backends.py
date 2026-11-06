"""Swappable click-delivery backends.

Both backends click at the *current cursor position*.  Coordinates are not
stored in the v1 profile, so the cursor is the source of truth.

* ForegroundBackend  - SendInput hardware events (works with raw-input games,
  steals focus on click because Windows activates the window).
* PostMessageBackend - WM_xBUTTON messages posted to the window under the
  cursor (does not move the cursor or change focus; ignored by many games and
  some protected/child windows).
"""

from __future__ import annotations

from dataclasses import dataclass

from . import win32


@dataclass(frozen=True)
class ClickResult:
    ok: bool
    reason: str = ""


OK = ClickResult(True)


class ClickBackend:
    name = "backend"
    description = ""

    def press(self, button: str, target, own_pid: int) -> ClickResult:  # pragma: no cover - interface
        raise NotImplementedError

    def release(self, button: str) -> ClickResult:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:
        pass


class _CursorGuard:
    """Shared target/own-window validation for cursor-position clicks."""

    @staticmethod
    def resolve(target, own_pid: int) -> tuple[int, int, ClickResult]:
        x, y = win32.get_cursor_pos()
        deep_hwnd, root_hwnd, root_pid = win32.window_under_point(x, y)
        if not deep_hwnd:
            return 0, 0, ClickResult(False, "no window under the cursor")
        deep_pid = win32.window_pid(deep_hwnd)
        if deep_pid == own_pid or root_pid == own_pid:
            return 0, 0, ClickResult(False, "cursor is over Kirby Clicker itself")
        if target.any_process:
            return deep_hwnd, 0, OK
        if deep_pid != target.pid or root_pid != target.pid:
            exe = win32.process_exe(deep_pid) or "another process"
            return 0, 0, ClickResult(False, f"cursor is over {exe}, not {target.exe}")
        return deep_hwnd, root_hwnd, OK


class ForegroundBackend(ClickBackend, _CursorGuard):
    name = "foreground"
    description = "SendInput hardware click at the cursor (most compatible; takes focus)"

    def __init__(self):
        self._held_button: str | None = None

    def press(self, button: str, target, own_pid: int) -> ClickResult:
        _deep, _root, result = self.resolve(target, own_pid)
        if not result.ok:
            return result
        if not win32.send_mouse_button(button, True):
            return ClickResult(False, "SendInput was rejected")
        self._held_button = button
        return OK

    def release(self, button: str) -> ClickResult:
        if self._held_button is None:
            return OK
        win32.send_mouse_button(button, False)
        self._held_button = None
        return OK

    def close(self) -> None:
        if self._held_button:
            win32.send_mouse_button(self._held_button, False)
            self._held_button = None


class PostMessageBackend(ClickBackend, _CursorGuard):
    name = "background"
    description = "PostMessage WM_xBUTTON to the window under the cursor (no focus change)"

    def __init__(self):
        self._hwnd = 0
        self._point = (0, 0)
        self._held_button: str | None = None

    def press(self, button: str, target, own_pid: int) -> ClickResult:
        deep_hwnd, _root, result = self.resolve(target, own_pid)
        if not result.ok:
            return result
        x, y = win32.get_cursor_pos()
        if not win32.post_mouse_message(deep_hwnd, button, True, x, y):
            return ClickResult(False, "PostMessage failed (window may be elevated or hung)")
        self._hwnd = deep_hwnd
        self._point = (x, y)
        self._held_button = button
        return OK

    def release(self, button: str) -> ClickResult:
        if self._held_button is None:
            return OK
        hwnd, (x, y) = self._hwnd, self._point
        self._held_button = None
        self._hwnd = 0
        if not hwnd or not win32.is_window(hwnd):
            return OK
        win32.post_mouse_message(hwnd, button, False, x, y)
        return OK

    def close(self) -> None:
        if self._held_button:
            self.release(self._held_button)


class NullBackend(ClickBackend, _CursorGuard):
    """Used by dry-run previews and unit tests: validates nothing, clicks nothing."""

    name = "null"
    description = "no clicks"

    def press(self, button: str, target, own_pid: int) -> ClickResult:
        return OK

    def release(self, button: str) -> ClickResult:
        return OK


BACKENDS = {
    "foreground": ("Foreground — SendInput", "Hardware click at the cursor. Needed by games/raw input, but takes focus."),
    "background": ("Background — PostMessage", "Posts clicks to the target window. No focus change; ignored by some apps/games."),
}


def create_backend(name: str) -> ClickBackend:
    if name == "background":
        return PostMessageBackend()
    return ForegroundBackend()
