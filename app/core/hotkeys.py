"""Global hotkeys via RegisterHotKey on a dedicated Win32 message-loop thread."""

from __future__ import annotations

import ctypes
import threading

from PySide6.QtCore import QThread, Signal

from . import win32
from .binds import BindSet, BIND_ACTIONS, key_to_vk, is_mouse_key

WM_APP_ENABLE = 0x8000 + 1
WM_APP_DISABLE = 0x8000 + 2
_HOTKEY_ID_BASE = 200


class HotkeyManager(QThread):
    triggered = Signal(str)
    log = Signal(str, str)
    registration = Signal(list, dict)  # failed actions, Ctrl+key fallbacks in use

    def __init__(self, binds: BindSet, parent=None, skip_actions: set[str] | None = None):
        super().__init__(parent)
        self.binds = binds
        self.skip_actions = set(skip_actions or ())
        self._thread_id = 0
        self._ready = threading.Event()
        self._ack = threading.Event()
        self._enabled = True
        self._actions: dict[int, str] = {}
        self._registered: dict[int, str] = {}
        self.failed_actions: set[str] = set()
        self.fallback_hotkeys: dict[str, str] = {}

    def wait_ready(self, timeout: float = 0.6) -> bool:
        return self._ready.wait(timeout)

    def _post(self, message: int) -> None:
        if self._thread_id:
            win32.user32.PostThreadMessageW(self._thread_id, message, 0, 0)

    def run(self) -> None:
        self._thread_id = int(win32.kernel32.GetCurrentThreadId())
        self._ready.set()
        self._apply_enabled()
        msg = win32.wintypes.MSG()
        while True:
            ret = win32.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break
            if msg.message == win32.WM_HOTKEY:
                action = self._actions.get(int(msg.wParam))
                if action:
                    self.triggered.emit(action)
            elif msg.message == WM_APP_ENABLE:
                self._apply_enabled()
                self._ack.set()
            elif msg.message == WM_APP_DISABLE:
                self._unregister_all()
                self._ack.set()
            win32.user32.TranslateMessage(ctypes.byref(msg))
            win32.user32.DispatchMessageW(ctypes.byref(msg))
        self._unregister_all()

    def _unregister_all(self) -> None:
        for hotkey_id in list(self._registered):
            win32.user32.UnregisterHotKey(None, hotkey_id)
        self._registered.clear()
        self._actions.clear()

    def _apply_enabled(self) -> None:
        self._unregister_all()
        if not self._enabled:
            return
        failures: list[str] = []
        registration: list[str] = []
        self.failed_actions = set()
        self.fallback_hotkeys = {}
        for offset, action in enumerate(BIND_ACTIONS):
            if action in self.skip_actions or action == "trigger":
                continue
            key = self.binds.get(action)
            if is_mouse_key(key):
                failures.append(f"{key} ({action}): mouse buttons cannot be registered as Win32 hotkeys")
                self.failed_actions.add(action)
                continue
            vk = key_to_vk(key)
            if vk is None:
                failures.append(f"{key} ({action}): unsupported key")
                self.failed_actions.add(action)
                continue
            hotkey_id = _HOTKEY_ID_BASE + offset
            if win32.user32.RegisterHotKey(None, hotkey_id, win32.MOD_NOREPEAT, vk):
                self._registered[hotkey_id] = action
                self._actions[hotkey_id] = action
                registration.append(f"{key} {action}")
                continue
            error = ctypes.get_last_error()
            fallback_id = hotkey_id + 100
            if win32.user32.RegisterHotKey(
                None, fallback_id, win32.MOD_NOREPEAT | win32.MOD_CONTROL, vk
            ):
                self._registered[fallback_id] = action
                self._actions[fallback_id] = action
                self.fallback_hotkeys[action] = f"CTRL+{key}"
                self.log.emit(
                    "warn",
                    f"Hotkey {key} ({action}) is held by another application "
                    f"(Win32 error {error}); using CTRL+{key} as the global fallback.",
                )
                continue
            self.failed_actions.add(action)
            failures.append(
                f"{key} ({action}): already in use by another application "
                f"(Win32 error {error})"
            )
        self.registration.emit(sorted(self.failed_actions), dict(self.fallback_hotkeys))
        if registration:
            self.log.emit("info", "Hotkeys ready — " + " · ".join(registration))
        for failure in failures:
            self.log.emit("warn", "Hotkey register failed — " + failure)

    def set_enabled(self, enabled: bool) -> None:
        if not self.isRunning():
            self._enabled = enabled
            return
        self._enabled = enabled
        self._ack.clear()
        self._post(WM_APP_ENABLE if enabled else WM_APP_DISABLE)
        self._ack.wait(0.4)

    def pause(self) -> None:
        self.set_enabled(False)

    def resume(self) -> None:
        self.set_enabled(True)

    def stop(self) -> None:
        if self._thread_id:
            win32.user32.PostThreadMessageW(self._thread_id, win32.WM_QUIT, 0, 0)
        self.wait(1200)
