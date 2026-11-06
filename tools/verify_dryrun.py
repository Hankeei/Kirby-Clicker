"""Dry-run scheduling check: proves the player keeps the profile's inter-click timing.

Run:  py -3.13 tools/verify_dryrun.py
Exit code 0 when every measured interval/hold is within TOLERANCE_MS of plan.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from app.core.backends import NullBackend  # noqa: E402
from app.core.player import PlaybackSession  # noqa: E402
from app.core.profile import Click, ClickProfile  # noqa: E402
from app.core.windows import Target  # noqa: E402

TOLERANCE_MS = 12.0

CLICKS = [
    (12, 30),
    (9, 42),
    (14, 28),
    (11, 51),
    (18, 34),
    (7, 39),
    (16, 22),
    (10, 46),
]


def main() -> int:
    app = QCoreApplication(sys.argv)
    profile = ClickProfile(clicks=[Click(h, g) for h, g in CLICKS], button="left", name="timing-check")
    session = PlaybackSession(
        profile=profile,
        target=Target.any_target(),
        backend=NullBackend(),
        own_pid=0,
        dry_run=True,
    )
    session.start()
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if session.snapshot().sent >= 16:
            break
        time.sleep(0.005)
    session.stop()
    session.wait(2000)

    events = [e for e in session.dry_run_events() if e.lap == 0]
    if len(events) < len(CLICKS):
        print(f"FAIL: only {len(events)} lap-0 events; need {len(CLICKS)}")
        return 1

    events = events[: len(CLICKS)]
    print("Dry-run scheduling check (no clicks sent)")
    print(f"tolerance = +/- {TOLERANCE_MS:.1f} ms")
    print(f"{'#':>2} {'plan(ms)':>9} {'actual(ms)':>10} {'drift':>7} "
          f"{'gap plan':>8} {'gap act':>8} {'hold plan':>9} {'hold act':>8}  result")

    max_drift = 0.0
    max_gap_err = 0.0
    max_hold_err = 0.0
    for i, event in enumerate(events):
        drift = event.actual_down_ms - event.planned_down_ms
        planned_gap = event.hold_ms + event.gap_ms
        if i == 0:
            gap_err = 0.0
            gap_actual = 0
            gap_plan = 0
        else:
            previous = events[i - 1]
            gap_actual = event.actual_down_ms - previous.actual_down_ms
            gap_plan = previous.hold_ms + previous.gap_ms
            gap_err = gap_actual - gap_plan
        hold_err = event.actual_hold_ms - event.hold_ms
        max_drift = max(max_drift, abs(drift))
        max_gap_err = max(max_gap_err, abs(gap_err))
        max_hold_err = max(max_hold_err, abs(hold_err))
        ok = abs(drift) <= TOLERANCE_MS and abs(gap_err) <= TOLERANCE_MS and abs(hold_err) <= TOLERANCE_MS
        print(
            f"{i + 1:>2} {event.planned_down_ms:>9.1f} {event.actual_down_ms:>10.1f} "
            f"{drift:>+7.1f} {gap_plan:>8.0f} {gap_actual:>8.1f} "
            f"{event.hold_ms:>9d} {event.actual_hold_ms:>8.1f}  {'PASS' if ok else 'FAIL'}"
        )

    print(f"\nmax |down drift| = {max_drift:.1f} ms")
    print(f"max |interval error| = {max_gap_err:.1f} ms")
    print(f"max |hold error| = {max_hold_err:.1f} ms")
    passed = max_drift <= TOLERANCE_MS and max_gap_err <= TOLERANCE_MS and max_hold_err <= TOLERANCE_MS
    print("RESULT:", "PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
