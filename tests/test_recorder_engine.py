"""Recorder state machine tests (synthetic timestamps, no real clicking)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from app.core.recorder import RecorderEngine  # noqa: E402


class RecorderEngineTest(unittest.TestCase):
    def test_hold_and_gap_capture(self) -> None:
        engine = RecorderEngine(button="left", own_pid=999, target_pid=555)
        engine.start(1000)
        self.assertTrue(engine.on_down(1010, "left", 555))
        self.assertTrue(engine.on_up(1028, "left", 555))
        self.assertTrue(engine.on_down(1064, "left", 555))
        self.assertTrue(engine.on_up(1079, "left", 555))
        self.assertTrue(engine.on_down(1133, "left", 555))
        self.assertTrue(engine.on_up(1141, "left", 555))
        profile = engine.stop(1200)
        self.assertEqual(
            [(c.hold_ms, c.gap_ms) for c in profile.clicks],
            [(18, 36), (15, 54), (8, 54)],
        )
        self.assertEqual(profile.button, "left")

    def test_own_window_is_ignored(self) -> None:
        engine = RecorderEngine(button="left", own_pid=999)
        engine.start(0)
        self.assertFalse(engine.on_down(10, "left", 999))
        self.assertFalse(engine.on_up(20, "left", 999))
        snap = engine.snapshot(30)
        self.assertEqual(snap.count, 0)
        self.assertEqual(snap.ignored_own, 1)

    def test_outside_target_injected_and_wrong_button_are_ignored(self) -> None:
        engine = RecorderEngine(button="left", own_pid=999, target_pid=555)
        engine.start(0)
        self.assertFalse(engine.on_down(10, "left", 777))
        self.assertFalse(engine.on_down(20, "left", 555, injected=True))
        self.assertFalse(engine.on_down(30, "right", 555))
        snap = engine.snapshot(40)
        self.assertEqual(snap.count, 0)
        self.assertEqual(snap.ignored_outside, 1)
        self.assertEqual(snap.ignored_injected, 1)
        self.assertEqual(snap.ignored_other_button, 1)

    def test_any_process_target(self) -> None:
        engine = RecorderEngine(button="left", own_pid=999, target_pid=None)
        engine.start(0)
        self.assertTrue(engine.on_down(5, "left", 42))
        self.assertTrue(engine.on_up(12, "left", 42))
        profile = engine.stop(50)
        self.assertEqual([(c.hold_ms, c.gap_ms) for c in profile.clicks], [(7, 0)])

    def test_cps_and_interval_snapshot(self) -> None:
        engine = RecorderEngine(button="left", own_pid=999, target_pid=555)
        engine.start(0)
        for t in (100, 150, 200):
            self.assertTrue(engine.on_down(t, "left", 555))
            self.assertTrue(engine.on_up(t + 10, "left", 555))
        snap = engine.snapshot(1000)
        self.assertEqual(snap.count, 3)
        self.assertEqual(snap.intervals_ms[-2:], [50.0, 50.0])
        self.assertEqual(snap.cps_now, 3.0)


if __name__ == "__main__":
    unittest.main()
