"""Check native exchange output using the original Python importer."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from app.core.transfer import import_profile_file


def main() -> int:
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "dist/KirbyClicker.exe"
    with tempfile.TemporaryDirectory(prefix="native-compat-", dir=BASE / "build") as temp:
        folder = Path(temp)
        output = folder / "selftest.json"
        env = os.environ.copy()
        env["KIRBYCLICKER_DATA"] = str(folder / "data")
        env["KIRBYCLICKER_SELFTEST_OUT"] = str(output)
        subprocess.run([str(exe), "--selftest"], env=env, check=True, timeout=20)
        report = json.loads(output.read_text(encoding="utf-8"))
        source = folder / "native.rcprofile.json"
        source.write_text(json.dumps(report["exchange_fixture"], ensure_ascii=False), encoding="utf-8")
        outcome = import_profile_file(source, folder / "profiles")
        assert outcome.profile.button == "right"
        assert [(c.hold_ms, c.gap_ms) for c in outcome.profile.clicks] == [(12, 36), (18, 29)]
        print("Rust -> Python exchange checksum, Unicode name and click data: PASS")
        print(f"Native dry-run max drift: {report['max_drift_ms']:.2f} ms; max hold error: {report['max_hold_error_ms']:.2f} ms")
        print(f"Native audio: {report['music_status']} at {report['music_position_ms']} ms; toggle sounds: {report['toggle_sounds']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
