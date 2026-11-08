# AGENTS.md — working on Kirby Clicker

Practical instructions for the next coding agent. The full context is in
[HANDOFF.md](HANDOFF.md); this file is the short version.

## Project shape

Windows-only PySide6 desktop app. No package/`pyproject.toml`, no CI. Entry point is
`main.py`; source lives in `app/core` (engine) and `app/ui` (widgets). Tests are plain
`unittest` modules under `tests/`. The build is a single PowerShell script, `build.ps1`.

```
main.py            Qt bootstrap + --selftest
app/core/          recorder, player, autoclicker, trigger, hotkeys, binds, settings,
                   profile, transfer, windows, backends, paths, win32
app/ui/            main_window, compact, dialogs, theme, widgets, music
tests/             144 unittest tests
tools/             verification scripts + screenshot/asset generators
assets/            mascots, cat.gif, luolei.mp3, pattern.png, icons
```

## Commands to run after any change

```powershell
py -3.13 -m unittest discover -s tests -q
py -3.13 tools/verify_dryrun.py
py -3.13 tools/verify_click_delivery.py
py -3.13 tools/verify_hotkeys.py
py -3.13 tools/verify_trigger.py
```

If you changed packaging, assets or anything imported at startup, also rebuild and run the
frozen check:

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
powershell -ExecutionPolicy Bypass -File .\build\verify_exe_env.ps1
```

Use `py -3.13` everywhere. Plain `python` here is 3.14 without PySide6 and will fail at import.
GUI/hook scripts need an interactive desktop; close stale `KirbyClicker` processes first.

## Conventions actually used here

- PySide6 only for UI; Win32 access is raw `ctypes` in `app/core/win32.py` (do not add pywin32).
- Engine code (`app/core`) stays importable without a `QApplication` where possible; Qt is used
  for `QThread`/signals only.
- Persistent structures are dataclasses (`AppSettings`, `BindSet`, `ClickProfile`, `Target`).
- Settings and profiles are written defensively: validate/clamp on load, fall back to defaults,
  write settings through a `.tmp` file + `os.replace`.
- UI text is sentence case except card headings (`RECORDER`, `PROFILES`), which use
  `panel_title_font()` and a `TitleRule` line.
- Colours and fonts come from `app/ui/theme.py`; do not hard-code new hex values in widgets.
- Tests are `unittest`, one behaviour per test, no network and no real input synthesis.

## Do not break

1. **ClickProfile v1 compatibility.** Keep the `# ClickProfile v1` header prefix and the
   `<hold_ms> <gap_ms>` lines. Legacy GMK/Record Clicker files must still load. Do not change
   `load_profile()` in a way that rejects files without `# data` or with an old header suffix.
2. **Stored method ids.** `settings.json` stores `blatant`, `gaussian`, `poisson`,
   `gaussian_poisson`, `static`. Display labels may change (`Random`, `Static ⚠`), ids must not.
   Renaming them requires a settings migration.
3. **Legacy data-folder migration.** `app/core/paths.py` copies `%LOCALAPPDATA%\GMKClicker` then
   `RecordClicker` into `%LOCALAPPDATA%\KirbyClicker` once, and only when the new folder is
   absent. Keep the env overrides `KIRBYCLICKER_DATA` / `GMKCLICKER_DATA` / `RECORD_CLICKER_DATA`.
4. **Frozen data location.** Packaged builds must keep writing to `%LOCALAPPDATA%\KirbyClicker`,
   never to PyInstaller's temporary `_MEIPASS`.
5. **Minimum layout.** `440×250` must not clip horizontally. It scrolls vertically by design;
   verify with `tests/test_ui_redesign.py` after layout changes.
6. **Profile actions.** Rename and Open folder belong to their own `PROFILES` card; the Record
   card holds only recording controls (v1.2 decision).

## Releases

Releases bump from **v1.2 onward**: next is v1.3 (patch for fixes, minor for features). The
version is manual — update `__version__` in `app/__init__.py`, commit, push, then create the
release with the REST API using the GCM token. `gh` is not installed and the MCP GitHub
connector cannot write. Full runbook: [HANDOFF.md §9](HANDOFF.md).

Documentation-only changes do not need a version bump or a release.
