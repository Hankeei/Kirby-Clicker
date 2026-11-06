"""Redesign guarantees: recN auto-naming, backend from settings, ON/OFF wording."""

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

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QMovie  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from app.core.profile import next_recording_path  # noqa: E402
from app.core.settings import AppSettings, load_settings, save_settings  # noqa: E402
from app.core.trigger import ArmState  # noqa: E402
from app.ui import theme  # noqa: E402
from app.ui.main_window import BITE_LIP_RATIO, MainWindow  # noqa: E402
from app.ui.widgets import PatternBackdrop  # noqa: E402


class RecordingNameTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_first_recording_is_rec1(self) -> None:
        self.assertEqual(next_recording_path(self.folder).name, "rec1.txt")

    def test_lowest_unused_number_is_picked(self) -> None:
        (self.folder / "rec1.txt").write_text("x", encoding="utf-8")
        (self.folder / "rec3.txt").write_text("x", encoding="utf-8")
        self.assertEqual(next_recording_path(self.folder).name, "rec2.txt")

    def test_other_names_do_not_shift_numbering(self) -> None:
        (self.folder / "old-session.txt").write_text("x", encoding="utf-8")
        (self.folder / "rec2.txt").write_text("x", encoding="utf-8")
        self.assertEqual(next_recording_path(self.folder).name, "rec1.txt")

    def test_contiguous_files_advance(self) -> None:
        for number in (1, 2, 3):
            (self.folder / f"rec{number}.txt").write_text("x", encoding="utf-8")
        self.assertEqual(next_recording_path(self.folder).name, "rec4.txt")

    def test_existing_files_are_untouched(self) -> None:
        legacy = self.folder / "old-session.txt"
        legacy.write_text("keep me", encoding="utf-8")
        next_recording_path(self.folder)
        self.assertEqual(legacy.read_text(encoding="utf-8"), "keep me")


class SettingsBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "settings.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_default_backend_is_foreground(self) -> None:
        self.assertEqual(AppSettings().click_backend, "foreground")

    def test_backend_roundtrips(self) -> None:
        settings = AppSettings(click_backend="background")
        save_settings(self.path, settings)
        self.assertEqual(load_settings(self.path).click_backend, "background")

    def test_unknown_backend_falls_back(self) -> None:
        self.path.write_text(json.dumps({"click_backend": "magic"}), encoding="utf-8")
        self.assertEqual(load_settings(self.path).click_backend, "foreground")

    def test_legacy_settings_without_backend_still_load(self) -> None:
        self.path.write_text(json.dumps({"auto_min_cps": 12.0, "auto_method": "static"}),
                             encoding="utf-8")
        loaded = load_settings(self.path)
        self.assertEqual(loaded.auto_method, "static")
        self.assertEqual(loaded.click_backend, "foreground")


class OnOffStateTest(unittest.TestCase):
    def test_arm_state_labels(self) -> None:
        self.assertEqual(ArmState().label(), "OFF")
        self.assertEqual(ArmState(armed=True).label(), "ON")
        self.assertEqual(ArmState(armed=True, clicking=True).label(), "ON")


class RedesignWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        patches = [
            mock.patch.object(MainWindow, "_start_hotkeys", lambda _self: None),
            mock.patch.object(MainWindow, "_restart_trigger_monitor", lambda _self: None),
            mock.patch.object(MainWindow, "_refresh_targets", lambda *_a, **_k: None),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.window = MainWindow(Path(self._tmp.name))
        self.window.show()
        self.window._timer.stop()

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self._tmp.cleanup()

    def test_numbers_and_log_panels_are_gone(self) -> None:
        for name in (
            "log_panel",
            "log_view",
            "playback_panel",
            "cps_value",
            "target_cps_value",
            "sent_value",
            "held_value",
            "status_mode",
            "status_stats",
            "binds_panel",
            "header_hotkeys",
        ):
            self.assertFalse(hasattr(self.window, name), f"{name} should be removed")

    def test_state_word_is_on_off(self) -> None:
        window = self.window
        self.assertEqual(window.state_text(), "OFF")
        window._toggle_arm()
        self.assertEqual(window.state_text(), "ON")
        self.assertEqual(window.arm_button.text(), "ON")
        window._toggle_arm()
        self.assertEqual(window.state_text(), "OFF")
        self.assertEqual(window.arm_button.text(), "OFF")

    def test_backend_change_persists_to_settings(self) -> None:
        window = self.window
        index = window.backend_combo.findData("background")
        self.assertGreaterEqual(index, 0)
        window.backend_combo.setCurrentIndex(index)
        self.assertEqual(window.backend_name, "background")
        saved = json.loads((Path(self._tmp.name) / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["click_backend"], "background")

    def test_compact_overlay_uses_on_off_and_pink_activity(self) -> None:
        overlay = self.window._ensure_overlay()
        overlay.set_state(True, False, "GAUSS", [])
        self.assertEqual(overlay.state_button.text(), "ON")
        overlay.set_state(True, True, "GAUSS", [])
        self.assertIn(theme.PINK, overlay.dot.styleSheet())
        overlay.set_state(False, False, "GAUSS", [])
        self.assertEqual(overlay.state_button.text(), "OFF")

    def test_rhythm_strip_is_tiny(self) -> None:
        strip = self.window.rhythm
        self.assertLessEqual(strip.width(), 140)
        self.assertLessEqual(strip.height(), 28)

    def test_mascot_art_and_cat_are_present(self) -> None:
        self.assertFalse(self.window.mascot.pixmap().isNull())
        self.assertTrue(self.window.mascot.testAttribute(Qt.WA_TransparentForMouseEvents))
        self.assertTrue(self.window.cat_movie.isValid())
        self.assertEqual(self.window.cat_movie.state(), QMovie.NotRunning)

    def test_mascot_swaps_with_tab_and_state(self) -> None:
        self.window.tabs.setCurrentIndex(1)
        self.assertIn("pikachu", self.window._mascot_file())
        self.window.tabs.setCurrentIndex(0)
        self.assertIn("mascot_kirby", self.window._mascot_file())
        self.window._toggle_arm()
        self.assertIn("mascot_eat", self.window._mascot_file())
        self.window._toggle_arm()

    def test_cat_animation_follows_state(self) -> None:
        self.window._toggle_arm()
        self.assertEqual(self.window.cat_movie.state(), QMovie.Running)
        self.window._toggle_arm()
        self.assertEqual(self.window.cat_movie.state(), QMovie.NotRunning)
        self.assertEqual(self.window.cat_movie.currentFrameNumber(), 0)

    def test_bite_chomps_the_record_pill(self) -> None:
        window = self.window
        window.tabs.setCurrentIndex(0)
        window.resize(560, 437)
        window._place_bite()
        bite = window.bite_label
        pill = window.record_button
        root = window._root
        self.assertTrue(bite.isVisible())
        self.assertEqual(bite.parent(), root)
        # Click-through: it must never swallow a press meant for the button.
        self.assertTrue(bite.testAttribute(Qt.WA_TransparentForMouseEvents))
        bite_rect = bite.geometry()
        pill_pos = pill.mapTo(root, QPoint(0, 0))
        # The pill's left end sits inside the open mouth.
        self.assertLess(bite_rect.left(), pill_pos.x())
        self.assertGreater(bite_rect.right(), pill_pos.x() + 8)
        # The mouth's lower lip rests on the pill's top edge, never below it.
        self.assertLessEqual(abs(BITE_LIP_RATIO - 19 / 60), 0.03)
        lip = bite_rect.top() + round(bite_rect.height() * BITE_LIP_RATIO)
        self.assertLessEqual(abs(lip - pill_pos.y()), 2)
        # The art hangs above the button, so it is not cut by the window edge.
        self.assertGreaterEqual(bite_rect.left(), 0)
        self.assertGreaterEqual(bite_rect.top(), 0)

    def test_bite_hides_off_the_recorder_tab(self) -> None:
        window = self.window
        window.tabs.setCurrentIndex(1)
        window._place_bite()
        self.assertFalse(window.bite_label.isVisible())
        window.tabs.setCurrentIndex(0)
        window._place_bite()
        self.assertTrue(window.bite_label.isVisible())

    def test_window_shrinks_back_to_the_old_compact_size(self) -> None:
        window = self.window
        self.assertEqual(window.minimumWidth(), 440)
        self.assertEqual(window.minimumHeight(), 250)
        window.resize(440, 250)
        window.tabs.setCurrentIndex(0)
        window._place_bite()
        # The record row must still fit inside the visible tab area.
        page = window._recorder_page
        stack = window.tabs._stack
        button = window.record_button
        self.assertLessEqual(button.mapTo(page, QPoint(0, 0)).x() + button.width(), page.width())
        self.assertLessEqual(stack.height(), page.height() + 2)
        # And the bite still clamps the pill at that size.
        bite_rect = window.bite_label.geometry()
        pill_pos = button.mapTo(window._root, QPoint(0, 0))
        self.assertGreater(bite_rect.right(), pill_pos.x() + 8)
        lip = bite_rect.top() + round(bite_rect.height() * BITE_LIP_RATIO)
        self.assertLessEqual(abs(lip - pill_pos.y()), 2)

    def test_auto_tab_scrolls_instead_of_clipping(self) -> None:
        window = self.window
        window.resize(440, 250)
        window.tabs.setCurrentIndex(1)
        window.show()
        window._timer.stop()
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        self.assertEqual(len(window._scrolls), 2)
        scroll = window._scrolls[1]
        self.assertTrue(scroll.widgetResizable())
        self.assertEqual(scroll.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)
        # Taller than the viewport at the minimum size: scrolling, not clipping.
        self.assertGreater(scroll.widget().height(), scroll.viewport().height())

    def test_backdrop_tiles_the_wallpaper_at_natural_scale(self) -> None:
        root = self.window.centralWidget()
        self.assertIsInstance(root, PatternBackdrop)
        tile = PatternBackdrop._tile
        self.assertFalse(tile.isNull())
        # 1080 px is the tile's own size: never stretched, only repeated.
        self.assertEqual(tile.width(), 1080)
        self.assertEqual(tile.height(), 1080)

    def test_settings_music_defaults_and_persistence(self) -> None:
        window = self.window
        # Background music is on by default and independent of ON/OFF.
        self.assertTrue(window.music_check.isChecked())
        self.assertEqual(window.music_slider.value(), 30)
        self.assertEqual(window.music_value.text(), "30%")
        window.music_check.setChecked(False)
        window.music_slider.setValue(55)
        saved = json.loads(
            (Path(self._tmp.name) / "settings.json").read_text(encoding="utf-8")
        )
        self.assertFalse(saved["music_enabled"])
        self.assertAlmostEqual(saved["music_volume"], 0.55)
        self.assertAlmostEqual(window.music.volume(), 0.55)
        self.assertFalse(window.settings.music_enabled)
        self.assertFalse(window.music.is_playing())

    def test_settings_footer_has_signature_and_clickable_link(self) -> None:
        dialog = self.window.settings_dialog
        signature = dialog.findChild(QLabel, "Signature")
        self.assertIsNotNone(signature)
        self.assertEqual(signature.text(), "vibe coded by @hankeei <3")
        link = self.window.link_button
        self.assertEqual(link.text(), "https://linktr.ee/hankeei")
        self.assertEqual(link.accessibleName(), "Linktree")
        self.assertNotEqual(link.focusPolicy(), Qt.NoFocus)
        with mock.patch("app.ui.dialogs.QDesktopServices.openUrl") as open_url:
            link.click()
        open_url.assert_called_once()
        self.assertIn("https://linktr.ee/hankeei", open_url.call_args.args[0].toString())


if __name__ == "__main__":
    unittest.main()
