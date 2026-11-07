"""Offscreen GUI tests for the auto-clicker bound sliders and method picker."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.autoclicker import METHOD_SHORT_LABELS  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


class AutoBoundsUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        patches = [
            mock.patch.object(MainWindow, "_start_hotkeys", lambda _self: None),
            mock.patch.object(MainWindow, "_restart_trigger_monitor", lambda _self: None),
            mock.patch.object(MainWindow, "_refresh_targets", lambda *_a, **_k: None),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.window = MainWindow(root)
        self.window._timer.stop()

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self._tmp.cleanup()

    def _saved(self) -> dict:
        path = Path(self._tmp.name) / "settings.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_lower_slider_pushes_upper_and_upper_pushes_lower(self) -> None:
        window = self.window
        window.auto_min_slider.setValue(200)  # 20 CPS, past the 14 CPS upper
        self.assertEqual((window.auto_min_spin.value(), window.auto_max_spin.value()), (20.0, 20.0))
        self.assertEqual(window.auto_max_slider.value(), 200)

        window.auto_max_slider.setValue(50)  # 5 CPS, below the lower bound
        self.assertEqual((window.auto_min_spin.value(), window.auto_max_spin.value()), (5.0, 5.0))
        self.assertEqual(window.auto_min_slider.value(), 50)

    def test_typed_value_syncs_slider_and_persists(self) -> None:
        window = self.window
        window.auto_max_spin.setValue(50.0)  # typed value beyond the 30 CPS slider band
        self.assertEqual(window.auto_max_spin.value(), 50.0)
        self.assertEqual(window.auto_max_slider.value(), 300)
        self.assertEqual(window.auto_min_slider.value(), 80)
        saved = self._saved()
        self.assertAlmostEqual(saved["auto_max_cps"], 50.0)
        self.assertAlmostEqual(saved["auto_min_cps"], 8.0)

    def test_static_mode_ties_both_bounds_and_both_controls(self) -> None:
        window = self.window
        window.auto_method_combo.setCurrentIndex(
            window.auto_method_combo.findData("static")
        )
        # The default 8/14 bounds collapse to their 11 CPS midpoint.
        self.assertEqual(
            (window.auto_min_spin.value(), window.auto_max_spin.value()), (11.0, 11.0)
        )
        self.assertEqual(
            (window.auto_min_slider.value(), window.auto_max_slider.value()), (110, 110)
        )

        window.auto_min_spin.setValue(20.0)
        self.assertEqual(
            (window.auto_min_spin.value(), window.auto_max_spin.value()), (20.0, 20.0)
        )
        self.assertEqual(
            (window.auto_min_slider.value(), window.auto_max_slider.value()), (200, 200)
        )

        window.auto_max_spin.setValue(7.5)
        self.assertEqual(
            (window.auto_min_spin.value(), window.auto_max_spin.value()), (7.5, 7.5)
        )
        self.assertEqual(
            (window.auto_min_slider.value(), window.auto_max_slider.value()), (75, 75)
        )

        window.auto_min_slider.setValue(250)
        self.assertEqual(
            (window.auto_min_spin.value(), window.auto_max_spin.value()), (25.0, 25.0)
        )
        self.assertEqual(
            (window.auto_min_slider.value(), window.auto_max_slider.value()), (250, 250)
        )

        window.auto_max_slider.setValue(120)
        self.assertEqual(
            (window.auto_min_spin.value(), window.auto_max_spin.value()), (12.0, 12.0)
        )
        self.assertEqual(
            (window.auto_min_slider.value(), window.auto_max_slider.value()), (120, 120)
        )
        saved = self._saved()
        self.assertAlmostEqual(saved["auto_min_cps"], 12.0)
        self.assertAlmostEqual(saved["auto_max_cps"], 12.0)

    def test_non_static_methods_keep_independent_bounds(self) -> None:
        window = self.window
        for method in ("blatant", "gaussian", "poisson", "gaussian_poisson"):
            with self.subTest(method=method):
                window.auto_method_combo.setCurrentIndex(
                    window.auto_method_combo.findData(method)
                )
                window.auto_min_spin.setValue(8.0)
                window.auto_max_spin.setValue(20.0)
                window.auto_min_spin.setValue(12.0)
                self.assertEqual(
                    (window.auto_min_spin.value(), window.auto_max_spin.value()),
                    (12.0, 20.0),
                )
                window.auto_max_spin.setValue(30.0)
                self.assertEqual(
                    (window.auto_min_spin.value(), window.auto_max_spin.value()),
                    (12.0, 30.0),
                )

    def test_method_and_sigma_enablement_persist(self) -> None:
        window = self.window
        self.assertFalse(window.auto_sigma_spin.isEnabled())  # blatant ignores sigma

        index = window.auto_method_combo.findData("gaussian")
        window.auto_method_combo.setCurrentIndex(index)
        self.assertTrue(window.auto_sigma_spin.isEnabled())
        self.assertEqual(METHOD_SHORT_LABELS[window._auto_method()], "GAUSS")

        window.auto_sigma_spin.setValue(25.0)
        window.auto_method_combo.setCurrentIndex(
            window.auto_method_combo.findData("gaussian_poisson")
        )
        saved = self._saved()
        self.assertEqual(saved["auto_method"], "gaussian_poisson")
        self.assertAlmostEqual(saved["auto_sigma"], 0.25)

        window.auto_method_combo.setCurrentIndex(
            window.auto_method_combo.findData("blatant")
        )
        self.assertFalse(window.auto_sigma_spin.isEnabled())
        self.assertEqual(METHOD_SHORT_LABELS[window._auto_method()], "RANDOM")

        window.auto_method_combo.setCurrentIndex(
            window.auto_method_combo.findData("static")
        )
        self.assertFalse(window.auto_sigma_spin.isEnabled())
        self.assertEqual(METHOD_SHORT_LABELS[window._auto_method()], "STATIC ⚠")
        self.assertEqual(self._saved()["auto_method"], "static")


if __name__ == "__main__":
    unittest.main()
