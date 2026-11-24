# Kirby Clicker — handoff

The current release is **v1.3.0**, a native Rust Windows application.
Read this file, then [AGENTS.md](AGENTS.md), then [TASKS.md](TASKS.md) before editing.
The Python v1.2 implementation remains in app/ and main.py as a compatibility
reference and regression suite. Its historical handoff is in
[docs/PYTHON_HANDOFF.md](docs/PYTHON_HANDOFF.md); its environment notes are not
the build instructions for the native release.

## Functionality and usage

Kirby Clicker starts OFF. F9 or the power pill arms it; holding the configured
physical mouse button starts clicking; releasing it stops playback.

- **Recorder:** F8 starts/stops a take, automatically saved as the lowest free
  profiles/recN.txt. Load a profile, arm, then hold the trigger to loop its cadence.
  One button per profile; clicks use the current cursor position.
- **Auto:** five timing methods, left/right/middle output, 1–50 CPS and Gaussian
  sigma 5–40%. Static links both bounds and supports 40–50 CPS.
- **PROFILES:** Rename and Open folder stay separate from recording controls.
- **Settings:** foreground SendInput or background PostMessage, selected-app
  scope/target picker, record button, Recorder-only dry run, editable shortcuts,
  profile import/export, background music and volume.
- **Compact:** small draggable, topmost control with power, method chip and Restore.
  It does not take focus on a mouse click and remembers its position.
- F12 stops active work and disarms; when idle it quits. Busy global shortcuts
  fall back to Ctrl+key and report that fallback in the status text.
- Music defaults to enabled at 5%. Short ON/OFF sounds are independent of music.
  The same Kirby artwork, pastel palette, dancing cat and card organization remain.

The user-facing guide is [README.md](README.md).

## Environment and build

Windows 10/11; Rust stable x86_64-pc-windows-msvc; Visual Studio C++ Build Tools
with the Windows SDK. OpenGL 3.3-capable drivers are required by the native renderer.
On this machine Cargo lives at %USERPROFILE%\.cargo\bin\cargo.exe; build.ps1 finds it
even when it is absent from PATH. Rust 1.100.0 was installed for this migration.

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
.\dist\KirbyClicker.exe
```

build.ps1 uses Cargo.lock, optimizes for size, embeds the Windows icon/version,
statically links the C runtime, and copies the single EXE to dist/. No Python,
Qt, FFmpeg DLLs, installer or separate assets folder are needed at runtime.
Images, GIF, MP3 and WAV cues are embedded; no extraction of a runtime occurs.

Cargo project: native/Cargo.toml. Release version: its package.version, mirrored
in app/__init__.py for the retained Python implementation. Releases continue at
v1.3 (not a reset to v1.0). Python packaging is retained as build-python.ps1.

## Module map

| Rust module | Responsibility |
| --- | --- |
| native/src/main.rs | Native bootstrap, icon, error reporting, explicit self-test/verification modes |
| native/src/ui.rs | Recorder/Auto/settings/profile dialogs, compact mode, artwork, persistence |
| native/src/engine.rs | Master arm state, one sleeping worker, cancellable hold/gap deadlines, dry-run traces |
| native/src/platform.rs | Win32 boundary, mouse hook/message loop, hotkeys/fallbacks, scope guard, delivery, file dialogs |
| native/src/recorder.rs | Pure hold/gap state machine; ignores injected/own/out-of-scope presses |
| native/src/binds.rs | Key names, validation, aliases, legacy hold migration, binds.txt |
| native/src/settings.rs | Validated settings, unknown-field preservation, atomic .tmp + MoveFileEx replacement |
| native/src/lib.rs | Timing distributions, legacy profile parsing/writing, data-directory migration |
| native/src/storage.rs | Library naming/rename, exchange v2/checksum/stat validation, conflict-safe import |
| native/src/audio.rs | Rust MP3 decoder/WASAPI music worker; quiet in-memory WinMM WAV cues |
| native/build.rs | Windows icon and version resources |

The hook and hotkey message loop run on their own thread. Injected mouse events
return before locking shared state, avoiding a SendInput/hook deadlock. The input
thread wakes the playback condition variable on physical release/disarm/shutdown.
The playback worker owns delivery state and releases every successful down event,
including cancellation and error paths. Idle playback waits without polling.
Timing is best-effort, with no catch-up bursts after scheduling stalls.

## Compatibility requirements

- Keep the # ClickProfile v1 header prefix and hold_ms gap_ms text lines.
  Old header suffixes and files without # data still load; commas and BOMs work.
  Lenient library loading and strict exchange importing remain distinct.
- Persist the method IDs blatant, gaussian, poisson, gaussian_poisson and static.
  Display labels may differ; never rename stored IDs without migration.
- Native data always lives at %LOCALAPPDATA%\KirbyClicker, unless overridden by
  KIRBYCLICKER_DATA, GMKCLICKER_DATA or RECORD_CLICKER_DATA (in that order).
  When the new folder is absent, copy GMKClicker first, then RecordClicker;
  never overwrite an existing Kirby folder. Migration is best-effort.
- Unknown settings fields, including Python window_geometry, are retained.
  Native geometry uses native_window_size/native_window_pos; compact_pos remains
  a two-number array. Every launch starts OFF; arm state is never persisted.
- Exchange format stays record-clicker-profile, version 2, canonical sorted-key
  UTF-8 JSON with SHA-256, one button, and the existing size/count/duration limits.
  Tests include a golden Python export; the Python importer also checks native exports.
- 440×250 remains the normal-window minimum. Vertical scrolling is deliberate;
  it must not clip controls horizontally. Compact remains 188×104.

## Verification

Read [AGENTS.md](AGENTS.md) for all required commands. Native tests validate native
behavior; the Python tests protect compatibility references and do not prove the port.

The native EXE supports --selftest, writing JSON to KIRBYCLICKER_SELFTEST_OUT
(default selftest-native.json). It checks legacy profiles, actual dry-run scheduling
against ±12 ms, ignored injected intake, the 28 GIF frames, music progression,
both WAV cues and an exchange fixture. It sends no mouse clicks.
--verify-input is an explicit integration mode restricted to the dedicated dummy
window title and PID used by tools/verify_native.py.

tools/verify_native_exe.ps1 strips Python from PATH, runs the self-test, drives the
accessible GUI through Recorder/Auto/ON/OFF/Settings/compact, checks minimum width,
saves build/native-*.png and records startup/idle CPU. Results are machine-specific.
KIRBYCLICKER_STARTUP_OUT optionally records initialization time at the first GUI update;
the external script includes process launch up to that signal.

## GitHub publishing

Repository: https://github.com/Hankeei/Kirby-Clicker (private), branch main.
The user authorizes automatic commit, push and release updates after verified app
changes. Documentation-only updates need no version bump. No CI is configured.

Use git for commit/push. Git Credential Manager supplies the GitHub token.
Keep it in process memory; never print it, save it to disk or put it in a commit.
Use the REST release API (the historical runbook in docs/PYTHON_HANDOFF.md section 9
has working PowerShell examples). gh is not required.

1. Inspect remote main and existing tags; integrate concurrent changes.
2. Bump native/Cargo.toml and app/__init__.py, update docs, run all checks, build.
3. Commit the exact reviewed files and push main.
4. POST /repos/Hankeei/Kirby-Clicker/releases with tag_name v1.3 and
   target_commitish set to the tested commit SHA; attach dist/KirbyClicker.exe.
5. Verify the tag SHA, published state, one uploaded EXE and exact size/hash.
   Do not force-update existing tags or replace older releases.

## Measured migration results

On this machine, three launches of each EXE with music disabled used the same
UI Automation ready-window criterion. Median startup was 258 ms for Rust versus
1920 ms for the downloaded v1.2 release. The candidate was about 9.2 MB versus
61.5 MB (about 85% smaller). Both had 0% measured idle CPU in the short samples.
These are local observations, not guarantees for other machines or cold disk caches.
Reproduce with tools/benchmark_native.ps1; it expects the v1.2 EXE in build/.
Raw measurements live in build/native-benchmark.json.
## Known limits

Hooks and synthetic input can be blocked by elevated/protected apps. The physical
trigger press passes through, which can add one real click. Background delivery
is ignored by some apps. Auto always sends real clicks; dry run applies to Recorder.
Compact is not click-through. Timing is not hard real-time. The EXE is unsigned.
Automated checks do not prove physical-device capture or clean-VM behavior.
