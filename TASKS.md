# TASKS.md — open items

Tracked issues and decisions for native v1.3.0. The Python implementation is retained as a historical reference. Nothing here is a roadmap commitment. Each item is
tagged **bug**, **limitation**, or **idea**, with the evidence and the smallest sensible next
step.

## Bugs

### T1 — Static mode 31–50 CPS: fixed in native v1.3

The Rust UI uses 1–50 CPS for both sliders and numeric values and links the two
bounds in Static mode. Native tests check the 50 CPS timing boundary.
The retained Python UI still has the original 30 CPS slider limitation.

## Limitations

### T2 — 440×250 needs vertical scrolling

**Type:** limitation · **Area:** Recorder layout

**Evidence:** At the 440×250 minimum the two Recorder cards (Record + PROFILES) exceed the
viewport height, so the tab scrolls vertically. Width was deliberately fitted so nothing clips
horizontally (native GUI smoke checks this; `tests/test_ui_redesign.py` covers the Python reference).

**Next step:** none required unless the minimum size changes. If it does, re-measure page width
against viewport width and update the layout test.

### T3 — Compact overlay is not click-through

**Type:** limitation · **Area:** native compact UI (historical Python reference: `app/ui/compact.py`)

**Evidence:** native compact mode sets topmost and WS_EX_NOACTIVATE /
WS_EX_TOOLWINDOW, but deliberately does not set mouse pass-through. Its power
and restore controls need to receive mouse input. The GUI smoke test checks the
no-activate flag. The historical Python overlay has the same trade-off.
**Next step:** treat as a design trade-off. Click-through would also make the overlay's ON/OFF
and restore buttons unreachable; a solution needs a separate hit-test or a mode toggle.

### T4 — No per-click button in the profile format

**Type:** limitation · **Area:** native/src/lib.rs, native/src/storage.rs (Python reference: app/core/profile.py, app/core/transfer.py)

**Evidence:** The v1 text format has a single `button=left|right|middle` header, and
`save_profile()` raises `ProfileFormatError` when clicks disagree with it. Exchange v2 JSON also
stores one button. A recording cannot mix buttons.

**Next step:** would require a new format version (v2 text or an exchange-schema change) plus a
migration path; do not change the v1 writer in place.

### T5 — Verification gaps

**Type:** limitation · **Area:** `tests/`, `tools/`, release process

- **No automated recording of physical clicks.** `tools/verify_trigger.py` simulates trigger
  press/release and `tools/verify_hotkeys.py` injects keys; neither proves a real human mouse
  press is captured by `WH_MOUSE_LL` on a given machine. This was checked manually only.
- **No clean-VM test.** `build/verify_exe_env.ps1` strips Python from `PATH` and launches the exe
  on this machine, and `--selftest` proves the bundled GIF/audio load, but the build was not run
  on a fresh Windows install without the dev toolchain/Windows SDK.

**Next step:** a hardware-in-the-loop harness would need a synthetic device or manual checklist;
a clean VM would need a separate snapshot. Document any manual pass in the release notes rather
than claiming automated coverage.

## Ideas

### I1 — Default background music to off

**Type:** idea · **Area:** `app/core/settings.py`, Settings dialog

**Evidence:** Current defaults are `music_enabled = True` and `music_volume = 0.05`. Music starts
with the app and is independent of the clicker's ON/OFF state. There has been a request to
default it off; it is **not** implemented yet.

**Next step:** if accepted, change `AppSettings.music_enabled` to `False`, keep the 0.05 default
volume, update `tests/test_settings.py`, and note the migration for users who already have a
saved `settings.json` (their stored `true` should be preserved).
