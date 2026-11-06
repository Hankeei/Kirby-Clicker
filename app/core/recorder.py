"""Live recording: a pure click-state engine plus a WH_MOUSE_LL hook thread."""

from __future__ import annotations

import ctypes
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Signal

from . import win32
from .profile import Click, ClickProfile, median_gap

DOWN_MESSAGES = {
    win32.WM_LBUTTONDOWN: "left",
    win32.WM_RBUTTONDOWN: "right",
    win32.WM_MBUTTONDOWN: "middle",
}
UP_MESSAGES = {
    win32.WM_LBUTTONUP: "left",
    win32.WM_RBUTTONUP: "right",
    win32.WM_MBUTTONUP: "middle",
}


def now_ms() -> float:
    return time.perf_counter() * 1000.0


@dataclass
class RecorderSnapshot:
    count: int = 0
    cps_now: float = 0.0
    intervals_ms: list[float] = field(default_factory=list)
    duration_ms: float = 0.0
    current_hold_ms: float = 0.0
    ignored_own: int = 0
    ignored_outside: int = 0
    ignored_injected: int = 0
    ignored_other_button: int = 0
    held: bool = False


class RecorderEngine:
    """Consumes hook events and produces reference-format hold/gap pairs.

    Pure Python (no Win32, no Qt) so it can be unit-tested with synthetic events.
    """

    def __init__(self, button: str = "left", own_pid: int = 0, target_pid: int | None = None):
        self.button = button
        self.own_pid = own_pid
        self.target_pid = target_pid
        self._active = False
        self._start_ms = 0.0
        self._down_t: float | None = None
        self._down_times: list[float] = []
        self._pending_hold: int | None = None
        self._last_up_t: float | None = None
        self._clicks: list[Click] = []
        self.ignored_own = 0
        self.ignored_outside = 0
        self.ignored_injected = 0
        self.ignored_other_button = 0

    # -- lifecycle ---------------------------------------------------------
    def start(self, at_ms: float | None = None) -> None:
        self._active = True
        self._start_ms = now_ms() if at_ms is None else at_ms
        self._down_t = None
        self._down_times.clear()
        self._pending_hold = None
        self._last_up_t = None
        self._clicks.clear()
        self.ignored_own = self.ignored_outside = 0
        self.ignored_injected = self.ignored_other_button = 0

    def stop(self, at_ms: float | None = None) -> ClickProfile:
        at = now_ms() if at_ms is None else at_ms
        if self._down_t is not None:
            hold = max(1, int(round(at - self._down_t)))
            self._pending_hold = hold
            self._last_up_t = at
            self._down_t = None
        if self._pending_hold is not None:
            gaps = [c.gap_ms for c in self._clicks]
            gap = int(median_gap(self._clicks)) if gaps else 0
            self._clicks.append(Click(self._pending_hold, gap, self.button))
            self._pending_hold = None
        self._active = False
        return ClickProfile(clicks=list(self._clicks), button=self.button, name="recording")

    # -- event intake ------------------------------------------------------
    def _allowed(self, owner_pid: int, injected: bool) -> str | None:
        if injected:
            self.ignored_injected += 1
            return "injected"
        if owner_pid == self.own_pid:
            self.ignored_own += 1
            return "own_window"
        if owner_pid <= 0:
            self.ignored_outside += 1
            return "desktop"
        if self.target_pid is not None and owner_pid != self.target_pid:
            self.ignored_outside += 1
            return "outside_target"
        return None

    def on_down(self, now: float, button: str, owner_pid: int, injected: bool = False) -> bool:
        if not self._active:
            return False
        if button != self.button:
            self.ignored_other_button += 1
            return False
        if self._allowed(owner_pid, injected):
            return False
        if self._down_t is not None:
            return False  # duplicate down, ignore
        if self._pending_hold is not None and self._last_up_t is not None:
            gap = max(0, int(round(now - self._last_up_t)))
            self._clicks.append(Click(self._pending_hold, gap, self.button))
            self._pending_hold = None
        self._down_t = now
        self._down_times.append(now)
        return True

    def on_up(self, now: float, button: str, owner_pid: int, injected: bool = False) -> bool:
        if not self._active or button != self.button or self._down_t is None:
            return False
        hold = max(1, int(round(now - self._down_t)))
        self._pending_hold = hold
        self._last_up_t = now
        self._down_t = None
        return True

    def snapshot(self, at_ms: float | None = None) -> RecorderSnapshot:
        at = now_ms() if at_ms is None else at_ms
        window_start = at - 1000.0
        recent_times = [t for t in self._down_times if t >= window_start]
        intervals = [
            round(self._down_times[i] - self._down_times[i - 1], 1)
            for i in range(max(1, len(self._down_times) - 49), len(self._down_times))
        ]
        current_hold = (at - self._down_t) if self._down_t is not None else 0.0
        return RecorderSnapshot(
            count=len(self._down_times),
            cps_now=float(len(recent_times)),
            intervals_ms=intervals,
            duration_ms=max(0.0, at - self._start_ms),
            current_hold_ms=current_hold,
            ignored_own=self.ignored_own,
            ignored_outside=self.ignored_outside,
            ignored_injected=self.ignored_injected,
            ignored_other_button=self.ignored_other_button,
            held=self._down_t is not None,
        )


class MouseHookThread(QThread):
    """Owns the low-level mouse hook and its message loop.

    Only button events are forwarded to the GUI; mouse moves are dropped inside
    the C callback so the Qt event queue never floods.
    """

    button_event = Signal(object)
    hook_error = Signal(str)

    def __init__(self, own_pid: int, parent=None):
        super().__init__(parent)
        self.own_pid = own_pid
        self._thread_id = 0
        self._hook = None
        self._callback = win32.HOOKPROC(self._hook_proc)
        self._running = False

    def _hook_proc(self, n_code, w_param, l_param):
        try:
            if n_code == win32.HC_ACTION:
                message = int(w_param)
                button = None
                kind = None
                if message in DOWN_MESSAGES:
                    button = DOWN_MESSAGES[message]
                    kind = "down"
                elif message in UP_MESSAGES:
                    button = UP_MESSAGES[message]
                    kind = "up"
                else:
                    return win32.user32.CallNextHookEx(self._hook, n_code, w_param, l_param)

                data = ctypes.cast(l_param, ctypes.POINTER(win32.MSLLHOOKSTRUCT)).contents
                x, y = int(data.pt.x), int(data.pt.y)
                deep_hwnd, root_hwnd, owner_pid = win32.window_under_point(x, y)
                self.button_event.emit(
                    {
                        "kind": kind,
                        "button": button,
                        "t_ms": now_ms(),
                        "x": x,
                        "y": y,
                        "owner_pid": owner_pid,
                        "hwnd": root_hwnd,
                        "injected": bool(data.flags & win32.LLMHF_INJECTED),
                    }
                )
        except Exception:
            pass
        return win32.user32.CallNextHookEx(self._hook, n_code, w_param, l_param)

    def run(self) -> None:
        self._thread_id = int(win32.kernel32.GetCurrentThreadId())
        module = win32.kernel32.GetModuleHandleW(None)
        self._hook = win32.user32.SetWindowsHookExW(win32.WH_MOUSE_LL, self._callback, module, 0)
        if not self._hook:
            self.hook_error.emit(f"Could not install WH_MOUSE_LL hook (Win32 error {ctypes.get_last_error()})")
            return
        self._running = True
        msg = win32.wintypes.MSG()
        try:
            while True:
                ret = win32.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret <= 0:
                    break
                win32.user32.TranslateMessage(ctypes.byref(msg))
                win32.user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self._running = False
            if self._hook:
                win32.user32.UnhookWindowsHookEx(self._hook)
                self._hook = None

    def stop(self) -> None:
        if self._thread_id:
            win32.user32.PostThreadMessageW(self._thread_id, win32.WM_QUIT, 0, 0)
        self.wait(1500)
