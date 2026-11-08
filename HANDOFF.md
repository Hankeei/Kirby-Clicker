# Kirby Clicker — handoff for Codex

This document describes the project exactly as it is at **v1.2.0** (source commit `8a04fbd`).
It is written so an agent with no prior conversation can run, change, verify and release the app
without rediscovering the machine-specific details.

---

## 1. What Kirby Clicker is

A Windows-only desktop clicker with a claymorphism UI and Kirby mascots. It has two working
modes plus a compact overlay:

- **Recorder** — records real human clicks as *(hold_ms, gap_ms)* pairs, saves them in the
  `# ClickProfile v1` text format, and replays the same cadence. You arm the clicker once
  (default `F9`), then **hold** the configured mouse button (default left) to fire; releasing it
  stops immediately.
- **Auto** — a random-CPS auto-clicker with five timing methods, 1–50 CPS bounds, and a
  left/right/middle click button.
- **Compact overlay** — a 188×104 always-on-top frameless widget with the ON/OFF pill, method
  chip and equalizer. Optional background music loops `assets/luolei.mp3`.

Intended user: one person on Windows 10/11 who wants either a human-cadence click replay or a
configurable auto-clicker. It is not a library or a service, has no installer, and ships as an
unsigned one-file exe. It is **not** designed to defeat anti-cheat; hooks can be blocked by
protected or elevated applications.

---

## 2. Current version and release history

The version lives in [`app/__init__.py`](app/__init__.py): `__version__ = "1.2.0"`.

| Release | Tag commit | Published | Asset |
| --- | --- | --- | --- |
| v1.0 | `045d310` | 2026-11-07 | `KirbyClicker.exe`, 61,504,621 bytes |
| v1.1 | `752ea79` | 2026-11-07 | `KirbyClicker.exe`, 61,507,296 bytes |
| v1.2 | `8a04fbd` | 2026-11-07 | `KirbyClicker.exe`, 61,507,538 bytes |

Real release pages (private repo — anonymous visits return 404):

- https://github.com/Hankeei/Kirby-Clicker/releases/tag/v1.0
- https://github.com/Hankeei/Kirby-Clicker/releases/tag/v1.1
- https://github.com/Hankeei/Kirby-Clicker/releases/tag/v1.2

What changed between them:

- **v1.0** — initial public build: recorder, profile library, Auto tab, binds, settings, compact
  overlay, music, packaged exe.
- **v1.1** — added **Rename** and **Open folder** profile actions; removed **Save as**; linked
  the two CPS bounds when the method is `Static ⚠`; lowered the default music volume to 5 %.
- **v1.2** — moved Rename/Open folder out of the Record card into a separate **PROFILES** card
  with its own title rule; tightened widths/margins so the 440×250 minimum has no horizontal
  clipping (vertical scrolling remains — see [TASKS.md](TASKS.md)).

---

## 3. Exact environment on this machine

Checked at handoff time:

| Item | Value |
| --- | --- |
| OS | Windows (the app imports `user32`, `kernel32`, `winmm`, `dwmapi`; it will not run elsewhere) |
| `py -3.13 --version` | Python 3.13.5 |
| PySide6 under 3.13 | 6.12.0 |
| `python --version` | Python 3.14.3 |
| `python -c "import PySide6"` | `ModuleNotFoundError: No module named 'PySide6'` |
| `gh` | not installed |
| `git` | installed, credential helper is Git Credential Manager (GCM) |

**Always use `py -3.13`**, not plain `python`. The 3.14 install on this machine does not have
PySide6, so `python main.py` fails at the first import. The README says the same on purpose.

Dependencies:

- [`requirements.txt`](requirements.txt) — `PySide6>=6.6,<7` (runtime only).
- [`requirements-build.txt`](requirements-build.txt) — `-r requirements.txt` plus
  `pyinstaller>=6.10,<7`.

There is no virtualenv committed. Packages are installed into the Python 3.13 environment that
the `py` launcher selects.

---

## 4. Run from source

From the project root:

```powershell
py -3.13 -m pip install -r requirements.txt
py -3.13 main.py
```

When run this way, the data directory is the **project root** (`app/core/paths.py`), so
`binds.txt`, `settings.json` and `profiles/` are created next to `main.py`. That is why those
three paths are in `.gitignore`.

Headless asset check (writes JSON, no window):

```powershell
py -3.13 main.py --selftest
# -> .\selftest.json
# or: $env:KIRBYCLICKER_SELFTEST_OUT = "D:\tmp\selftest.json"
```

---

## 5. Build the executable

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

[`build.ps1`](build.ps1) does two things:

1. `py -3.13 -m pip install -r requirements-build.txt`.
2. PyInstaller with
   `--onefile --windowed --name KirbyClicker --icon assets/icon.ico
   --add-data "assets;assets" --add-data "README.md;." --collect-all PySide6.QtMultimedia
   --distpath dist --workpath build/work --specpath build main.py`.

Output: `dist\KirbyClicker.exe` (61,507,538 bytes for v1.2, ≈59 MB). `build/` holds the
intermediate tree and spec; both are gitignored. `--collect-all PySide6.QtMultimedia` is required
or the bundled FFmpeg plugin is missing and `luolei.mp3` will not play in the frozen build.

Packaged data directory is `%LOCALAPPDATA%\KirbyClicker` (not the exe folder), because
PyInstaller's one-file extraction directory is temporary and read-only.

---

## 6. Module map

All paths are real and current at `8a04fbd`.

### Core (`app/core/`)

| File | Responsibility |
| --- | --- |
| [`paths.py`](app/core/paths.py) | `data_directory()`, `asset_path()`, `app_icon_path()`, `is_frozen()`, `project_root()`, `migration_source()`. Source mode → repo root; frozen → `%LOCALAPPDATA%\KirbyClicker`; env overrides; one-time legacy copy. |
| [`recorder.py`](app/core/recorder.py) | `RecorderEngine` (pure state machine turning down/up events into `Click(hold_ms, gap_ms)`) and `MouseHookThread` (`WH_MOUSE_LL`). Ignores injected events, its own process, events outside the target, and other buttons. |
| [`player.py`](app/core/player.py) | `PlaybackSession(QThread)` — millisecond scheduler for hold/gap, loop support, dry-run, `PlaybackSnapshot`, `DryRunEvent`, graceful stop. |
| [`autoclicker.py`](app/core/autoclicker.py) | Five timing methods and their sampling; `AutoClickerSession`; CPS clamping (`MIN_CPS=1`, `MAX_CPS=50`), gap clamp to `[1000/max, 1000/min]`, hold jitter 10–45 % of gap clamped 3–120 ms, sigma 0.05–0.40. |
| [`trigger.py`](app/core/trigger.py) | `ArmState` (one master arm flag) and `MouseButtonMonitor` — physical hold trigger via `WH_MOUSE_LL`; `MOUSE1`–`MOUSE5`, XBUTTON handling; ignores injected input so playback cannot re-trigger itself. |
| [`hotkeys.py`](app/core/hotkeys.py) | `HotkeyManager(QThread)` — `RegisterHotKey` on a dedicated Win32 message loop; reports failed registrations and Ctrl+key fallbacks. |
| [`binds.py`](app/core/binds.py) | `BindSet`, `DEFAULT_TEXT`, parsing/validation, `BindError`, canonical key names, `ensure_bind_file()`. |
| [`settings.py`](app/core/settings.py) | `AppSettings` dataclass, `load_settings()`, `save_settings()` (atomic `.tmp` + `os.replace`), validation/clamping. |
| [`profile.py`](app/core/profile.py) | `Click`, `ClickProfile`, `ProfileStats`, `load_profile()`, `save_profile()`, `save_profile_values()`, `compute_stats()`, `generate_profile()`, plus rename helpers `profile_name_problem()` / `rename_profile_file()`. |
| [`transfer.py`](app/core/transfer.py) | Exchange JSON v2 export/import (`export_profile`, `import_profile_file`), SHA-256 checksum, legacy v1 import, conflict-safe naming. |
| [`windows.py`](app/core/windows.py) | `WindowInfo`, `Target`, visible-window enumeration for the process picker and scope guard. |
| [`backends.py`](app/core/backends.py) | `ForegroundBackend` (SendInput), `PostMessageBackend` (`WM_xBUTTON` to the window under the cursor), `NullBackend`, shared `_CursorGuard`. |
| [`win32.py`](app/core/win32.py) | Every ctypes constant, struct and prototype. No pywin32 dependency. |

### UI (`app/ui/`)

| File | Responsibility |
| --- | --- |
| [`main_window.py`](app/ui/main_window.py) | `MainWindow` — window constants (`560×437` default, `440×250` minimum), Recorder/Auto tabs, arm state machine, recording/playback wiring, profile library, target scope, settings dialog wiring, compact enter/restore, music, logging. |
| [`compact.py`](app/ui/compact.py) | `CompactOverlay` — 188×104, `Qt.Tool | FramelessWindowHint | WindowStaysOnTopHint | WindowDoesNotAcceptFocus`, `WA_ShowWithoutActivating`, draggable. |
| [`theme.py`](app/ui/theme.py) | Claymorphism palette, font helpers, `palette()`, full Qt stylesheet. Font fallback Instrument Sans → Segoe UI Variable → Segoe UI. |
| [`dialogs.py`](app/ui/dialogs.py) | `ProcessPickerDialog`, `BindEditorDialog`, `SettingsDialog` (backend, record button, dry run, scope/target, profile Files row, music). |
| [`widgets.py`](app/ui/widgets.py) | `PatternBackdrop`, `Card`, `Cushion`, `RhythmStrip`, `SegmentedTabs`, `muted()`, `field_label()`. |
| [`music.py`](app/ui/music.py) | `MusicPlayer` (`QMediaPlayer` loop) and `selftest()` used by `--selftest` and the frozen-build check. |

### Everything else

- [`main.py`](main.py) — Qt app bootstrap, Fusion style/palette/font, AppUserModelID, `--selftest`.
- [`tests/`](tests/) — 11 unittest modules, 144 tests.
- [`tools/`](tools/) — verification scripts, screenshot capture, icon and pattern generators,
  sample-profile generator.
- [`assets/`](assets/) — mascots, bite art, `cat.gif`, `luolei.mp3`, `pattern.png`, icons.
- [`build/verify_exe_env.ps1`](build/verify_exe_env.ps1) — frozen-build environment check
  (generated path under `build/`, not committed).

---

## 7. Data formats and locations

### 7.1 ClickProfile v1 (`profiles/*.txt`)

Produced by `save_profile()` and accepted by `load_profile()`:

```text
# ClickProfile v1 (Kirby Clicker)
# Each data line: <hold_ms> <gap_ms>
# hold_ms = how long the button stays down, gap_ms = wait until the next press
button=left
clicks=10288
avg_cps=19.05
min_interval_ms=22
max_interval_ms=200
# data
11 36
18 29
```

Rules enforced or tolerated by the code:

- `button` is `left`, `right` or `middle`. **One button per file.** `save_profile()` raises
  `ProfileFormatError` if clicks disagree with the header or the profile is empty.
- `clicks`, `avg_cps`, `min_interval_ms`, `max_interval_ms` are metadata. A `clicks` mismatch is
  recorded in `meta["clicks_mismatch"]` but does not block loading.
- The loader accepts any line starting with `# ClickProfile v1` (legacy GMK Clicker files still
  open), and also accepts files without a `# data` marker by treating trailing numeric lines as
  data.
- A line is `<hold_ms> <gap_ms>`; commas are accepted as separators. Blank lines and `#` lines
  inside the data block are skipped.
- **No cursor coordinates are stored.** Playback clicks at the current cursor position.

### 7.2 `binds.txt`

Created on demand from `DEFAULT_TEXT` in [`app/core/binds.py`](app/core/binds.py):

```text
record=F8
toggle=F9
trigger=MOUSE1
quit=F12
rebind=INSERT
selector=F10
scope=anywhere
target=
```

- Keyboard keys: A–Z, 0–9, F1–F24, NUMPAD0–NUMPAD9, SPACE, TAB, ENTER, ESC, BACKSPACE, INSERT,
  DELETE, HOME, END, PAGEUP, PAGEDOWN, arrows, LSHIFT/RSHIFT, LCTRL/RCTRL, LALT/RALT.
- Mouse keys `MOUSE1`–`MOUSE5` are accepted **only** for `trigger`.
- Duplicate bindings are rejected (`BindError`).
- `scope` is `restricted` (selected app only) or `anywhere` (window under the cursor).
  `target` is the executable name; empty means no target.
- Legacy `hold=` lines migrate to the mouse trigger; keyboard `hold=` is ignored. If `target` is
  set and `scope` was absent, the loader defaults to `restricted`; otherwise `anywhere`.

### 7.3 `settings.json`

Written by `save_settings()`; unknown keys are ignored on load, invalid values fall back to
defaults. Defaults:

```json
{
  "auto_min_cps": 8.0,
  "auto_max_cps": 14.0,
  "auto_button": "left",
  "auto_method": "blatant",
  "auto_sigma": 0.15,
  "click_backend": "foreground",
  "active_tab": 0,
  "compact_enabled": false,
  "music_enabled": true,
  "music_volume": 0.05,
  "window_geometry": null,
  "compact_pos": null
}
```

`auto_method` stores an internal id (`blatant`, `gaussian`, `poisson`, `gaussian_poisson`,
`static`), not the display label. Ranges are clamped on load and save: CPS 1–50, sigma
0.05–0.40, volume 0–1.

### 7.4 Data directory

`app/core/paths.py` decides where the three files above live:

| Launch | `binds.txt`, `settings.json`, `profiles/` |
| --- | --- |
| `py -3.13 main.py` | project root |
| `dist\KirbyClicker.exe` | `%LOCALAPPDATA%\KirbyClicker` |
| any, with `KIRBYCLICKER_DATA` set | that directory |

Legacy names `GMKCLICKER_DATA` and `RECORD_CLICKER_DATA` are also honoured. On first frozen
launch, if `%LOCALAPPDATA%\KirbyClicker` does not exist, the app copies `%LOCALAPPDATA%\GMKClicker`
first, then `%LOCALAPPDATA%\RecordClicker`, once. An existing Kirby folder is never overwritten.
A failed copy is swallowed so startup still succeeds.

### 7.5 Exchange format v2 (`transfer.py`)

UTF-8 JSON with `format: "record-clicker-profile"`, `version: 2`, a nested `profile`
(name/button/clicks), `stats`, and a `checksum` of `sha256:<hex>` over the canonical JSON minus
the checksum. Import accepts v2 JSON or strict legacy v1 text, never overwrites an existing file,
and renames clashes to `name (imported).txt`, `name (imported 2).txt`, and so on.

---

## 8. Verification commands and what they prove

Run these from the project root. Every GUI/hook script needs an interactive desktop session and
can steal focus or move the cursor briefly.

| Command | Proves | Does **not** prove |
| --- | --- | --- |
| `py -3.13 -m unittest discover -s tests -q` | 144 tests pass in ~3 s: profile roundtrip/rename, binds, recorder engine, dry-run playback, autoclicker distributions, trigger/scope, settings defaults/migration, transfer, UI layout/card separation/static linking | Real mouse/keyboard input, the frozen exe, visual appearance |
| `py -3.13 tools/verify_dryrun.py` | `PlaybackSession` keeps planned hold/gap timing with `NullBackend`, tolerance ±12 ms (v1.2: max drift 3.1 ms, max interval error 3.1 ms, max hold error 0.3 ms) | That clicks are delivered to another process |
| `py -3.13 tools/verify_click_delivery.py` | Both backends press/release and replay 3 clicks into a dummy window created by the script; restores the cursor | Real games, elevated windows, every app's message handling |
| `py -3.13 tools/verify_hotkeys.py` | The real `MainWindow` responds to injected F8 (record start/stop), F9 (arm/disarm) and Ctrl+F12 (quit fallback) while unfocused | Physical key presses; it fails if another app owns the hotkeys |
| `py -3.13 tools/verify_trigger.py` | F9 arm, simulated trigger press starts and release stops the active tab on both tabs, using a silent backend / dry run | A real physical mouse hold |
| `powershell -ExecutionPolicy Bypass -File .\build\verify_exe_env.ps1` | `dist\KirbyClicker.exe --selftest` loads the 28-frame `cat.gif` and plays `luolei.mp3`; the frozen GUI opens with Python stripped from PATH; UIA opens Auto/Settings/ON state and saves screenshots | A clean VM without Windows SDK/UIA; code signing; every OS build |

`build/verify_exe_env.ps1` hard-codes `D:\Record Clicker` and requires a **freshly built** exe.
Kill stale `KirbyClicker` processes before running it, or it may attach to an old instance.

Screenshots are captured with [`tools/capture_screenshot.py`](tools/capture_screenshot.py) into
`screenshots/`.

---

## 9. GitHub publish and release runbook (as it actually works here)

Repository: `https://github.com/Hankeei/Kirby-Clicker` (**private**, default branch `main`).
The lowercase remote URL redirects to that canonical name.

Two constraints on this machine:

1. **`gh` is not installed.** Do not write `gh release create` instructions that are meant to be
   run here.
2. **The MCP GitHub connector is read-only for writes** — release/file creation through it
   returns 403. Use `git` for the commit/push and the GitHub REST API with a GCM token for the
   release.

### 9.1 Get the token

```powershell
$cred = "protocol=https`nhost=github.com`n`n" | git credential fill
$tok  = (($cred | Select-String '^password=').ToString()).Substring(9)
$h    = @{
    Authorization = "Bearer $tok"
    Accept        = "application/vnd.github+json"
    "User-Agent"  = "kirby-clicker-release"
}
```

Keep `$tok` in the process; do not print it or commit it.

### 9.2 Prepare and push

```powershell
py -3.13 -m unittest discover -s tests -q
py -3.13 tools/verify_dryrun.py
py -3.13 tools/verify_click_delivery.py
py -3.13 tools/verify_hotkeys.py
py -3.13 tools/verify_trigger.py
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

Bump `__version__` in [`app/__init__.py`](app/__init__.py), update README if behaviour changed,
then:

```powershell
git add <changed files>
git commit -m "v1.3: ..."
git push origin main
```

### 9.3 Create the release

```powershell
$notes = @"
...release notes...
"@
$payload = @{
    tag_name         = "v1.3"
    target_commitish = "main"
    name             = "Kirby Clicker v1.3"
    body             = $notes
    draft            = $false
    prerelease       = $false
} | ConvertTo-Json

$rel = Invoke-RestMethod -Method Post `
    -Uri "https://api.github.com/repos/Hankeei/Kirby-Clicker/releases" `
    -Headers $h -ContentType "application/json" -Body $payload
```

The release API creates the tag; you do not push tags with git.

### 9.4 Attach the exe

```powershell
Invoke-RestMethod -Method Post `
    -Uri "https://uploads.github.com/repos/Hankeei/Kirby-Clicker/releases/$($rel.id)/assets?name=KirbyClicker.exe" `
    -Headers $h -ContentType "application/octet-stream" `
    -InFile "dist\KirbyClicker.exe"
```

### 9.5 Verify

```powershell
$check = Invoke-RestMethod `
    -Uri "https://api.github.com/repos/Hankeei/Kirby-Clicker/releases/tags/v1.3" -Headers $h
$check.draft
$check.assets | Select-Object name, size, state
(Get-Item .\dist\KirbyClicker.exe).Length

$ref = Invoke-RestMethod `
    -Uri "https://api.github.com/repos/Hankeei/Kirby-Clicker/git/ref/tags/v1.3" -Headers $h
$ref.object.sha
```

Confirm: `draft=False`, exactly one `KirbyClicker.exe` asset, uploaded size equals the local file
size, and the tag SHA equals `git rev-parse HEAD`.

There is **no CI**. Every release in this repository was built and verified manually on this
machine.

---

## 10. Honest known limitations

Behavioural limitations:

- **Windows only.** ctypes bindings to `user32`/`kernel32`/`winmm`/`dwmapi`; no cross-platform
  path.
- **Unsigned exe.** Windows SmartScreen/antivirus may warn or quarantine it.
- **Hooks and anti-cheat.** Low-level hooks need no elevation, but protected/elevated games can
  block them.
- **Foreground backend steals focus** (SendInput activation). The background backend does not,
  but many games/protected/child windows ignore `PostMessage`.
- **Clicks happen at the cursor.** The v1 profile stores no coordinates, so position is entirely
  the user's responsibility.
- **One button per profile.** The format has a single `button=` header.
- **Compact overlay is not click-through.** It can cover a small part of a game; making it
  click-through would also make its own buttons unreachable.
- **440×250 needs vertical scrolling.** The two Recorder cards together are taller than the
  viewport. There is no horizontal clipping.
- **One arm state for both tabs.** Switching tabs while armed routes the next press to the newly
  active tab.
- **The physical trigger press passes through** to the game, which may register one extra real
  click.
- **Auto tab has no dry-run mode**; it always sends real clicks.
- **Timing is best-effort** (single-digit ms drift measured here), not real-time.
- **Instrument Sans is not installed here**, so the UI falls back to Segoe UI Variable/Segoe UI.

Open defects and verification gaps are tracked in [TASKS.md](TASKS.md), including the static
31–50 CPS slider pinning and the absence of automated physical-click and clean-VM tests.

---

## 11. Repository state at handoff

- Branch `main`. v1.2 source is commit `8a04fbd`; the handoff documents are a docs-only commit
  on top of it.
- Local tags exist only for `v1.0`; `v1.1` and `v1.2` tags exist on the remote and were verified
  through the API.
- `.gitignore` excludes `dist/`, `build/`, `__pycache__/`, `.venv/`, and the three local data
  paths (`settings.json`, `binds.txt`, `profiles/`), plus OS/editor noise.
- The tracked working tree is clean. Local data files may exist but are untracked, and the
  transfer archive in `handoff/` is intentionally **not** committed.
