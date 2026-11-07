"""Profile format compatibility and exact hold/gap round-trip checks."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from app.core.profile import (  # noqa: E402
    Click,
    ClickProfile,
    ProfileFormatError,
    compute_stats,
    generate_profile,
    load_profile,
    profile_name_problem,
    rename_profile_file,
    save_profile,
)


class ProfileRoundTripTest(unittest.TestCase):
    def test_synthetic_generator_roundtrip_is_exact(self) -> None:
        profile = generate_profile(10288, seed=20261105)
        self.assertEqual(len(profile.clicks), 10288)
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.txt"
            second = Path(tmp) / "second.txt"
            saved = save_profile(first, profile)
            loaded = load_profile(first)
            self.assertEqual(len(loaded.clicks), 10288)
            self.assertEqual(
                [(c.hold_ms, c.gap_ms) for c in loaded.clicks],
                [(c.hold_ms, c.gap_ms) for c in profile.clicks],
            )
            self.assertEqual(loaded.button, "left")
            stats = compute_stats(profile.clicks)
            self.assertEqual(stats.clicks, 10288)
            self.assertGreater(stats.avg_cps, 15.0)
            self.assertLess(stats.avg_cps, 25.0)
            self.assertEqual(stats.min_interval_ms, min(c.hold_ms + c.gap_ms for c in profile.clicks))
            self.assertEqual(stats.max_interval_ms, max(c.hold_ms + c.gap_ms for c in profile.clicks))

            header = first.read_text(encoding="utf-8").splitlines()[:9]
            self.assertEqual(header[0], "# ClickProfile v1 (Kirby Clicker)")
            self.assertEqual(header[3], "button=left")
            self.assertEqual(header[4], "clicks=10288")
            self.assertEqual(header[8], "# data")

            # Save the loaded object again: v1 output must be byte-identical.
            save_profile(second, loaded)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_legacy_gmk_header_still_loads(self) -> None:
        text = "\n".join(
            [
                "# ClickProfile v1 (GMK Clicker)",
                "# Each data line: <hold_ms> <gap_ms>",
                "# hold_ms = how long the button stays down, gap_ms = wait until the next press",
                "button=left",
                "clicks=3",
                "avg_cps=19.05",
                "min_interval_ms=22",
                "max_interval_ms=200",
                "# data",
                "11 36",
                "18 29",
                "18 24",
                "",
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reference.txt"
            path.write_text(text, encoding="utf-8")
            profile = load_profile(path)
            self.assertEqual([(c.hold_ms, c.gap_ms) for c in profile.clicks], [(11, 36), (18, 29), (18, 24)])
            self.assertEqual(profile.button, "left")
            with tempfile.TemporaryDirectory() as tmp2:
                out = Path(tmp2) / "out.txt"
                save_profile(out, profile)
                lines = out.read_text(encoding="utf-8").splitlines()
                self.assertEqual(lines[4], "clicks=3")
                self.assertEqual(lines[-3:], ["11 36", "18 29", "18 24"])

    def test_mixed_buttons_are_rejected_by_v1_writer(self) -> None:
        profile = ClickProfile(clicks=[Click(10, 20, "left"), Click(10, 20, "right")], button="left")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(Exception):
                save_profile(Path(tmp) / "bad.txt", profile)


class ProfileRenameTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.source = self.folder / "rec1.txt"
        self.source.write_text("# ClickProfile v1\n# data\n10 20\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_rename_moves_the_file_and_keeps_its_content(self) -> None:
        target = rename_profile_file(self.source, "session")
        self.assertEqual(target, self.folder / "session.txt")
        self.assertTrue(target.is_file())
        self.assertFalse(self.source.exists())
        self.assertEqual(target.read_text(encoding="utf-8").splitlines()[-1], "10 20")

    def test_txt_suffix_is_implied_and_not_doubled(self) -> None:
        self.assertEqual(rename_profile_file(self.source, "session.txt").name, "session.txt")

    def test_same_name_is_a_no_op(self) -> None:
        self.assertEqual(rename_profile_file(self.source, "rec1"), self.source)
        self.assertTrue(self.source.exists())

    def test_invalid_names_are_rejected_without_touching_the_file(self) -> None:
        for name in ("", "   ", ".", "..", "a/b", "a\\b", "bad:name", "bad*name", "trailing.", ".txt"):
            with self.subTest(name=name):
                self.assertIsNotNone(profile_name_problem(name))
                with self.assertRaises(ProfileFormatError):
                    rename_profile_file(self.source, name)
                self.assertTrue(self.source.exists())

    def test_existing_name_is_a_conflict_and_is_never_overwritten(self) -> None:
        other = self.folder / "taken.txt"
        other.write_text("keep me", encoding="utf-8")
        with self.assertRaises(ProfileFormatError):
            rename_profile_file(self.source, "taken")
        self.assertEqual(other.read_text(encoding="utf-8"), "keep me")
        self.assertTrue(self.source.exists())


if __name__ == "__main__":
    unittest.main()
