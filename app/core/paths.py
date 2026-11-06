"""Where Kirby Clicker keeps binds, settings and profiles.

Source checkout: the project root (so the existing bind file keeps working).
Packaged one-file exe: %LOCALAPPDATA%\\KirbyClicker, because PyInstaller's
temporary extraction directory is read-only and disappears on exit.  If an old
%LOCALAPPDATA%\\GMKClicker (or the older RecordClicker) folder exists and the
new one does not, its contents are copied across once so existing
binds/profiles/settings are kept.

Set KIRBYCLICKER_DATA (or the legacy GMKCLICKER_DATA / RECORD_CLICKER_DATA)
to override the directory; the verification tools use this.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_DIR_NAME = "KirbyClicker"
LEGACY_DIR_NAMES = ("GMKClicker", "RecordClicker")
_ENV_OVERRIDES = ("KIRBYCLICKER_DATA", "GMKCLICKER_DATA", "RECORD_CLICKER_DATA")

_migrated_from: Path | None = None


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def asset_path(name: str) -> Path:
    """Bundled read-only asset (icon, README); PyInstaller puts them in _MEIPASS."""
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        return base / "assets" / name
    return project_root() / "assets" / name


def app_icon_path() -> Path:
    """Qt reads PNG natively; the .ico remains the executable/taskbar resource."""
    png = asset_path("icon.png")
    return png if png.exists() else asset_path("icon.ico")


def _local_appdata() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    return Path(root) if root else Path.home() / "AppData" / "Local"


def migration_source() -> Path | None:
    """The legacy folder copied into the new data directory, if any."""
    return _migrated_from


def _migrate_legacy(old: Path, new: Path) -> None:
    global _migrated_from
    if _migrated_from is not None or not old.is_dir() or new.exists():
        return
    try:
        shutil.copytree(old, new)
        _migrated_from = old
    except OSError:
        # A failed migration must never stop the app; it just starts empty.
        pass


def data_directory() -> Path:
    override = next((os.environ[k] for k in _ENV_OVERRIDES if os.environ.get(k)), None)
    if override:
        path = Path(override).expanduser()
    elif is_frozen():
        path = _local_appdata() / APP_DIR_NAME
        for legacy in LEGACY_DIR_NAMES:
            if path.exists():
                break
            _migrate_legacy(_local_appdata() / legacy, path)
    else:
        path = project_root()
    path.mkdir(parents=True, exist_ok=True)
    return path
