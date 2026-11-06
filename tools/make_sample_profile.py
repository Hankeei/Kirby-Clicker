"""Generate the synthetic 10288-click profile used by the demo/screenshot."""

from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from app.core.profile import generate_profile, save_profile  # noqa: E402


def main() -> int:
    profile = generate_profile(10288, seed=20261105)
    out = BASE / "profiles" / "click_profile.txt"
    saved = save_profile(out, profile)
    stats = saved.stats
    print(f"wrote {out}")
    print(f"clicks={stats.clicks} avg_cps={stats.avg_cps:.2f} "
          f"min={stats.min_interval_ms} max={stats.max_interval_ms}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
