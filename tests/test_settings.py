"""AppSettings persistence, clamping and tolerant loading."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from app.core import paths  # noqa: E402
from app.core.settings import AppSettings, load_settings, save_settings  # noqa: E402


class SettingsRoundTripTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "settings.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_defaults_when_missing(self) -> None:
        settings = load_settings(self.path)
        self.assertEqual(settings.auto_min_cps, 8.0)
        self.assertEqual(settings.auto_max_cps, 14.0)
        self.assertEqual(settings.auto_button, "left")
        self.assertEqual(settings.auto_method, "blatant")
        self.assertAlmostEqual(settings.auto_sigma, 0.15)
        self.assertEqual(settings.active_tab, 0)
        self.assertFalse(settings.compact_enabled)
        self.assertIsNone(settings.window_geometry)
        self.assertTrue(settings.music_enabled)
        self.assertAlmostEqual(settings.music_volume, 0.30)

    def test_round_trip(self) -> None:
        settings = AppSettings(
            auto_min_cps=5.5,
            auto_max_cps=17.0,
            auto_button="right",
            auto_method="gaussian_poisson",
            auto_sigma=0.22,
            active_tab=1,
            compact_enabled=True,
            window_geometry=[10, 20, 1200, 800],
            compact_pos=[300, 200],
        )
        save_settings(self.path, settings)
        loaded = load_settings(self.path)
        self.assertEqual(loaded.auto_min_cps, 5.5)
        self.assertEqual(loaded.auto_max_cps, 17.0)
        self.assertEqual(loaded.auto_button, "right")
        self.assertEqual(loaded.auto_method, "gaussian_poisson")
        self.assertAlmostEqual(loaded.auto_sigma, 0.22)
        self.assertEqual(loaded.active_tab, 1)
        self.assertTrue(loaded.compact_enabled)
        self.assertEqual(loaded.window_geometry, [10, 20, 1200, 800])
        self.assertEqual(loaded.compact_pos, [300, 200])

    def test_invalid_json_falls_back_to_defaults(self) -> None:
        self.path.write_text("{not json", encoding="utf-8")
        settings = load_settings(self.path)
        self.assertEqual(settings.auto_max_cps, 14.0)
        self.assertIsNone(settings.window_geometry)

    def test_clamps_and_swaps_bounds(self) -> None:
        self.path.write_text(
            json.dumps({"auto_min_cps": 90, "auto_max_cps": 2, "auto_button": "side"}),
            encoding="utf-8",
        )
        settings = load_settings(self.path)
        self.assertEqual((settings.auto_min_cps, settings.auto_max_cps), (2.0, 50.0))
        self.assertEqual(settings.auto_button, "left")

    def test_invalid_method_and_sigma_fall_back_and_clamp(self) -> None:
        self.path.write_text(
            json.dumps({"auto_method": "turbo", "auto_sigma": 3.0}),
            encoding="utf-8",
        )
        settings = load_settings(self.path)
        self.assertEqual(settings.auto_method, "blatant")
        self.assertAlmostEqual(settings.auto_sigma, 0.40)
        for method in ("gaussian", "poisson", "gaussian_poisson", "static", "blatant"):
            self.path.write_text(json.dumps({"auto_method": method}), encoding="utf-8")
            self.assertEqual(load_settings(self.path).auto_method, method)

    def test_rejects_bad_geometry(self) -> None:
        self.path.write_text(
            json.dumps({"window_geometry": [0, 0, 100, 100], "compact_pos": "nope"}),
            encoding="utf-8",
        )
        settings = load_settings(self.path)
        self.assertIsNone(settings.window_geometry)
        self.assertIsNone(settings.compact_pos)

    def test_active_tab_is_normalised(self) -> None:
        self.path.write_text(json.dumps({"active_tab": 7}), encoding="utf-8")
        self.assertEqual(load_settings(self.path).active_tab, 0)
        self.path.write_text(json.dumps({"active_tab": 1}), encoding="utf-8")
        self.assertEqual(load_settings(self.path).active_tab, 1)

    def test_invalid_active_tab_falls_back(self) -> None:
        self.path.write_text(json.dumps({"active_tab": "auto"}), encoding="utf-8")
        self.assertEqual(load_settings(self.path).active_tab, 0)


class MusicSettingsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "settings.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_default_volume_is_thirty_percent(self) -> None:
        self.assertAlmostEqual(AppSettings().music_volume, 0.30)
        self.assertTrue(AppSettings().music_enabled)

    def test_music_option_and_volume_roundtrip(self) -> None:
        settings = AppSettings(music_enabled=True, music_volume=0.62)
        save_settings(self.path, settings)
        loaded = load_settings(self.path)
        self.assertTrue(loaded.music_enabled)
        self.assertAlmostEqual(loaded.music_volume, 0.62)
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertTrue(raw["music_enabled"])
        self.assertAlmostEqual(raw["music_volume"], 0.62)

    def test_volume_is_clamped(self) -> None:
        self.path.write_text(json.dumps({"music_volume": 4.5}), encoding="utf-8")
        self.assertEqual(load_settings(self.path).music_volume, 1.0)
        self.path.write_text(json.dumps({"music_volume": -2}), encoding="utf-8")
        self.assertEqual(load_settings(self.path).music_volume, 0.0)

    def test_invalid_music_fields_fall_back(self) -> None:
        self.path.write_text(
            json.dumps({"music_enabled": "yes", "music_volume": "loud"}),
            encoding="utf-8",
        )
        loaded = load_settings(self.path)
        self.assertTrue(loaded.music_enabled)
        self.assertAlmostEqual(loaded.music_volume, 0.30)

    def test_missing_music_fields_keep_defaults(self) -> None:
        self.path.write_text(json.dumps({"auto_method": "static"}), encoding="utf-8")
        loaded = load_settings(self.path)
        self.assertTrue(loaded.music_enabled)
        self.assertAlmostEqual(loaded.music_volume, 0.30)


class DataDirectoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._old = {k: os.environ.get(k) for k in ("KIRBYCLICKER_DATA", "GMKCLICKER_DATA", "RECORD_CLICKER_DATA", "LOCALAPPDATA")}
        for key in self._old:
            os.environ.pop(key, None)
        paths._migrated_from = None

    def tearDown(self) -> None:
        for key, value in self._old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        paths._migrated_from = None
        self._tmp.cleanup()

    def test_override_env_is_used(self) -> None:
        target = self.root / "portable"
        os.environ["KIRBYCLICKER_DATA"] = str(target)
        self.assertEqual(paths.data_directory(), target)
        self.assertTrue(target.is_dir())

    def test_legacy_env_override_still_honoured(self) -> None:
        target = self.root / "legacy-env"
        os.environ["GMKCLICKER_DATA"] = str(target)
        self.assertEqual(paths.data_directory(), target)

    def test_legacy_recordclicker_folder_is_migrated(self) -> None:
        os.environ["LOCALAPPDATA"] = str(self.root)
        old = self.root / "RecordClicker"
        (old / "profiles").mkdir(parents=True)
        (old / "binds.txt").write_text("toggle=F9\n", encoding="utf-8")
        (old / "profiles" / "rec.txt").write_text("x", encoding="utf-8")
        real_frozen = paths.is_frozen
        paths.is_frozen = lambda: True  # type: ignore[assignment]
        try:
            new = paths.data_directory()
        finally:
            paths.is_frozen = real_frozen  # type: ignore[assignment]
        self.assertEqual(new, self.root / "KirbyClicker")
        self.assertTrue((new / "binds.txt").is_file())
        self.assertTrue((new / "profiles" / "rec.txt").is_file())
        self.assertEqual(paths.migration_source(), old)

    def test_gmkclicker_folder_is_preferred_over_recordclicker(self) -> None:
        os.environ["LOCALAPPDATA"] = str(self.root)
        older = self.root / "RecordClicker"
        older.mkdir()
        (older / "binds.txt").write_text("toggle=F8\n", encoding="utf-8")
        old = self.root / "GMKClicker"
        old.mkdir()
        (old / "binds.txt").write_text("toggle=F9\n", encoding="utf-8")
        real_frozen = paths.is_frozen
        paths.is_frozen = lambda: True  # type: ignore[assignment]
        try:
            new = paths.data_directory()
        finally:
            paths.is_frozen = real_frozen  # type: ignore[assignment]
        self.assertEqual(new, self.root / "KirbyClicker")
        self.assertEqual((new / "binds.txt").read_text(encoding="utf-8"), "toggle=F9\n")
        self.assertEqual(paths.migration_source(), old)

    def test_existing_kirby_folder_is_never_overwritten(self) -> None:
        os.environ["LOCALAPPDATA"] = str(self.root)
        old = self.root / "GMKClicker"
        old.mkdir()
        (old / "binds.txt").write_text("toggle=F8\n", encoding="utf-8")
        new = self.root / "KirbyClicker"
        (new / "profiles").mkdir(parents=True)
        (new / "binds.txt").write_text("toggle=INSERT\n", encoding="utf-8")
        real_frozen = paths.is_frozen
        paths.is_frozen = lambda: True  # type: ignore[assignment]
        try:
            result = paths.data_directory()
        finally:
            paths.is_frozen = real_frozen  # type: ignore[assignment]
        self.assertEqual(result, new)
        self.assertEqual((new / "binds.txt").read_text(encoding="utf-8"), "toggle=INSERT\n")
        self.assertIsNone(paths.migration_source())


if __name__ == "__main__":
    unittest.main()
