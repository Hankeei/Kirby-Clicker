"""Click profile model and the ClickProfile v1 text format.

Format (v1):

    # ClickProfile v1 (Kirby Clicker)
    # Each data line: <hold_ms> <gap_ms>
    # hold_ms = how long the button stays down, gap_ms = wait until the next press
    button=left
    clicks=10288
    avg_cps=19.05
    min_interval_ms=22
    max_interval_ms=200
    # data
    11 36
    18 29
    ...
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

HEADER_1 = "# ClickProfile v1 (Kirby Clicker)"
# Older GMK Clicker files keep the same v1 header prefix; the loader accepts
# any "# ClickProfile v1 ..." line so existing recordings still open.
HEADER_2 = "# Each data line: <hold_ms> <gap_ms>"
HEADER_3 = "# hold_ms = how long the button stays down, gap_ms = wait until the next press"

VALID_BUTTONS = ("left", "right", "middle")


class ProfileFormatError(ValueError):
    pass


@dataclass
class Click:
    hold_ms: int
    gap_ms: int
    button: str = "left"


@dataclass(frozen=True)
class ProfileStats:
    clicks: int = 0
    avg_cps: float = 0.0
    min_interval_ms: int = 0
    max_interval_ms: int = 0

    @property
    def range_text(self) -> str:
        return f"{self.min_interval_ms}-{self.max_interval_ms} ms"


def compute_stats(clicks: Iterable[Click]) -> ProfileStats:
    items = list(clicks)
    if not items:
        return ProfileStats()
    intervals = [max(0, c.hold_ms + c.gap_ms) for c in items]
    total = sum(intervals)
    avg_cps = (1000.0 * len(items) / total) if total > 0 else 0.0
    return ProfileStats(
        clicks=len(items),
        avg_cps=round(avg_cps, 2),
        min_interval_ms=min(intervals),
        max_interval_ms=max(intervals),
    )


@dataclass
class ClickProfile:
    clicks: list[Click] = field(default_factory=list)
    button: str = "left"
    path: Path | None = None
    name: str = "unsaved"
    meta: dict[str, str] = field(default_factory=dict)

    @property
    def stats(self) -> ProfileStats:
        return compute_stats(self.clicks)

    @property
    def display_name(self) -> str:
        return self.path.name if self.path else self.name

    @property
    def target_cps(self) -> float:
        return self.stats.avg_cps

    def is_empty(self) -> bool:
        return not self.clicks


def _normalise_button(value: str) -> str:
    value = (value or "left").strip().lower()
    return value if value in VALID_BUTTONS else "left"


def load_profile(path: str | Path) -> ClickProfile:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise ProfileFormatError(f"Could not read {path}: {exc}") from exc

    meta: dict[str, str] = {}
    numbers: list[tuple[int, int]] = []
    in_data = False
    saw_data_marker = False

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if in_data:
            if line.startswith("#"):
                continue
            parts = line.replace(",", " ").split()
            if len(parts) < 2:
                raise ProfileFormatError(f"Line {lineno}: expected '<hold_ms> <gap_ms>'")
            try:
                hold = int(parts[0])
                gap = int(parts[1])
            except ValueError as exc:
                raise ProfileFormatError(f"Line {lineno}: non-numeric data '{line}'") from exc
            numbers.append((max(0, hold), max(0, gap)))
            continue
        if line.startswith("#"):
            if line.lower().startswith("# data"):
                in_data = True
                saw_data_marker = True
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            key = key.strip().lower()
            value = value.strip()
            if key == "data":
                in_data = True
                saw_data_marker = True
            else:
                meta[key] = value

    # A file without the "# data" marker: accept trailing numeric lines if any.
    if not saw_data_marker:
        for lineno, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#") or "=" in line:
                continue
            parts = line.replace(",", " ").split()
            if len(parts) >= 2:
                try:
                    hold, gap = int(parts[0]), int(parts[1])
                except ValueError:
                    continue
                numbers.append((max(0, hold), max(0, gap)))

    if not numbers:
        raise ProfileFormatError("Profile contains no click data")

    button = _normalise_button(meta.get("button", "left"))
    clicks = [Click(hold, gap, button) for hold, gap in numbers]
    header_count = meta.get("clicks", "")
    if header_count:
        try:
            declared = int(header_count)
        except ValueError:
            declared = -1
        if declared != len(clicks):
            meta["clicks_mismatch"] = f"header={header_count} data={len(clicks)}"

    return ClickProfile(clicks=clicks, button=button, path=path, name=path.stem, meta=meta)


def save_profile(path: str | Path, profile: ClickProfile) -> ClickProfile:
    path = Path(path)
    clicks = profile.clicks
    if not clicks:
        raise ProfileFormatError("Cannot save an empty profile")
    stats = compute_stats(clicks)
    button = _normalise_button(profile.button)
    if any(c.button and c.button != button for c in clicks):
        raise ProfileFormatError("v1 profiles can only store one button type (set button= in the header)")

    lines = [
        HEADER_1,
        HEADER_2,
        HEADER_3,
        f"button={button}",
        f"clicks={stats.clicks}",
        f"avg_cps={stats.avg_cps:.2f}",
        f"min_interval_ms={stats.min_interval_ms}",
        f"max_interval_ms={stats.max_interval_ms}",
        "# data",
    ]
    lines.extend(f"{max(0, int(c.hold_ms))} {max(0, int(c.gap_ms))}" for c in clicks)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return ClickProfile(
        clicks=clicks,
        button=button,
        path=path,
        name=path.stem,
        meta={"clicks": str(stats.clicks), "avg_cps": f"{stats.avg_cps:.2f}"},
    )


def save_profile_values(path: str | Path, values: Iterable[tuple[int, int]], button: str = "left") -> ClickProfile:
    profile = ClickProfile(
        clicks=[Click(int(h), int(g), button) for h, g in values],
        button=button,
    )
    return save_profile(path, profile)


def generate_profile(count: int = 10288, seed: int = 20261105, button: str = "left") -> ClickProfile:
    """Deterministic synthetic profile that has human-looking hold/gap values.

    Intervals are drawn from a clipped normal distribution around 52.5 ms
    (~19 CPS), split into a hold and a gap and written in the v1 file format.
    """
    rng = random.Random(seed)
    clicks: list[Click] = []
    for _ in range(max(1, int(count))):
        interval = int(round(rng.gauss(52.5, 18.0)))
        interval = max(22, min(200, interval))
        hold = max(5, int(round(interval * rng.uniform(0.22, 0.48))))
        hold = min(hold, interval - 1) if interval > 1 else 1
        gap = max(0, interval - hold)
        clicks.append(Click(hold, gap, _normalise_button(button)))
    return ClickProfile(clicks=clicks, button=_normalise_button(button), name="synthetic")


def next_recording_path(folder: str | Path) -> Path:
    """Lowest unused ``recN.txt`` in ``folder`` (rec1, rec2, rec3, ...).

    Existing files with any other name are ignored and never rewritten.
    """
    folder = Path(folder)
    index = 1
    while True:
        candidate = folder / f"rec{index}.txt"
        if not candidate.exists():
            return candidate
        index += 1


_INVALID_NAME_CHARS = '<>:"/\\|?*'


def profile_name_problem(name: str) -> str | None:
    """Return a user-facing problem for a profile name, or ``None`` if valid."""
    raw = (name or "").strip()
    if not raw:
        return "Profile name cannot be empty."
    if raw in (".", ".."):
        return "That profile name is not allowed."
    if any(ch in _INVALID_NAME_CHARS or ord(ch) < 32 for ch in raw):
        return 'Profile names cannot contain <>:"/\\|?* or control characters.'
    if raw.endswith(".") or raw.endswith(" "):
        return "Profile names cannot end with a dot or space."
    stem = raw[:-4] if raw.lower().endswith(".txt") else raw
    if not stem.strip():
        return "Profile name cannot be empty."
    return None


def rename_profile_file(path: str | Path, new_name: str) -> Path:
    """Rename ``path`` to ``new_name`` (``.txt`` implied) inside its folder.

    Raises :class:`ProfileFormatError` for an invalid or already-used name.
    """
    path = Path(path)
    problem = profile_name_problem(new_name)
    if problem:
        raise ProfileFormatError(problem)
    stem = (new_name or "").strip()
    if stem.lower().endswith(".txt"):
        stem = stem[:-4]
    target = path.with_name(f"{stem}.txt")
    if target == path:
        return path
    # A case-only change points at the same file on Windows; anything else
    # that exists is a real conflict and must never be overwritten.
    if target.name.casefold() != path.name.casefold() and target.exists():
        raise ProfileFormatError(f"{target.name} already exists.")
    try:
        path.rename(target)
    except OSError as exc:
        raise ProfileFormatError(f"Could not rename {path.name}: {exc}") from exc
    return target


def median_gap(clicks: list[Click]) -> int:
    gaps = sorted(c.gap_ms for c in clicks)
    if not gaps:
        return 0
    return int(gaps[len(gaps) // 2])
