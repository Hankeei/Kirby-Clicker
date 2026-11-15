# Developer and LLM reference

README.md is the user guide. Keep implementation details here and in the handoff documents.

Before changing code, read these in order:

1. [HANDOFF.md](HANDOFF.md) — environment, module map, formats and release runbook.
2. [AGENTS.md](AGENTS.md) — working rules, required checks and compatibility requirements.
3. [TASKS.md](TASKS.md) — known bugs, limitations and ideas.

HANDOFF.md records the v1.2 baseline. Details below were moved from the former README;
historical verification results are not evidence of a current pass.

## Changes since the v1.2 handoff

- Commit fd197ab adds quiet, 150 ms ON/OFF cues in app/ui/music.py, using
  assets/toggle_on.wav and assets/toggle_off.wav. ToggleSounds uses QSoundEffect
  at 0.18 volume, independently of background music. Main-window, compact and
  hotkey toggles share MainWindow._toggle_arm().
- build.ps1 temporarily limits PATH during PyInstaller dependency discovery and
  restores it afterward. Otherwise it can collect Poppler's incompatible icuuc.dll
  from the host tool environment instead of using Windows ICU.
- The last recorded checks for that change passed 144 unit tests, dry-run timing,
  both click-delivery backends and the frozen self-test/GUI. Hotkey and trigger
  scripts failed at F9 arming; the cause was not established. On 2026-11-16,
  the documentation-update run passed all 144 unit tests and all four verification
  scripts, including hotkeys and trigger. Do not infer that a code fix was made.
- Static mode typing above 30 CPS is a known bug (TASKS.md T1). The former README
  incorrectly said those values were retained.
- The user authorizes automatic commits, pushes and release updates after verified
  application changes. Documentation-only changes need no version bump or release.
  Keep the existing REST/GCM release runbook; never print credentials.

## Source, packaging and assets

### From source

Requirements: Windows 10/11, Python 3.10+ and PySide6. Clone the repository
(green **Code** button) or download the ZIP, then from its folder:

```powershell
cd "Record Clicker"
py -3.13 -m pip install -r requirements.txt
py -3.13 main.py
```

Use `py -3.13` on this machine: the plain `python` command resolves to Python
3.14, which does not have PySide6 installed.

### Where data lives

| Launch | `binds.txt`, `settings.json` and `profiles/` | Screenshots |
| --- | --- | --- |
| `py -3.13 main.py` | project root | `screenshots/` |
| `dist\KirbyClicker.exe` | `%LOCALAPPDATA%\KirbyClicker` | not written |
| any, with `KIRBYCLICKER_DATA` set | that directory | not written |

`settings.json` stores the auto-clicker bounds, button, timing method and
sigma, the active tab, the compact-mode flag, the last window geometry, the
overlay position, and the music option and volume. `binds.txt` keeps the
hotkeys, the mouse trigger, scope and target. Both are created on demand; a
corrupt or unreadable settings file falls back to defaults instead of failing
to launch.

**Renamed through Record Clicker → GMK Clicker → Kirby Clicker.** On first start
of the packaged exe, if `%LOCALAPPDATA%\KirbyClicker` does not exist, the app
copies the newest available legacy folder into it once: `GMKClicker` first, then
`RecordClicker` (binds, settings and all profiles). An existing Kirby folder is
never overwritten. The legacy `GMKCLICKER_DATA` and `RECORD_CLICKER_DATA`
environment variables are still honoured. Profile files keep the
`# ClickProfile v1` header prefix, so every old `.txt` profile still loads, and
the exchange JSON format id is unchanged.

The packaged app deliberately avoids one-file's temporary extraction folder for
user data.

### Build the executable

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

The script installs `requirements-build.txt`, then runs PyInstaller with
`--onefile --windowed --name KirbyClicker --icon assets/icon.ico
--add-data "assets;assets" --add-data "README.md;."
--collect-all PySide6.QtMultimedia --distpath dist --workpath build/work
--specpath build main.py`. `--collect-all PySide6.QtMultimedia` is required so
the FFmpeg media plugin is bundled and the song keeps playing in the frozen
build. The icon is embedded as the Windows executable resource; `assets/` and
`README.md` are extracted to `sys._MEIPASS` and located by
`app/core/paths.py`. Output:

```text
dist\KirbyClicker.exe      58 MB
build\KirbyClicker.spec    intermediate spec
build\work\              intermediate build tree (safe to delete)
```

### Application icon

| File | Purpose |
| --- | --- |
| `assets/kirby.png` | uploaded normal Kirby; icon source and recorder mascot |
| `assets/icon.ico` | 16, 24, 32, 48, 64, 128 and 256 px layers; exe resource + taskbar |
| `assets/icon.png` | 256 px, used by Qt for the window and compact overlay |
| `tools/make_icon.py` | trim transparent margins, square-crop, scale, ICO writer (Qt only, no Pillow) |

`make_icon.py` scans the PNG alpha channel, trims the empty margins, centres the
art in a transparent square and writes every ICO layer independently. Regenerate
with:

```powershell
py -3.13 tools/make_icon.py
```

### What the exe contains, and what it still needs

The bundle contains the Python 3.13 runtime, Qt 6 (`Qt6Core`, `Qt6Gui`,
`Qt6Widgets`, `Qt6Multimedia`), the Windows platform plugin, the FFmpeg
multimedia plugin, the MSVC runtime, and every asset in `assets/` including
`cat.gif` and `luolei.mp3`. The `--selftest` mode (see Verification) proves the
frozen copy loads its icon, animates the GIF and plays the song.

So neither Python nor PySide6 has to be installed. External pieces are only
Windows itself:

- **Windows 10/11 system DLLs**, including the Universal C Runtime (present by
  default) and normal `kernel32`/`user32` APIs. The Visual C++ runtime is
  bundled.
- **Unsigned exe → SmartScreen.** Windows may show “Windows protected your PC”;
  choose *More info → Run anyway*. A code-signing certificate removes this.
- **Antivirus false positives.** One-file packagers are frequently flagged by
  heuristics because the exe self-extracts; submit false positives to the vendor.
- One-file launch extracts Qt to `%TEMP%`; the first start is slower and spawns
  two processes (bootloader + app). User data stays in LocalAppData.

**Evidence and its limit:** this machine has Python installed, so a genuinely
clean-VM test was not possible. The closest available test launched
`dist\KirbyClicker.exe` with `PATH` reduced to `%SystemRoot%\System32` and
`PYTHONHOME`, `PYTHONPATH`, `PYTHONSTARTUP` and `VIRTUAL_ENV` removed:
`--selftest` reported a valid 28-frame GIF and audio actually playing at 5 %
volume (position 2352 ms), the window opened with the title `Kirby Clicker`,
both segments were enumerated through UI Automation, and the settings dialog
opened. `python` was not resolvable on the stripped `PATH`. That shows the exe
does not fall back to the installed interpreter, but it is not the same as
running on a machine that never had Python.

### Timing methods and exact math

Let `L` be lower CPS, `H` upper CPS, `s = 1000/H` (shortest gap), `l = 1000/L`
(longest gap), `m = (L + H)/2` (midpoint CPS), `μ = 1000/m` (mean gap) and
`σ` the sigma fraction. A generated gap `g` is always clamped at the end:

```text
g ← min(l, max(s, g))
```

All randomness uses Python's `random.Random.uniform/gauss/expovariate`; no
SciPy/NumPy is involved.

| Method | Generation |
| --- | --- |
| **Random** | `g = uniform(s, l)` — maximum spread; the clicker visits both bounds. |
| **Gaussian** | `g = gauss(μ, σ·μ)` — normal gaps around the midpoint. |
| **Poisson** | `g = expovariate(m / 1000)` — exponential gaps, mean `μ`, i.e. a Poisson arrival process at `m` CPS. |
| **Gaussian + Poisson** | `λ ~ gauss(m, σ·m)` (resampled while `λ < 0.5`), then `g = expovariate(λ / 1000)` — a per-click tempo with a global Gaussian shape. |
| **Static ⚠** | `g = μ` exactly — no random sampling, so the gap never changes. The low and high bounds are linked, so picking Static sets both to one value. Hold time still jitters. |

The stored identifiers in `settings.json` are still `blatant` and `static`, so a
config written by any earlier build keeps resolving to the same mode; only the
displayed label changed.

What the modes actually do:

- **Clamping changes the realised mean near the bounds.** A Gaussian tail or an
  exponential tail that would exceed `s`/`l` is folded onto the bound, so the
  measured CPS is close to, but not exactly, the midpoint.
- **Random samples gaps uniformly, not CPS.** Do not assume the measured rate equals the midpoint CPS.- **Static ⚠ has zero gap variance.** Its equalizer collapses into one bar
  height. The warning in the label is deliberate: a perfectly regular click
  train is trivial to spot, so use it knowingly.
- **Variance ordering** for wide bounds is **random > poisson > gaussian >
  static**.
- These are statistical shapes for click timing only. They do **not** evade
  anticheat or make synthetic input look like a human device.

## Required verification

Run from the project root with Python 3.13:

```powershell
py -3.13 -m unittest discover -s tests -q
py -3.13 tools/verify_dryrun.py
py -3.13 tools/verify_click_delivery.py
py -3.13 tools/verify_hotkeys.py
py -3.13 tools/verify_trigger.py
```

GUI/hook checks require an interactive desktop and can move the cursor or take focus.
Close stale KirbyClicker instances first. Report actual output, including failures.
Unit tests do not prove physical input capture or clean-VM compatibility.

For packaging/assets/startup changes, rebuild and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
powershell -ExecutionPolicy Bypass -File .\build\verify_exe_env.ps1
```

README.md is bundled by build.ps1, so rebuild when verifying changes to its packaged copy.
See HANDOFF.md sections 6–9 for the module map, persistent formats, check limits and
release procedure. No CI is configured.

## License

No LICENSE file is present. Do not assume permission to redistribute the code, art or audio.
