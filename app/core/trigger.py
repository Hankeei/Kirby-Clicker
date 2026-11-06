"""Master arm state and the physical mouse-button hold trigger.

The clicker has one master arm/disarm flag (toggled by the arm hotkey).  While
it is armed, holding the configured mouse button makes clicks fire; releasing
it stops them.  A ``WH_MOUSE_LL`` hook reports the physical down/up events and
ignores injected input (including this app's own synthetic clicks) so playback
can never re-trigger itself.
"""

from __future__ import annotations

import ctypes
import threading

from PySide6.QtCore import QThread, Signal

from . import win32
from .binds import canonical_key, is_mouse_key

DOWN_MESSAGES = {
    win32.WM_LBUTTONDOWN: "MOUSE1",
    win32.WM_RBUTTONDOWN: "MOUSE2",
    win32.WM_MBUTTONDOWN: "MOUSE3",
    win32.WM_XBUTTONDOWN: None,
}
UP_MESSAGES = {
    win32.WM_LBUTTONUP: "MOUSE1",
    win32.WM_RBUTTONUP: "MOUSE2",
    win32.WM_MBUTTONUP: "MOUSE3",
    win32.WM_XBUTTONUP: None,
}

BUTTON_LABELS = {
    "MOUSE1": "LEFT MOUSE",
    "MOUSE2": "RIGHT MOUSE",
    "MOUSE3": "MIDDLE MOUSE",
    "MOUSE4": "XBUTTON1",
    "MOUSE5": "XBUTTON2",
}


def button_label(key: str) -> str:
    try:
        key = canonical_key(key)
    except Exception:  # noqa: BLE001 - display only
        return str(key)
    return BUTTON_LABELS.get(key, key)


def _xbutton_name(mouse_data: int) -> str:
    """MOUSE4/MOUSE5 from the high word of MSLLHOOKSTRUCT.mouseData."""
    return "MOUSE4" if (int(mouse_data) >> 16) & 0xFFFF == 1 else "MOUSE5"


class MouseButtonTracker:
    """Pure down/up state for one physical mouse button."""

    def __init__(self, button: str = "MOUSE1"):
        self.button = canonical_key(button)
        self.down = False

    def reset(self) -> None:
        self.down = False

    def handle(self, button: str, down: bool, injected: bool = False) -> str | None:
        """Return 'press', 'release' or None for other buttons / repeats / injected."""
        if injected or not is_mouse_key(button):
            return None
        if canonical_key(button) != self.button:
            return None
        if down:
            if self.down:
                return None  # duplicate down (held button)
            self.down = True
            return "press"
        if not self.down:
            return None  # release without a matching press
        self.down = False
        return "release"


class ArmState:
    """One master arm/disarm flag plus the live 'clicking' flag for the UI."""

    def __init__(self, armed: bool = False, clicking: bool = False):
        self.armed = bool(armed)
        self.clicking = bool(clicking)

    def toggle(self) -> bool:
        self.armed = not self.armed
        if not self.armed:
            self.clicking = False
        return self.armed

    def disarm(self) -> None:
        self.armed = False
        self.clicking = False

    def label(self, button_key: str = "MOUSE1") -> str:
        """The single ON/OFF state word used by the window, buttons and overlay."""
        return "ON" if self.armed else "OFF"


def resolve_trigger_kind(
    *, armed: bool, recording: bool, busy: bool, tab_index: int
) -> str | None:
    """Which clicker should run on a trigger press, or None when it must not."""
    if not armed or recording or busy:
        return None
    return "auto" if tab_index == 1 else "profile"


class MouseButtonMonitor(QThread):
    """WH_MOUSE_LL hook that reports physical presses of one mouse button.

    Events always pass through to the focused application: the hook never
    swallows input. Presses that land on this app's own windows are ignored so
    clicking the GUI cannot start a playback.
    """

    pressed = Signal()
    released = Signal()
    hook_error = Signal(str)

    def __init__(self, button: str, own_pid: int, parent=None):
        super().__init__(parent)
        self.button = button
        self.own_pid = own_pid
        self._tracker = MouseButtonTracker(button)
        self._callback = win32.HOOKPROC(self._hook_proc)
        self._thread_id = 0
        self._hook = None
        self._ready = threading.Event()

    def wait_ready(self, timeout: float = 0.6) -> bool:
        return self._ready.wait(timeout)

    def _hook_proc(self, n_code, w_param, l_param):
        try:
            if n_code == win32.HC_ACTION:
                message = int(w_param)
                if message in DOWN_MESSAGES or message in UP_MESSAGES:
                    data = ctypes.cast(
                        l_param, ctypes.POINTER(win32.MSLLHOOKSTRUCT)
                    ).contents
                    name = DOWN_MESSAGES.get(message) or UP_MESSAGES.get(message)
                    if name is None:
                        name = _xbutton_name(data.mouseData)
                    down = message in DOWN_MESSAGES
                    injected = bool(
                        data.flags
                        & (win32.LLMHF_INJECTED | win32.LLMHF_LOWER_IL_INJECTED)
                    )
                    action = self._tracker.handle(name, down, injected)
                    if action == "press":
                        _, _root, pid = win32.window_under_point(
                            int(data.pt.x), int(data.pt.y)
                        )
                        if pid != self.own_pid:
                            self.pressed.emit()
                    elif action == "release":
                        self.released.emit()
        except Exception:
            pass
        # Never swallow mouse input.
        return win32.user32.CallNextHookEx(self._hook, n_code, w_param, l_param)

    def run(self) -> None:
        self._thread_id = int(win32.kernel32.GetCurrentThreadId())
        module = win32.kernel32.GetModuleHandleW(None)
        self._hook = win32.user32.SetWindowsHookExW(
            win32.WH_MOUSE_LL, self._callback, module, 0
        )
        self._ready.set()
        if not self._hook:
            self.hook_error.emit(
                f"Could not install WH_MOUSE_LL hook (Win32 error {ctypes.get_last_error()})"
            )
            return
        msg = win32.wintypes.MSG()
        try:
            while True:
                ret = win32.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret <= 0:
                    break
                win32.user32.TranslateMessage(ctypes.byref(msg))
                win32.user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if self._hook:
                win32.user32.UnhookWindowsHookEx(self._hook)
                self._hook = None

    def stop(self) -> None:
        if self._thread_id:
            win32.user32.PostThreadMessageW(self._thread_id, win32.WM_QUIT, 0, 0)
        self.wait(1500)
