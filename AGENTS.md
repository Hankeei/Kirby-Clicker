# AGENTS.md — working on Kirby Clicker

Read HANDOFF.md, this file, then TASKS.md before editing. The shipping application
is now native Rust in native/. Retain app/, main.py and tests/ as the Python
compatibility reference; do not rewrite them as part of routine native work.

## Commands after changes

Use Cargo from %USERPROFILE%\.cargo\bin if it is not on PATH:

```powershell
cargo fmt --manifest-path native/Cargo.toml --check
cargo test --manifest-path native/Cargo.toml --locked
py -3.13 -m unittest discover -s tests -q
py -3.13 tools/verify_dryrun.py
py -3.13 tools/verify_click_delivery.py
py -3.13 tools/verify_hotkeys.py
py -3.13 tools/verify_trigger.py
powershell -ExecutionPolicy Bypass -File .\build.ps1
py -3.13 tools/verify_native.py
py -3.13 tools/verify_native_compat.py
powershell -ExecutionPolicy Bypass -File .\build\verify_exe_env.ps1
```

Python 3.13 is for the legacy tests/test harness only. Plain python has no PySide6.
GUI checks require an interactive desktop; close stale instances first. Report
actual output and limitations. Do not claim the Python tests validate Rust.
build.ps1 regenerates build/verify_exe_env.ps1 as a wrapper around the tracked
tools/verify_native_exe.ps1.

## Conventions

- Rust UI uses eframe/egui with the existing pastel palette/art and card structure.
- Native Win32 calls stay in platform.rs (audio has its WinMM boundary).
- Keep pure recorder/binds/profile/timing logic independently testable.
- Use one cancellable playback worker; never busy-spin to hold CPS.
- Ignore injected input before taking the hook lock. Always release injected downs
  on cancellation/error/shutdown. Never synthesize input in unit tests.
- Validate untrusted files/settings; persist settings atomically and imports
  without overwriting recordings. Keep Cargo.lock committed.
- Keep README.md short and user oriented. Developer details belong in HANDOFF.md,
  DEVELOPER.md or native/README.md.

## Do not break

1. ClickProfile v1 and legacy loading, including missing # data / old suffixes.
2. Stored method IDs: blatant, gaussian, poisson, gaussian_poisson, static.
3. One-time GMKClicker then RecordClicker migration and all three env overrides.
4. Packaged data in LocalAppData, never the EXE folder or a temporary runtime folder.
5. No horizontal clipping at 440×250; vertical scrolling is intentional.
6. Rename / Open folder in their own PROFILES card.

## Releases

The user authorizes automatic version bumps, commits, pushes and releases after
verification. Next release is v1.3; inspect remote tags before choosing future tags.
Version lives in native/Cargo.toml and is mirrored in app/__init__.py.
Use the REST/GCM runbook in HANDOFF.md. No release for documentation-only edits.
Do not publish incomplete scaffolding or quietly remove features to pass checks.
