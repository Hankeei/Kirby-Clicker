"""Exchange v2 export/import, strict validation and conflict policy tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from app.core.profile import Click, ClickProfile, generate_profile, load_profile, save_profile  # noqa: E402
from app.core.transfer import (  # noqa: E402
    FORMAT_ID,
    FORMAT_VERSION,
    ProfileTransferError,
    _checksum,
    export_profile,
    import_profile_file,
)

V1_HEADER = "\n".join(
    [
        "# ClickProfile v1 (GMK Clicker)",
        "# Each data line: <hold_ms> <gap_ms>",
        "# hold_ms = how long the button stays down, gap_ms = wait until the next press",
        "button=left",
    ]
)


class ExchangeExportTest(unittest.TestCase):
    def test_export_structure_and_checksum(self) -> None:
        profile = generate_profile(12, seed=1)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.rcprofile.json"
            export_profile(path, profile, name="sample")
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["format"], FORMAT_ID)
            self.assertEqual(raw["version"], FORMAT_VERSION)
            self.assertEqual(raw["profile"]["name"], "sample")
            self.assertEqual(
                [tuple(pair) for pair in raw["profile"]["clicks"]],
                [(c.hold_ms, c.gap_ms) for c in profile.clicks],
            )
            self.assertEqual(raw["stats"]["clicks"], 12)
            body = {key: value for key, value in raw.items() if key != "checksum"}
            self.assertEqual(raw["checksum"], _checksum(body))

    def test_export_rejects_empty_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ProfileTransferError):
                export_profile(Path(tmp) / "empty.json", ClickProfile())

    def test_export_rejects_out_of_range(self) -> None:
        profile = ClickProfile(clicks=[Click(-1, 10)], button="left")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ProfileTransferError):
                export_profile(Path(tmp) / "bad.json", profile)


class ExchangeImportTest(unittest.TestCase):
    def test_full_roundtrip_preserves_10288_clicks(self) -> None:
        profile = generate_profile(10288, seed=20261105)
        with tempfile.TemporaryDirectory() as tmp:
            exchange = Path(tmp) / "export.rcprofile.json"
            library = Path(tmp) / "library"
            export_profile(exchange, profile, name="source")
            outcome = import_profile_file(exchange, library)
            self.assertEqual(outcome.format_label, f"exchange v{FORMAT_VERSION}")
            self.assertEqual(outcome.path.suffix, ".txt")
            self.assertEqual(outcome.path.name, "source.txt")
            loaded = load_profile(outcome.path)
            self.assertEqual(len(loaded.clicks), 10288)
            self.assertEqual(
                [(c.hold_ms, c.gap_ms) for c in loaded.clicks],
                [(c.hold_ms, c.gap_ms) for c in profile.clicks],
            )
            self.assertEqual(loaded.button, "left")

    def test_tampered_checksum_is_rejected_without_touching_library(self) -> None:
        profile = generate_profile(5, seed=2)
        with tempfile.TemporaryDirectory() as tmp:
            exchange = Path(tmp) / "tampered.rcprofile.json"
            export_profile(exchange, profile, name="tampered")
            raw = json.loads(exchange.read_text(encoding="utf-8"))
            raw["profile"]["clicks"][0][0] += 7
            exchange.write_text(json.dumps(raw), encoding="utf-8")

            library = Path(tmp) / "library"
            library.mkdir()
            existing = library / "keep.txt"
            save_profile(existing, generate_profile(3, seed=3))
            before = sorted(p.name for p in library.iterdir())

            with self.assertRaises(ProfileTransferError) as ctx:
                import_profile_file(exchange, library)
            self.assertIn("Checksum mismatch", str(ctx.exception))
            self.assertEqual(sorted(p.name for p in library.iterdir()), before)

    def test_unsupported_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            exchange = Path(tmp) / "future.rcprofile.json"
            exchange.write_text(
                json.dumps(
                    {
                        "format": FORMAT_ID,
                        "version": 3,
                        "profile": {"name": "x", "button": "left", "clicks": [[1, 2]]},
                        "stats": {},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ProfileTransferError) as ctx:
                import_profile_file(exchange, Path(tmp) / "library")
            self.assertIn("Unsupported profile version", str(ctx.exception))

    def test_foreign_and_malformed_json_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "library"
            for body in ('{"hello": "world"}', "{not json", "[]"):
                source = Path(tmp) / "bad.json"
                source.write_text(body, encoding="utf-8")
                with self.assertRaises(ProfileTransferError):
                    import_profile_file(source, library)

    def test_legacy_v1_text_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "other_user.txt"
            source.write_text(
                V1_HEADER + "\nclicks=2\navg_cps=19.05\n# data\n11 36\n18 29\n",
                encoding="utf-8",
            )
            library = Path(tmp) / "library"
            outcome = import_profile_file(source, library)
            self.assertEqual(outcome.format_label, "legacy v1 text")
            self.assertEqual(outcome.path.name, "other_user.txt")
            loaded = load_profile(outcome.path)
            self.assertEqual([(c.hold_ms, c.gap_ms) for c in loaded.clicks], [(11, 36), (18, 29)])

    def test_legacy_declared_count_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "truncated.txt"
            source.write_text(
                V1_HEADER + "\nclicks=3\n# data\n11 36\n18 29\n", encoding="utf-8"
            )
            with self.assertRaises(ProfileTransferError) as ctx:
                import_profile_file(source, Path(tmp) / "library")
            self.assertIn("declares 3 clicks", str(ctx.exception))

    def test_legacy_negative_values_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "negative.txt"
            source.write_text(V1_HEADER + "\nclicks=1\n# data\n-5 10\n", encoding="utf-8")
            with self.assertRaises(ProfileTransferError):
                import_profile_file(source, Path(tmp) / "library")

    def test_non_utf8_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "binary.txt"
            source.write_bytes(b"# ClickProfile v1\n# data\n11 36\n\xff\xfe")
            with self.assertRaises(ProfileTransferError) as ctx:
                import_profile_file(source, Path(tmp) / "library")
            self.assertIn("UTF-8", str(ctx.exception))

    def test_name_collision_renames_and_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src" / "duplicate.txt"
            source.parent.mkdir()
            source.write_text(V1_HEADER + "\nclicks=1\n# data\n10 20\n", encoding="utf-8")
            library = Path(tmp) / "library"
            library.mkdir()
            existing = library / "duplicate.txt"
            existing.write_text("sentinel — must not be replaced\n", encoding="utf-8")

            first = import_profile_file(source, library)
            self.assertEqual(first.path.name, "duplicate (imported).txt")
            self.assertEqual(existing.read_text(encoding="utf-8"), "sentinel — must not be replaced\n")
            second = import_profile_file(source, library)
            self.assertEqual(second.path.name, "duplicate (imported 2).txt")
            self.assertEqual(len([p for p in library.iterdir() if p.suffix == ".txt"]), 3)

    def test_name_sanitisation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src.txt"
            source.write_text(V1_HEADER + "\nclicks=1\n# data\n10 20\n", encoding="utf-8")
            outcome = import_profile_file(source, Path(tmp) / "library", name_override="CON")
            self.assertEqual(outcome.path.name, "CON-profile.txt")
            outcome = import_profile_file(
                source, Path(tmp) / "library2", name_override='a/b:c*?"< >'
            )
            self.assertNotIn("/", outcome.path.name)
            self.assertNotIn(":", outcome.path.name)

    def test_bad_file_does_not_modify_existing_library(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "library"
            library.mkdir()
            keep = library / "keep.txt"
            save_profile(keep, generate_profile(4, seed=4))
            before = keep.read_bytes()
            bad = Path(tmp) / "bad.txt"
            bad.write_text("this is not a profile\n", encoding="utf-8")
            with self.assertRaises(ProfileTransferError):
                import_profile_file(bad, library)
            self.assertEqual(keep.read_bytes(), before)
            self.assertEqual([p.name for p in library.iterdir()], ["keep.txt"])


if __name__ == "__main__":
    unittest.main()
