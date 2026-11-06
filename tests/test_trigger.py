"""Master arm state, physical mouse trigger and clean release of an in-flight click."""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from app.core.backends import ClickBackend, ClickResult  # noqa: E402
from app.core.player import PlaybackSession  # noqa: E402
from app.core.profile import Click, ClickProfile  # noqa: E402
from app.core.trigger import (  # noqa: E402
    ArmState,
    MouseButtonTracker,
    resolve_trigger_kind,
)
from app.core.windows import Target  # noqa: E402


class ArmStateTest(unittest.TestCase):
    def test_starts_off_and_toggles(self) -> None:
        state = ArmState()
        self.assertFalse(state.armed)
        self.assertEqual(state.label("MOUSE1"), "OFF")
        self.assertTrue(state.toggle())
        self.assertEqual(state.label("MOUSE1"), "ON")
        state.clicking = True
        self.assertEqual(state.label("MOUSE1"), "ON")
        self.assertFalse(state.toggle())
        self.assertEqual(state.label("MOUSE1"), "OFF")
        self.assertFalse(state.clicking)

    def test_disarm_clears_clicking(self) -> None:
        state = ArmState(armed=True, clicking=True)
        state.disarm()
        self.assertFalse(state.armed)
        self.assertFalse(state.clicking)

    def test_label_never_uses_armed_wording(self) -> None:
        self.assertNotIn("ARMED", ArmState(armed=True).label("MOUSE2"))
        self.assertNotIn("DISARMED", ArmState().label("MOUSE2"))


class MouseButtonTrackerTest(unittest.TestCase):
    def test_down_starts_release_stops(self) -> None:
        tracker = MouseButtonTracker("MOUSE1")
        self.assertIsNone(tracker.handle("MOUSE2", True))  # other button
        self.assertEqual(tracker.handle("MOUSE1", True), "press")
        self.assertIsNone(tracker.handle("MOUSE1", True))  # duplicate down
        self.assertEqual(tracker.handle("MOUSE1", False), "release")
        self.assertIsNone(tracker.handle("MOUSE1", False))  # duplicate up

    def test_injected_events_are_ignored(self) -> None:
        tracker = MouseButtonTracker("MOUSE1")
        self.assertIsNone(tracker.handle("MOUSE1", True, injected=True))
        self.assertIsNone(tracker.handle("MOUSE1", False, injected=True))
        self.assertFalse(tracker.down)
        # A real press still works afterwards.
        self.assertEqual(tracker.handle("MOUSE1", True), "press")

    def test_injected_up_does_not_end_a_physical_hold(self) -> None:
        tracker = MouseButtonTracker("MOUSE1")
        self.assertEqual(tracker.handle("MOUSE1", True), "press")
        self.assertIsNone(tracker.handle("MOUSE1", False, injected=True))
        self.assertTrue(tracker.down)
        self.assertEqual(tracker.handle("MOUSE1", False), "release")

    def test_reset_clears_stuck_down_state(self) -> None:
        tracker = MouseButtonTracker("MOUSE1")
        tracker.handle("MOUSE1", True)
        tracker.reset()
        self.assertEqual(tracker.handle("MOUSE1", True), "press")
        self.assertEqual(tracker.handle("MOUSE1", False), "release")

    def test_side_button_binding(self) -> None:
        tracker = MouseButtonTracker("MOUSE4")
        self.assertEqual(tracker.handle("MOUSE4", True), "press")
        self.assertEqual(tracker.handle("MOUSE4", False), "release")


class TriggerRoutingTest(unittest.TestCase):
    def test_disarmed_never_fires(self) -> None:
        for tab in (0, 1):
            self.assertIsNone(
                resolve_trigger_kind(armed=False, recording=False, busy=False, tab_index=tab)
            )

    def test_armed_profile_tab(self) -> None:
        self.assertEqual(
            resolve_trigger_kind(armed=True, recording=False, busy=False, tab_index=0),
            "profile",
        )

    def test_armed_auto_tab(self) -> None:
        self.assertEqual(
            resolve_trigger_kind(armed=True, recording=False, busy=False, tab_index=1),
            "auto",
        )

    def test_recording_and_busy_block_both_tabs(self) -> None:
        for tab in (0, 1):
            self.assertIsNone(
                resolve_trigger_kind(armed=True, recording=True, busy=False, tab_index=tab)
            )
            self.assertIsNone(
                resolve_trigger_kind(armed=True, recording=False, busy=True, tab_index=tab)
            )


class FakeBackend(ClickBackend):
    name = "fake"

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self.pressed = threading.Event()

    def press(self, button: str, target, own_pid: int) -> ClickResult:
        self.events.append(("press", button))
        self.pressed.set()
        return ClickResult(True)

    def release(self, button: str) -> ClickResult:
        self.events.append(("release", button))
        return ClickResult(True)


class ReleaseMidClickTest(unittest.TestCase):
    def test_stop_during_hold_always_releases_and_counts_click(self) -> None:
        backend = FakeBackend()
        profile = ClickProfile(clicks=[Click(hold_ms=300, gap_ms=500)], button="left")
        session = PlaybackSession(
            profile=profile,
            target=Target.any_target(),
            backend=backend,
            own_pid=1,
            dry_run=False,
            restricted=False,
        )
        session.start()
        self.assertTrue(backend.pressed.wait(2.0), "click never started")
        session.stop()  # equivalent to releasing the mouse trigger mid-click
        session.wait(3000)
        self.assertFalse(session.isRunning())
        self.assertEqual([name for name, _ in backend.events], ["press", "release"])
        self.assertGreaterEqual(session.summary()["sent"], 1)
        self.assertFalse(session.snapshot().held, "button left logically down")


if __name__ == "__main__":
    unittest.main()
