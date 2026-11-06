"""Bind-file compatibility and rebind validation tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from app.core.binds import BindError, BindSet, canonical_key, load_binds, save_binds  # noqa: E402


class BindFileTest(unittest.TestCase):
    def test_legacy_bind_file(self) -> None:
        text = "\n".join(
            [
                "# legacy keybinds (no trigger line)",
                "# Keys: A-Z, 0-9, F1-F24, NUMPAD0-NUMPAD9, SPACE, TAB, INSERT, DELETE, HOME, END,",
                "record=F8",
                "toggle=2",
                "quit=F12",
                "rebind=INSERT",
                "selector=F10",
                "# target = executable the clicker is restricted to (empty = any process)",
                "target=javaw.exe",
                "",
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy_binds.txt"
            path.write_text(text, encoding="utf-8")
            binds = load_binds(path)
            self.assertEqual(binds.record, "F8")
            self.assertEqual(binds.toggle, "2")
            self.assertEqual(binds.trigger, "MOUSE1")  # legacy file -> left mouse default
            self.assertEqual(binds.quit, "F12")
            self.assertEqual(binds.selector, "F10")
            self.assertEqual(binds.rebind, "INSERT")
            self.assertEqual(binds.target_exe, "javaw.exe")
            save_binds(path, binds)
            reloaded = load_binds(path)
            self.assertEqual(reloaded.toggle, "2")
            self.assertEqual(reloaded.trigger, "MOUSE1")
            self.assertIn("trigger=MOUSE1", path.read_text(encoding="utf-8"))

    def test_defaults(self) -> None:
        binds = BindSet()
        self.assertEqual(binds.toggle, "F9")
        self.assertEqual(binds.trigger, "MOUSE1")
        binds.validate()

    def test_trigger_cannot_be_keyboard(self) -> None:
        with self.assertRaises(BindError) as ctx:
            BindSet(trigger="F9").validate()
        self.assertIn("mouse button", str(ctx.exception))

    def test_trigger_can_be_any_mouse_button(self) -> None:
        for key in ("MOUSE1", "MOUSE2", "MOUSE3", "MOUSE4", "MOUSE5"):
            BindSet(trigger=key).validate()

    def test_mouse_key_rejected_for_other_actions(self) -> None:
        binds = BindSet(toggle="MOUSE3")
        with self.assertRaises(BindError):
            binds.validate()
        self.assertEqual(binds.first_mouse_action(), ("toggle", "MOUSE3"))

    def test_trigger_duplicate_with_other_action_is_rejected(self) -> None:
        binds = BindSet(record="MOUSE1")  # already rejected as a mouse hotkey
        with self.assertRaises(BindError):
            binds.validate()

    def test_trigger_rebind_is_persisted(self) -> None:
        binds = BindSet()
        binds.set("trigger", "MOUSE2")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "binds.txt"
            save_binds(path, binds)
            reloaded = load_binds(path)
            self.assertEqual(reloaded.trigger, "MOUSE2")
            self.assertIn("trigger=MOUSE2", path.read_text(encoding="utf-8"))

    def test_legacy_hold_mouse_value_migrates_to_trigger(self) -> None:
        text = "record=F8\ntoggle=F9\nhold=MOUSE2\nquit=F12\nrebind=INSERT\nselector=F10\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "binds.txt"
            path.write_text(text, encoding="utf-8")
            binds = load_binds(path)
            self.assertEqual(binds.trigger, "MOUSE2")
            self.assertEqual(binds.toggle, "F9")

    def test_legacy_hold_keyboard_value_is_ignored(self) -> None:
        text = "record=F8\ntoggle=F9\nhold=F7\nquit=F12\nrebind=INSERT\nselector=F10\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "binds.txt"
            path.write_text(text, encoding="utf-8")
            binds = load_binds(path)
            self.assertEqual(binds.trigger, "MOUSE1")
            self.assertEqual(binds.toggle, "F9")

    def test_arm_rebind_is_persisted(self) -> None:
        binds = BindSet()
        binds.set("toggle", "F7")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "binds.txt"
            save_binds(path, binds)
            reloaded = load_binds(path)
            self.assertEqual(reloaded.toggle, "F7")
            self.assertIn("toggle=F7", path.read_text(encoding="utf-8"))

    def test_duplicate_bind_is_rejected(self) -> None:
        with self.assertRaises(BindError):
            BindSet(record="F8", toggle="F8").validate()

    def test_key_aliases(self) -> None:
        self.assertEqual(canonical_key("ins"), "INSERT")
        self.assertEqual(canonical_key("pgup"), "PAGEUP")
        self.assertEqual(canonical_key("esc"), "ESC")
        self.assertEqual(canonical_key("lmb"), "MOUSE1")
        self.assertEqual(canonical_key("rmb"), "MOUSE2")

    def test_scope_persists_and_roundtrips(self) -> None:
        binds = BindSet(scope="restricted", target_exe="notepad.exe")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "binds.txt"
            save_binds(path, binds)
            self.assertIn("scope=restricted", path.read_text(encoding="utf-8"))
            reloaded = load_binds(path)
            self.assertEqual(reloaded.scope, "restricted")
            self.assertEqual(reloaded.target_exe, "notepad.exe")

    def test_missing_scope_is_inferred_from_target(self) -> None:
        text = "record=F8\ntoggle=F9\nquit=F12\nrebind=INSERT\nselector=F10\ntarget=game.exe\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old_binds.txt"
            path.write_text(text, encoding="utf-8")
            self.assertEqual(load_binds(path).scope, "restricted")
            path.write_text(text.replace("target=game.exe", "target="), encoding="utf-8")
            self.assertEqual(load_binds(path).scope, "anywhere")

    def test_invalid_scope_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "binds.txt"
            path.write_text("scope=sometimes\n", encoding="utf-8")
            with self.assertRaises(BindError) as ctx:
                load_binds(path)
            self.assertIn("scope must be", str(ctx.exception))

    def test_hotkeys_skip_the_mouse_trigger(self) -> None:
        binds = BindSet()
        actions = [action for action, _vk in binds.hotkeys()]
        self.assertNotIn("trigger", actions)
        self.assertIn("toggle", actions)


if __name__ == "__main__":
    unittest.main()
