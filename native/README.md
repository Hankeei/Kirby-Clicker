# Native Rust implementation

The shipping application is native Rust (v1.3). It uses eframe/egui for the UI,
raw Win32 hooks and delivery, and Rust MP3 decoding with WASAPI output.
No Python, Qt or separately installed runtime is required by the EXE.

The user guide is [../README.md](../README.md).
Architecture, data formats and the release runbook are in [../HANDOFF.md](../HANDOFF.md).

## Build and run

Install Rust stable (x86_64-pc-windows-msvc), Visual Studio C++ Build Tools and the
Windows SDK. Cargo is installed here at %USERPROFILE%\.cargo\bin\cargo.exe.

From the repository root:

```powershell
cargo run --manifest-path native/Cargo.toml --bin KirbyClicker
powershell -ExecutionPolicy Bypass -File .\build.ps1
.\dist\KirbyClicker.exe
```

The build script embeds the icon/version and links the C runtime statically.
Cargo.lock pins dependencies. Images/audio are embedded directly in the EXE.
Both development and release runs use LocalAppData unless a data env override is set.

## Tests

```powershell
cargo fmt --manifest-path native/Cargo.toml --check
cargo test --manifest-path native/Cargo.toml --locked
py -3.13 tools/verify_native.py
py -3.13 tools/verify_native_compat.py
powershell -ExecutionPolicy Bypass -File .\build\verify_exe_env.ps1
```

Run the Python regression commands in AGENTS.md too. Native unit tests do not send
real input. The dedicated integration target receives foreground/background clicks
and checks actual down/up delivery; it also checks F9 registration, recording
intake, ignored injected trigger events and stop-on-release.

GUI smoke tests exercise the actual release with Python stripped from PATH,
capture its views/minimum layout, and record startup and idle CPU. --selftest
checks dry-run timing, profiles, GIF, advancing music and both sound cues.
Physical-device capture, games/elevated targets and a clean VM require manual checks.
