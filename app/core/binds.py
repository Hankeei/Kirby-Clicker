"""Read/write the reference ``*_binds.txt`` key map."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

BIND_ACTIONS = ("record", "toggle", "trigger", "quit", "rebind", "selector")

ACTION_LABELS = {
    "record": "Record",
    "toggle": "Arm / disarm clicker",
    "trigger": "Hold-to-click button (mouse)",
    "quit": "Stop / quit",
    "rebind": "Edit binds",
    "selector": "Pick process",
}

DEFAULT_TEXT = """# Kirby Clicker keybinds
# Keys: A-Z, 0-9, F1-F24, NUMPAD0-NUMPAD9, SPACE, TAB, INSERT, DELETE, HOME, END,
#       PAGEUP, PAGEDOWN, arrows, LSHIFT, LCTRL, LALT (keyboard keys only)
# Mouse buttons (trigger only): MOUSE1 (left), MOUSE2 (right), MOUSE3 (middle),
#       MOUSE4 / MOUSE5 (side buttons)
record=F8
toggle=F9
trigger=MOUSE1
quit=F12
rebind=INSERT
selector=F10
# toggle = arm / disarm the clicker (press once to arm, again to disarm)
# trigger = physical mouse button held down to fire clicks while armed
# scope = restricted (selected app only) or anywhere (cursor window)
scope=anywhere
# target = executable used by restricted scope (empty = no target selected)
target=
"""


class BindError(ValueError):
    pass


_VK: dict[str, int] = {
    "SPACE": 0x20,
    "TAB": 0x09,
    "ENTER": 0x0D,
    "ESC": 0x1B,
    "BACKSPACE": 0x08,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
    "HOME": 0x24,
    "END": 0x23,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
    "UP": 0x26,
    "DOWN": 0x28,
    "LEFT": 0x25,
    "RIGHT": 0x27,
    "LSHIFT": 0xA0,
    "RSHIFT": 0xA1,
    "LCTRL": 0xA2,
    "RCTRL": 0xA3,
    "LALT": 0xA4,
    "RALT": 0xA5,
}
for _i in range(1, 25):
    _VK[f"F{_i}"] = 0x6F + _i
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    _VK[_c] = ord(_c)
for _d in range(10):
    _VK[str(_d)] = 0x30 + _d
    _VK[f"NUMPAD{_d}"] = 0x60 + _d

_ALIASES = {
    "ESCAPE": "ESC",
    "RETURN": "ENTER",
    "DEL": "DELETE",
    "INS": "INSERT",
    "PGUP": "PAGEUP",
    "PGDN": "PAGEDOWN",
    "CTRL": "LCTRL",
    "SHIFT": "LSHIFT",
    "ALT": "LALT",
}
for _d in range(10):
    _ALIASES[f"NUM{_d}"] = f"NUMPAD{_d}"

MOUSE_KEYS = {"MOUSE1", "MOUSE2", "MOUSE3", "MOUSE4", "MOUSE5"}
_ALIASES.update(
    {
        "LMB": "MOUSE1",
        "LEFTMOUSE": "MOUSE1",
        "MOUSELEFT": "MOUSE1",
        "RMB": "MOUSE2",
        "RIGHTMOUSE": "MOUSE2",
        "MOUSEMIDDLE": "MOUSE3",
        "MMB": "MOUSE3",
    }
)


def canonical_key(value: str) -> str:
    key = (value or "").strip().upper()
    key = _ALIASES.get(key, key)
    if key in _VK or key in MOUSE_KEYS:
        return key
    raise BindError(f"Unsupported key: {value!r}")


def key_to_vk(key: str) -> int | None:
    try:
        key = canonical_key(key)
    except BindError:
        return None
    return _VK.get(key)


def is_mouse_key(key: str) -> bool:
    try:
        return canonical_key(key) in MOUSE_KEYS
    except BindError:
        return False


def key_name_from_vk(vk: int) -> str | None:
    for name, value in _VK.items():
        if value == vk:
            return name
    return None


@dataclass
class BindSet:
    record: str = "F8"
    toggle: str = "F9"
    trigger: str = "MOUSE1"
    quit: str = "F12"
    rebind: str = "INSERT"
    selector: str = "F10"
    scope: str = "anywhere"
    target_exe: str = ""
    path: Path | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def get(self, action: str) -> str:
        return getattr(self, action)

    def set(self, action: str, key: str) -> None:
        if action not in BIND_ACTIONS:
            raise BindError(f"Unknown action: {action}")
        setattr(self, action, canonical_key(key))

    def validate(self) -> None:
        if self.scope not in ("restricted", "anywhere"):
            raise BindError(f"Unknown click scope: {self.scope!r}")
        seen: dict[str, str] = {}
        for action in BIND_ACTIONS:
            key = canonical_key(self.get(action))
            if action == "trigger":
                if not is_mouse_key(key):
                    raise BindError(
                        "Hold-to-click trigger must be a mouse button "
                        "(MOUSE1, MOUSE2, MOUSE3, MOUSE4 or MOUSE5)."
                    )
            elif is_mouse_key(key):
                raise BindError(
                    f"Mouse button {key} cannot be a global hotkey ({action}); "
                    "only the trigger can be a mouse button."
                )
            if key in seen:
                previous = seen[key]
                raise BindError(f"Duplicate bind: {key} used by {previous} and {action}")
            seen[key] = action

    def hotkeys(self) -> list[tuple[str, int]]:
        """Keys registered with RegisterHotKey; the mouse trigger uses a hook."""
        result = []
        for action in BIND_ACTIONS:
            if action == "trigger":
                continue
            vk = key_to_vk(self.get(action))
            if vk is not None:
                result.append((action, vk))
        return result

    def mouse_actions(self) -> list[tuple[str, str]]:
        """Mouse bindings that cannot be global hotkeys (the trigger is exempt)."""
        result = []
        for action in BIND_ACTIONS:
            if action == "trigger":
                continue
            key = canonical_key(self.get(action))
            if is_mouse_key(key):
                result.append((action, key))
        return result

    def first_mouse_action(self) -> tuple[str, str] | None:
        found = self.mouse_actions()
        return found[0] if found else None


def load_binds(path: str | Path) -> BindSet:
    path = Path(path)
    binds = BindSet(path=path)
    if not path.exists():
        return binds
    scope_seen = False
    hold_seen = False
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise BindError(f"Could not read {path}: {exc}") from exc
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "target":
            binds.target_exe = value
        elif key == "scope":
            scope = value.lower()
            if scope not in ("restricted", "anywhere"):
                raise BindError(
                    f"Line {lineno}: scope must be 'restricted' or 'anywhere', got {value!r}"
                )
            binds.scope = scope
            scope_seen = True
        elif key == "hold":
            # Legacy press-and-hold key. Only a mouse button can become the
            # trigger in the new model; keyboard values are ignored.
            hold_seen = True
            try:
                value_key = canonical_key(value)
            except BindError:
                value_key = ""
            if is_mouse_key(value_key):
                binds.trigger = value_key
        elif key in BIND_ACTIONS:
            try:
                binds.set(key, value)
            except BindError as exc:
                raise BindError(f"Line {lineno}: {exc}") from exc
        else:
            binds.extra[key] = value
    if not hold_seen and binds.trigger not in MOUSE_KEYS:
        binds.trigger = "MOUSE1"
    if not scope_seen:
        binds.scope = "restricted" if binds.target_exe else "anywhere"
    return binds


def save_binds(path: str | Path, binds: BindSet) -> None:
    path = Path(path)
    binds.validate()
    lines = [
        "# Kirby Clicker keybinds",
        "# Keys: A-Z, 0-9, F1-F24, NUMPAD0-NUMPAD9, SPACE, TAB, INSERT, DELETE, HOME, END,",
        "#       PAGEUP, PAGEDOWN, arrows, LSHIFT, LCTRL, LALT (keyboard keys only)",
        "# Mouse buttons (trigger only): MOUSE1 left, MOUSE2 right, MOUSE3 middle,",
        "#       MOUSE4 / MOUSE5 side buttons",
    ]
    for action in BIND_ACTIONS:
        lines.append(f"{action}={binds.get(action)}")
    lines.append("# toggle = arm / disarm the clicker (press once to arm, again to disarm)")
    lines.append("# trigger = physical mouse button held down to fire clicks while armed")
    lines.append("# scope = restricted (selected app only) or anywhere (cursor window)")
    lines.append(f"scope={binds.scope}")
    lines.append("# target = executable used by restricted scope (empty = no target selected)")
    lines.append(f"target={binds.target_exe}")
    for key, value in binds.extra.items():
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_bind_file(path: str | Path) -> BindSet:
    path = Path(path)
    if not path.exists():
        path.write_text(DEFAULT_TEXT, encoding="utf-8")
    return load_binds(path)
