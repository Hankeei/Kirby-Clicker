"""Persisted UI settings (auto-clicker bounds, compact mode, music, geometry)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


VALID_BUTTONS = ("left", "right", "middle")
VALID_METHODS = ("blatant", "gaussian", "poisson", "gaussian_poisson", "static")
VALID_BACKENDS = ("foreground", "background")
DEFAULT_SIGMA = 0.15
MIN_SIGMA = 0.05
MAX_SIGMA = 0.40
DEFAULT_MUSIC_VOLUME = 0.05


def _as_bool(value, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _as_float(value, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _geometry(value) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        numbers = [int(v) for v in value]
    except (TypeError, ValueError):
        return None
    if numbers[2] < 320 or numbers[3] < 240:
        return None
    return numbers


def _position(value) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        return [int(v) for v in value]
    except (TypeError, ValueError):
        return None


@dataclass
class AppSettings:
    auto_min_cps: float = 8.0
    auto_max_cps: float = 14.0
    auto_button: str = "left"
    auto_method: str = "blatant"
    auto_sigma: float = DEFAULT_SIGMA
    click_backend: str = "foreground"
    active_tab: int = 0
    compact_enabled: bool = False
    music_enabled: bool = True
    music_volume: float = DEFAULT_MUSIC_VOLUME
    window_geometry: list[int] | None = None
    compact_pos: list[int] | None = None
    path: Path | None = field(default=None, repr=False, compare=False)

    def normalise(self) -> "AppSettings":
        self.auto_min_cps = min(max(_as_float(self.auto_min_cps, 8.0), 1.0), 50.0)
        self.auto_max_cps = min(max(_as_float(self.auto_max_cps, 14.0), 1.0), 50.0)
        if self.auto_min_cps > self.auto_max_cps:
            self.auto_min_cps, self.auto_max_cps = self.auto_max_cps, self.auto_min_cps
        if self.auto_button not in VALID_BUTTONS:
            self.auto_button = "left"
        if self.auto_method not in VALID_METHODS:
            self.auto_method = "blatant"
        if self.click_backend not in VALID_BACKENDS:
            self.click_backend = "foreground"
        sigma = _as_float(self.auto_sigma, DEFAULT_SIGMA)
        self.auto_sigma = min(max(sigma, MIN_SIGMA), MAX_SIGMA)
        try:
            self.active_tab = 1 if int(self.active_tab) == 1 else 0
        except (TypeError, ValueError):
            self.active_tab = 0
        self.compact_enabled = bool(self.compact_enabled)
        self.music_enabled = _as_bool(self.music_enabled, True)
        try:
            volume = float(self.music_volume)
        except (TypeError, ValueError):
            volume = DEFAULT_MUSIC_VOLUME
        self.music_volume = min(max(volume, 0.0), 1.0)
        self.window_geometry = _geometry(self.window_geometry)
        self.compact_pos = _position(self.compact_pos)
        return self


def load_settings(path: str | Path) -> AppSettings:
    path = Path(path)
    settings = AppSettings(path=path)
    if not path.exists():
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return settings
    if not isinstance(raw, dict):
        return settings
    known = {f.name for f in fields(AppSettings)} - {"path"}
    for key in known:
        if key in raw:
            setattr(settings, key, raw[key])
    return settings.normalise()


def save_settings(path: str | Path, settings: AppSettings) -> None:
    path = Path(path)
    settings.normalise()
    payload = {key: value for key, value in asdict(settings).items() if key != "path"}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
