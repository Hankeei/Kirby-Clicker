"""Restricted-scope safety guard decisions (no real windows required)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from app.core.backends import NullBackend  # noqa: E402
from app.core.player import PlaybackSession  # noqa: E402
from app.core.profile import Click, ClickProfile  # noqa: E402
from app.core.windows import Target  # noqa: E402

TARGET = Target(any_process=False, hwnd=0x1234, pid=4242, exe="game.exe", title="Game")


def make_session(restricted: bool = True) -> PlaybackSession:
    return PlaybackSession(
        profile=ClickProfile(clicks=[Click(10, 20)], button="left"),
        target=TARGET,
        backend=NullBackend(),
        own_pid=1,
        dry_run=False,
        restricted=restricted,
    )


class ScopeGuardTest(unittest.TestCase):
    def test_unrestricted_never_stops(self) -> None:
        session = make_session(restricted=False)
        with patch("app.core.player.win32.is_window", return_value=False):
            self.assertEqual(session._scope_problem(), "")

    def test_closed_target_stops(self) -> None:
        session = make_session()
        with patch("app.core.player.win32.is_window", return_value=False):
            self.assertEqual(session._scope_problem(), "Target window closed")

    def test_focus_loss_stops_only_after_target_had_focus(self) -> None:
        session = make_session()
        with patch("app.core.player.win32.is_window", return_value=True):
            with patch.object(session, "_foreground_is_target", return_value=False):
                self.assertEqual(session._scope_problem(), "")
            with patch.object(session, "_foreground_is_target", return_value=True):
                self.assertEqual(session._scope_problem(), "")
                self.assertTrue(session._had_target_focus)
            with patch.object(session, "_foreground_is_target", return_value=False):
                self.assertEqual(session._scope_problem(), "Target lost foreground focus")

    def test_dry_run_is_not_stopped_by_focus(self) -> None:
        session = make_session()
        session.dry_run = True
        self.assertEqual(session._scope_problem(), "")


if __name__ == "__main__":
    unittest.main()
