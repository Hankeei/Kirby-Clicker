"""Versioned profile import/export (Kirby Clicker exchange format v2).

Exchange files are UTF-8 JSON with this shape::

    {
      "format": "record-clicker-profile",
      "version": 2,
      "created_by": "Kirby Clicker 1.0.0",
      "created_at": "2026-11-05T12:00:00Z",
      "profile": {
        "name": "my rhythm",
        "button": "left",
        "clicks": [[12, 36], [15, 41], ...]
      },
      "stats": {
        "clicks": 2,
        "avg_cps": 20.2,
        "min_interval_ms": 48,
        "max_interval_ms": 56
      },
      "checksum": "sha256:<hex>"
    }

The checksum covers the canonical JSON of every field except ``checksum``.
It detects corruption and accidental edits; it is not a signature and does not
protect against someone deliberately rebuilding the file.

Import accepts:
  * exchange v2 JSON (preferred)
  * legacy ClickProfile v1 text, validated strictly before it is written
    into the local library

Conflict policy: imported files are never overwritten.  A name clash becomes
``name (imported).txt``, then ``name (imported 2).txt``, and so on.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .profile import (
    VALID_BUTTONS,
    Click,
    ClickProfile,
    ProfileFormatError,
    compute_stats,
    load_profile,
    save_profile,
)

FORMAT_ID = "record-clicker-profile"
FORMAT_VERSION = 2
FILE_SUFFIX = ".rcprofile.json"
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_CLICKS = 250_000
MAX_HOLD_MS = 60_000
MAX_GAP_MS = 3_600_000
CHECKSUM_PREFIX = "sha256:"

_ALLOWED_TOP = {
    "format",
    "version",
    "created_by",
    "created_at",
    "profile",
    "stats",
    "checksum",
}
_ALLOWED_PROFILE = {"name", "button", "clicks"}
_ALLOWED_STATS = {"clicks", "avg_cps", "min_interval_ms", "max_interval_ms"}
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class ProfileTransferError(ProfileFormatError):
    """A file could not be imported/exported safely."""


@dataclass
class ImportOutcome:
    profile: ClickProfile
    path: Path
    source: Path
    format_label: str
    renamed_from: str | None = None


# --------------------------------------------------------------------- helpers
def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _checksum(payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(_canonical(payload)).hexdigest()
    return f"{CHECKSUM_PREFIX}{digest}"


def _valid_interval(hold: Any, gap: Any, index: int) -> tuple[int, int]:
    if isinstance(hold, bool) or isinstance(gap, bool):
        raise ProfileTransferError(f"Click {index + 1}: hold/gap must be integers")
    if not isinstance(hold, int) or not isinstance(gap, int):
        raise ProfileTransferError(f"Click {index + 1}: hold/gap must be integers")
    if hold < 0 or hold > MAX_HOLD_MS:
        raise ProfileTransferError(
            f"Click {index + 1}: hold_ms={hold} outside 0..{MAX_HOLD_MS}"
        )
    if gap < 0 or gap > MAX_GAP_MS:
        raise ProfileTransferError(
            f"Click {index + 1}: gap_ms={gap} outside 0..{MAX_GAP_MS}"
        )
    return hold, gap


def _valid_button(value: Any) -> str:
    if not isinstance(value, str) or value.strip().lower() not in VALID_BUTTONS:
        raise ProfileTransferError(
            f"Unsupported button {value!r}; expected left, right or middle"
        )
    return value.strip().lower()


def sanitise_name(name: str) -> str:
    name = re.sub(r"[\x00-\x1f]", " ", str(name or ""))
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    name = name[:80].strip(" .")
    if not name:
        name = "imported-profile"
    if name.upper() in _RESERVED_NAMES:
        name = f"{name}-profile"
    return name


def _source_stem(path: Path) -> str:
    name = path.name
    if name.lower().endswith(FILE_SUFFIX):
        name = name[: -len(FILE_SUFFIX)]
    else:
        name = path.stem
    return sanitise_name(name)


def unique_profile_path(directory: Path, base: str, suffix: str = ".txt") -> Path:
    """Never overwrite: name.txt, name (imported).txt, name (imported 2).txt ..."""
    base = sanitise_name(base)
    candidate = directory / f"{base}{suffix}"
    if not candidate.exists():
        return candidate
    candidate = directory / f"{base} (imported){suffix}"
    if not candidate.exists():
        return candidate
    for counter in range(2, 10_000):
        candidate = directory / f"{base} (imported {counter}){suffix}"
        if not candidate.exists():
            return candidate
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return directory / f"{base} (imported {stamp}){suffix}"


# ---------------------------------------------------------------------- export
def export_profile(
    path: str | Path,
    profile: ClickProfile,
    name: str | None = None,
    created_at: str | None = None,
) -> Path:
    path = Path(path)
    clicks = profile.clicks
    if not clicks:
        raise ProfileTransferError("Cannot export an empty profile")
    if len(clicks) > MAX_CLICKS:
        raise ProfileTransferError(
            f"Profile has {len(clicks)} clicks; the exchange format limit is {MAX_CLICKS}"
        )
    button = _valid_button(profile.button)
    for index, click in enumerate(clicks):
        _valid_interval(click.hold_ms, click.gap_ms, index)
        if click.button and click.button != button:
            raise ProfileTransferError(
                "Exchange v2 stores one button per profile; mixed buttons are not supported"
            )

    display_name = sanitise_name(name or profile.display_name or "profile")
    stats = compute_stats(clicks)
    payload: dict[str, Any] = {
        "format": FORMAT_ID,
        "version": FORMAT_VERSION,
        "created_by": "Kirby Clicker",
        "created_at": created_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile": {
            "name": display_name,
            "button": button,
            "clicks": [[int(c.hold_ms), int(c.gap_ms)] for c in clicks],
        },
        "stats": {
            "clicks": stats.clicks,
            "avg_cps": stats.avg_cps,
            "min_interval_ms": stats.min_interval_ms,
            "max_interval_ms": stats.max_interval_ms,
        },
    }
    payload["checksum"] = _checksum(payload)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    return path


# ---------------------------------------------------------------------- import
def _parse_exchange(raw: Any, source: Path) -> tuple[ClickProfile, str, str | None]:
    if not isinstance(raw, dict):
        raise ProfileTransferError("Malformed exchange file: top level must be a JSON object")
    unknown = set(raw) - _ALLOWED_TOP
    if unknown:
        raise ProfileTransferError(
            f"Malformed exchange file: unexpected field(s) {', '.join(sorted(unknown))}"
        )
    if raw.get("format") != FORMAT_ID:
        raise ProfileTransferError(
            "Not a Kirby Clicker exchange file (missing format='record-clicker-profile')"
        )
    version = raw.get("version")
    if version != FORMAT_VERSION:
        raise ProfileTransferError(
            f"Unsupported profile version {version!r}; this app reads version "
            f"{FORMAT_VERSION} exchange files and legacy v1 text"
        )

    checksum = raw.get("checksum")
    if not isinstance(checksum, str) or not checksum.startswith(CHECKSUM_PREFIX):
        raise ProfileTransferError("Malformed exchange file: missing sha256 checksum")
    body = {key: value for key, value in raw.items() if key != "checksum"}
    expected = _checksum(body)
    if not hmac.compare_digest(checksum.lower(), expected):
        raise ProfileTransferError(
            "Checksum mismatch — the file was modified after export or is corrupted"
        )

    if not isinstance(raw.get("created_by", ""), str) or not isinstance(raw.get("created_at", ""), str):
        raise ProfileTransferError("Malformed exchange file: created_by/created_at must be strings")

    profile_raw = raw.get("profile")
    if not isinstance(profile_raw, dict):
        raise ProfileTransferError("Malformed exchange file: missing profile object")
    unknown = set(profile_raw) - _ALLOWED_PROFILE
    if unknown:
        raise ProfileTransferError(
            f"Malformed exchange file: unexpected profile field(s) {', '.join(sorted(unknown))}"
        )
    name_raw = profile_raw.get("name")
    if not isinstance(name_raw, str):
        raise ProfileTransferError("Malformed exchange file: profile.name must be a string")
    button = _valid_button(profile_raw.get("button"))

    clicks_raw = profile_raw.get("clicks")
    if not isinstance(clicks_raw, list) or not clicks_raw:
        raise ProfileTransferError("Malformed exchange file: profile.clicks must be a non-empty array")
    if len(clicks_raw) > MAX_CLICKS:
        raise ProfileTransferError(
            f"Exchange file has {len(clicks_raw)} clicks; the safety limit is {MAX_CLICKS}"
        )
    clicks: list[Click] = []
    for index, item in enumerate(clicks_raw):
        if not isinstance(item, list) or len(item) != 2:
            raise ProfileTransferError(
                f"Click {index + 1}: expected a [hold_ms, gap_ms] pair"
            )
        hold, gap = _valid_interval(item[0], item[1], index)
        clicks.append(Click(hold, gap, button))

    stats_raw = raw.get("stats")
    if not isinstance(stats_raw, dict):
        raise ProfileTransferError("Malformed exchange file: missing stats object")
    unknown = set(stats_raw) - _ALLOWED_STATS
    if unknown:
        raise ProfileTransferError(
            f"Malformed exchange file: unexpected stats field(s) {', '.join(sorted(unknown))}"
        )
    stats = compute_stats(clicks)
    try:
        declared_avg = float(stats_raw.get("avg_cps"))
    except (TypeError, ValueError) as exc:
        raise ProfileTransferError("Malformed exchange file: stats.avg_cps must be a number") from exc
    if (
        stats_raw.get("clicks") != stats.clicks
        or stats_raw.get("min_interval_ms") != stats.min_interval_ms
        or stats_raw.get("max_interval_ms") != stats.max_interval_ms
        or abs(declared_avg - stats.avg_cps) > 0.005
    ):
        raise ProfileTransferError(
            "Stats do not match the click data — the file is inconsistent or tampered"
        )

    profile = ClickProfile(
        clicks=clicks,
        button=button,
        name=sanitise_name(name_raw),
        meta={"source_format": f"exchange-v{FORMAT_VERSION}"},
    )
    return profile, f"exchange v{FORMAT_VERSION}", name_raw


def _strict_legacy_values(source: Path) -> tuple[ClickProfile, str]:
    try:
        text = source.read_text(encoding="utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise ProfileTransferError("Legacy profile is not valid UTF-8 text") from exc
    except OSError as exc:
        raise ProfileTransferError(f"Could not read {source.name}: {exc}") from exc

    lines = text.splitlines()
    header = next((line.strip() for line in lines if line.strip()), "")
    has_header = header.lower().startswith("# clickprofile v1")
    has_data_marker = any(line.strip().lower().startswith("# data") for line in lines)
    has_meta = any(line.strip().lower().startswith(("clicks=", "button=")) for line in lines)
    if not (has_header or (has_data_marker and has_meta)):
        raise ProfileTransferError(
            "Not a Kirby Clicker profile: expected a '# ClickProfile v1' header "
            "or a '# data' section"
        )

    try:
        profile = load_profile(source)
    except ProfileFormatError as exc:
        raise ProfileTransferError(f"Malformed legacy profile: {exc}") from exc
    if not profile.clicks:
        raise ProfileTransferError("Legacy profile contains no click data")
    if len(profile.clicks) > MAX_CLICKS:
        raise ProfileTransferError(
            f"Legacy profile has {len(profile.clicks)} clicks; the safety limit is {MAX_CLICKS}"
        )

    raw_button = profile.meta.get("button")
    if raw_button is not None and raw_button.strip().lower() not in VALID_BUTTONS:
        raise ProfileTransferError(
            f"Legacy profile has unsupported button {raw_button!r}"
        )
    declared = profile.meta.get("clicks")
    if declared:
        try:
            declared_int = int(declared)
        except ValueError as exc:
            raise ProfileTransferError(
                f"Legacy profile has a non-numeric clicks header {declared!r}"
            ) from exc
        if declared_int != len(profile.clicks):
            raise ProfileTransferError(
                f"Legacy profile declares {declared_int} clicks but contains "
                f"{len(profile.clicks)} data lines — truncated, edited or tampered"
            )

    # Re-scan the data section and reject anything the lenient v1 loader repaired.
    in_data = not has_data_marker
    seen = 0
    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        if line.lower().startswith("# data"):
            in_data = True
            continue
        if line.startswith("#") or "=" in line:
            continue
        if not in_data:
            continue
        parts = line.split()
        if len(parts) != 2:
            raise ProfileTransferError(
                f"Line {lineno}: expected exactly '<hold_ms> <gap_ms>'"
            )
        try:
            hold = int(parts[0])
            gap = int(parts[1])
        except ValueError as exc:
            raise ProfileTransferError(f"Line {lineno}: non-numeric click data") from exc
        _valid_interval(hold, gap, seen)
        seen += 1
    if seen != len(profile.clicks):
        raise ProfileTransferError(
            "Legacy profile data does not match the parsed click count — refusing to import"
        )

    profile.meta["source_format"] = "legacy-v1-text"
    return profile, "legacy v1 text"


def import_profile_file(
    source: str | Path,
    profiles_dir: str | Path,
    name_override: str | None = None,
) -> ImportOutcome:
    source = Path(source)
    if not source.is_file():
        raise ProfileTransferError(f"Import file does not exist: {source}")
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise ProfileTransferError(f"Could not inspect {source.name}: {exc}") from exc
    if size > MAX_FILE_BYTES:
        raise ProfileTransferError(
            f"File is {size / (1024 * 1024):.1f} MB; the import limit is "
            f"{MAX_FILE_BYTES // (1024 * 1024)} MB"
        )

    try:
        text = source.read_text(encoding="utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise ProfileTransferError("Profile is not valid UTF-8 text") from exc
    except OSError as exc:
        raise ProfileTransferError(f"Could not read {source.name}: {exc}") from exc

    if text.lstrip().startswith("{"):
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProfileTransferError(
                f"Malformed JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
            ) from exc
        profile, label, declared_name = _parse_exchange(raw, source)
        base_name = name_override or declared_name or _source_stem(source)
    else:
        profile, label = _strict_legacy_values(source)
        base_name = name_override or _source_stem(source)

    base_name = sanitise_name(base_name)
    profiles_dir = Path(profiles_dir)
    profiles_dir.mkdir(parents=True, exist_ok=True)
    target = unique_profile_path(profiles_dir, base_name, ".txt")
    renamed_from = base_name if target.stem != base_name else None
    tmp = target.with_name(target.name + ".tmp")
    try:
        save_profile(tmp, profile)
        os.replace(tmp, target)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass

    profile.path = target
    profile.name = target.stem
    return ImportOutcome(
        profile=profile,
        path=target,
        source=source,
        format_label=label,
        renamed_from=renamed_from,
    )
