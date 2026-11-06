"""Dry-run timing test: verifies real scheduling (no clicks are sent)."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from app.core.backends import NullBackend  # noqa: E402
from app.core.player import PlaybackSession  # noqa: E402
from app.core.profile import Click, ClickProfile  # noqa: E402
from app.core.windows import Target  # noqa: E402

TOLERANCE_MS = 15.0
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


class DryRunTimingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_scheduling_matches_profile(self) -> None:
        profile = ClickProfile(
            clicks=[Click(h, g) for h, g in CLICKS], button="left", name="timing-check"
        )
        session = PlaybackSession(
            profile=profile,
            target=Target.any_target(),
            backend=NullBackend(),
            own_pid=0,
            dry_run=True,
        )
        session.start()
        deadline = time.time() + 5.0
        while time.time() < deadline and session.snapshot().sent < 16:
            time.sleep(0.005)
        session.stop()
        self.assertTrue(session.wait(2000))

        events = [e for e in session.dry_run_events() if e.lap == 0][: len(CLICKS)]
        self.assertEqual(len(events), len(CLICKS))

        drifts = []
        gap_errors = []
        hold_errors = []
        for i, event in enumerate(events):
            drifts.append(abs(event.actual_down_ms - event.planned_down_ms))
            if i > 0:
                actual_interval = event.actual_down_ms - events[i - 1].actual_down_ms
                planned_interval = events[i - 1].hold_ms + events[i - 1].gap_ms
                gap_errors.append(abs(actual_interval - planned_interval))
            hold_errors.append(abs(event.actual_hold_ms - event.hold_ms))

        self.assertLessEqual(max(drifts), TOLERANCE_MS, f"down-time drift too large: {max(drifts):.1f} ms")
        self.assertLessEqual(max(gap_errors), TOLERANCE_MS, f"interval error too large: {max(gap_errors):.1f} ms")
        self.assertLessEqual(max(hold_errors), TOLERANCE_MS, f"hold error too large: {max(hold_errors):.1f} ms")


if __name__ == "__main__":
    unittest.main()
