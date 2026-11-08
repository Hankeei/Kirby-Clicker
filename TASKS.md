# TASKS.md — open items

Real, currently observable issues at v1.2.0. Nothing here is a roadmap commitment. Each item is
tagged **bug**, **limitation**, or **idea**, with the evidence and the smallest sensible next
step.

## Bugs

### T1 — Static mode: typing 31–50 CPS pins both bounds at 30

**Type:** bug · **Area:** Auto tab / timing bounds

**Evidence:** In [`app/ui/main_window.py`](app/ui/main_window.py) the sliders are
`setRange(10, 300)` (i.e. 1.0–30.0 CPS) while the spin boxes are `setRange(1.0, 50.0)`. In
`Static ⚠` the bounds are linked: typing `40` in one spin box sets the other spin box to 40,
then `_tie_static_bounds()` writes 40 into the sliders; `QSlider` clamps to 300 (= 30 CPS), its
`valueChanged` fires `_apply_auto_bounds()`, and both spin boxes are rewritten to 30. Values
31–50 are reachable only by typing, and end up pinned at 30.

**Next step:** either extend both sliders to `setRange(10, 500)` or suppress the slider→spin
write-back while the typed value is above the slider maximum. Add a UI test for typing 40 in
Static mode.

## Limitations

### T2 — 440×250 needs vertical scrolling

**Type:** limitation · **Area:** Recorder layout

**Evidence:** At the 440×250 minimum the two Recorder cards (Record + PROFILES) exceed the
viewport height, so the tab scrolls vertically. Width was deliberately fitted so nothing clips
horizontally (`tests/test_ui_redesign.py` asserts this).

**Next step:** none required unless the minimum size changes. If it does, re-measure page width
against viewport width and update the layout test.

### T3 — Compact overlay is not click-through

**Type:** limitation · **Area:** `app/ui/compact.py`

**Evidence:** `CompactOverlay` sets `Qt.Tool | FramelessWindowHint | WindowStaysOnTopHint |
WindowDoesNotAcceptFocus` and `WA_ShowWithoutActivating`, but does **not** set
`WA_TransparentForMouseEvents` or `WS_EX_TRANSPARENT`. The 188×104 widget can cover a small part
of a game and intercept clicks there.

**Next step:** treat as a design trade-off. Click-through would also make the overlay's ON/OFF
and restore buttons unreachable; a solution needs a separate hit-test or a mode toggle.

### T4 — No per-click button in the profile format

**Type:** limitation · **Area:** `app/core/profile.py`, `app/core/transfer.py`

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
