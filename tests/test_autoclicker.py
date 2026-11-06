"""Random-CPS sampler and auto-clicker session tests."""

from __future__ import annotations

import math
import random
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from app.core.autoclicker import (  # noqa: E402
    MAX_CPS,
    MIN_CPS,
    MAX_HOLD_MS,
    MIN_HOLD_MS,
    METHOD_BLATANT,
    METHOD_GAUSSIAN,
    METHOD_GAUSSIAN_POISSON,
    METHOD_LABELS,
    METHOD_POISSON,
    METHOD_SHORT_LABELS,
    METHOD_STATIC,
    METHODS,
    AutoClickerSession,
    clamp_sigma,
    gap_bounds_ms,
    normalise_method,
    sample_gap_ms,
    sample_hold_ms,
    sync_bounds,
    validate_cps,
)
from app.core.backends import ClickBackend, ClickResult  # noqa: E402
from app.core.windows import Target  # noqa: E402


class ValidateCpsTest(unittest.TestCase):
    def test_accepts_ordered_bounds(self) -> None:
        self.assertEqual(validate_cps(4, 12), (4.0, 12.0))

    def test_rejects_inverted_bounds(self) -> None:
        with self.assertRaisesRegex(ValueError, "less than or equal"):
            validate_cps(12, 4)

    def test_rejects_non_numeric_and_non_positive(self) -> None:
        for low, high in (("abc", 4), (4, None), (0, 5), (-3, 8)):
            with self.assertRaises(ValueError):
                validate_cps(low, high)

    def test_clamps_to_sane_range(self) -> None:
        self.assertEqual(validate_cps(0.2, 75), (MIN_CPS, MAX_CPS))
        self.assertEqual(validate_cps(3, 99), (3.0, MAX_CPS))


class GapSamplingTest(unittest.TestCase):
    def test_gaps_stay_within_bounds_and_span_the_range(self) -> None:
        rng = random.Random(1234)
        gaps = [sample_gap_ms(5.0, 20.0, rng) for _ in range(2000)]
        short, long = 1000.0 / 20.0, 1000.0 / 5.0
        self.assertTrue(all(short <= gap <= long for gap in gaps))
        self.assertLess(min(gaps), short + (long - short) * 0.10)
        self.assertGreater(max(gaps), long - (long - short) * 0.10)
        mean = sum(gaps) / len(gaps)
        self.assertLess(abs(mean - (short + long) / 2.0), (long - short) * 0.10)
        self.assertGreater(len(set(gaps)), 1500, "sampling is not random enough")

    def test_tight_bounds_stay_tight(self) -> None:
        rng = random.Random(7)
        gaps = [sample_gap_ms(10.0, 10.0, rng) for _ in range(50)]
        self.assertTrue(all(abs(gap - 100.0) < 1e-9 for gap in gaps))

    def test_hold_time_is_plausible_and_varied(self) -> None:
        rng = random.Random(99)
        holds = [sample_hold_ms(gap, rng) for gap in (40.0, 70.0, 120.0, 300.0, 1000.0)]
        for gap, hold in zip((40.0, 70.0, 120.0, 300.0, 1000.0), holds):
            self.assertGreaterEqual(hold, min(MIN_HOLD_MS, gap * 0.9))
            self.assertLessEqual(hold, MAX_HOLD_MS)
        many = [sample_hold_ms(120.0, rng) for _ in range(200)]
        self.assertGreater(len(set(round(h, 1) for h in many)), 40, "hold time is fixed")


def _simpson(values: list[float], step: float) -> float:
    total = values[0] + values[-1]
    for index, value in enumerate(values[1:-1], start=1):
        total += value * (4 if index % 2 else 2)
    return total * step / 3.0


def _expected_mean_cps_exponential(lam_per_ms: float, short: float, long: float,
                                   steps: int = 900) -> float:
    """E[1000/X] for an exponential gap clamped to [short, long]."""
    step = (long - short) / steps
    xs = [short + i * step for i in range(steps + 1)]
    integral = _simpson([math.exp(-lam_per_ms * x) / x for x in xs], step)
    p_low = 1.0 - math.exp(-lam_per_ms * short)
    p_high = math.exp(-lam_per_ms * long)
    return 1000.0 * (lam_per_ms * integral + p_low / short + p_high / long)


def _expected_mean_cps_compound(mid_cps: float, sigma: float, short: float,
                                long: float, steps: int = 160) -> float:
    """E[1000/X] for rate ~ Normal(mid, sigma*mid), gap ~ Exp(rate), clamped."""
    sigma_cps = sigma * mid_cps
    low_rate = max(0.5, mid_cps - 5.0 * sigma_cps)
    high_rate = mid_cps + 5.0 * sigma_cps
    step = (high_rate - low_rate) / steps
    weight_sum = 0.0
    expected = 0.0
    for i in range(steps + 1):
        rate = low_rate + i * step
        weight = math.exp(-0.5 * ((rate - mid_cps) / sigma_cps) ** 2)
        if i in (0, steps):
            weight *= 0.5
        weight_sum += weight
        expected += weight * _expected_mean_cps_exponential(
            rate / 1000.0, short, long, steps=420
        )
    return expected / weight_sum


class TimingMethodsTest(unittest.TestCase):
    """10k+ samples per mode: bounds, mean and spread."""

    LOW, HIGH = 1.0, 30.0

    def _samples(self, method: str, count: int = 10_000, sigma: float = 0.15) -> list[float]:
        rng = random.Random(2026)
        return [
            sample_gap_ms(self.LOW, self.HIGH, rng, method, sigma)
            for _ in range(count)
        ]

    def test_every_mode_stays_inside_the_bounds(self) -> None:
        short, long = gap_bounds_ms(self.LOW, self.HIGH)
        for method in METHODS:
            gaps = self._samples(method, 10_000)
            for gap in gaps:
                self.assertGreaterEqual(gap, short, method)
                self.assertLessEqual(gap, long, method)
            if method == METHOD_STATIC:
                # A static mode is deliberately one identical gap; it is not
                # expected to produce 900 distinct values.
                self.assertEqual(len(set(round(g, 3) for g in gaps)), 1, method)
            else:
                self.assertGreater(len(set(round(g, 3) for g in gaps)), 900, method)

    def test_blatant_mean_cps_matches_uniform_gap_formula(self) -> None:
        gaps = self._samples(METHOD_BLATANT, 20_000)
        short, long = gap_bounds_ms(self.LOW, self.HIGH)
        expected = 1000.0 * math.log(long / short) / (long - short)
        measured = sum(1000.0 / gap for gap in gaps) / len(gaps)
        self.assertLess(abs(measured - expected) / expected, 0.03, (measured, expected))

    def test_gaussian_mean_cps_near_midpoint(self) -> None:
        gaps = self._samples(METHOD_GAUSSIAN, 20_000)
        measured = sum(1000.0 / gap for gap in gaps) / len(gaps)
        midpoint = (self.LOW + self.HIGH) / 2.0
        self.assertLess(abs(measured - midpoint) / midpoint, 0.05)

    def test_poisson_mean_cps_matches_truncated_exponential_expectation(self) -> None:
        gaps = self._samples(METHOD_POISSON, 20_000)
        measured = sum(1000.0 / gap for gap in gaps) / len(gaps)
        midpoint = (self.LOW + self.HIGH) / 2.0
        short, long = gap_bounds_ms(self.LOW, self.HIGH)
        expected = _expected_mean_cps_exponential(midpoint / 1000.0, short, long)
        self.assertLess(abs(measured - expected) / expected, 0.03, (measured, expected))
        self.assertGreaterEqual(measured, self.LOW)
        self.assertLessEqual(measured, self.HIGH)
        # The exponential tail plus the short-gap clamp skews mean CPS above
        # the arithmetic midpoint; this is a property of the mode, not a bug.
        self.assertGreater(measured, midpoint)

    def test_gaussian_poisson_mean_cps_matches_compound_expectation(self) -> None:
        gaps = self._samples(METHOD_GAUSSIAN_POISSON, 20_000)
        measured = sum(1000.0 / gap for gap in gaps) / len(gaps)
        midpoint = (self.LOW + self.HIGH) / 2.0
        short, long = gap_bounds_ms(self.LOW, self.HIGH)
        expected = _expected_mean_cps_compound(
            midpoint, 0.15, short, long
        )
        self.assertLess(abs(measured - expected) / expected, 0.04, (measured, expected))
        self.assertGreaterEqual(measured, self.LOW)
        self.assertLessEqual(measured, self.HIGH)

    def test_static_mode_is_one_exact_gap_and_cps(self) -> None:
        short, long = gap_bounds_ms(self.LOW, self.HIGH)
        gaps = self._samples(METHOD_STATIC, 10_000)
        expected_gap = 1000.0 / ((self.LOW + self.HIGH) / 2.0)
        self.assertTrue(all(abs(gap - expected_gap) < 1e-9 for gap in gaps))
        self.assertEqual(min(gaps), max(gaps))
        measured = sum(1000.0 / gap for gap in gaps) / len(gaps)
        self.assertAlmostEqual(measured, (self.LOW + self.HIGH) / 2.0, places=9)
        self.assertGreaterEqual(expected_gap, short)
        self.assertLessEqual(expected_gap, long)

    def test_static_mode_hold_time_still_varies(self) -> None:
        rng = random.Random(31)
        holds = [sample_hold_ms(1000.0 / 12.0, rng) for _ in range(200)]
        self.assertGreater(len(set(round(h, 2) for h in holds)), 40)

    def test_variance_ordering_for_wide_bounds(self) -> None:
        def variance(values: list[float]) -> float:
            mean = sum(values) / len(values)
            return sum((v - mean) ** 2 for v in values) / len(values)

        gaps = {method: self._samples(method, 20_000) for method in METHODS}
        blatant = variance(gaps[METHOD_BLATANT])
        poisson = variance(gaps[METHOD_POISSON])
        gaussian = variance(gaps[METHOD_GAUSSIAN])
        compound = variance(gaps[METHOD_GAUSSIAN_POISSON])
        self.assertGreater(blatant, poisson * 3.0, (blatant, poisson))
        self.assertGreater(poisson, gaussian * 3.0, (poisson, gaussian))
        self.assertGreater(compound, gaussian, (compound, gaussian))

    def test_sigma_widens_gaussian_mode(self) -> None:
        def sd(sigma: float) -> float:
            gaps = self._samples(METHOD_GAUSSIAN, 10_000, sigma)
            mean = sum(gaps) / len(gaps)
            return (sum((g - mean) ** 2 for g in gaps) / len(gaps)) ** 0.5

        self.assertGreater(sd(0.30), sd(0.08) * 2.5)

    def test_method_and_sigma_normalisation(self) -> None:
        self.assertEqual(normalise_method("poisson"), METHOD_POISSON)
        self.assertEqual(normalise_method("static"), METHOD_STATIC)
        self.assertEqual(normalise_method("nonsense"), METHOD_BLATANT)
        self.assertEqual(normalise_method(None), METHOD_BLATANT)
        self.assertEqual(clamp_sigma(0.01), 0.05)
        self.assertEqual(clamp_sigma(0.99), 0.40)
        self.assertEqual(clamp_sigma("bad"), 0.15)
        self.assertIn(METHOD_GAUSSIAN_POISSON, METHOD_LABELS)

    def test_display_labels_keep_the_stable_ids(self) -> None:
        # The stored identifiers stay ``blatant`` / ``static`` so old
        # settings.json files keep loading; only the visible text changes.
        self.assertEqual(METHOD_LABELS[METHOD_BLATANT], "Random")
        self.assertEqual(METHOD_LABELS[METHOD_STATIC], "Static ⚠")
        self.assertEqual(METHOD_SHORT_LABELS[METHOD_BLATANT], "RANDOM")
        self.assertEqual(METHOD_SHORT_LABELS[METHOD_STATIC], "STATIC ⚠")
        self.assertEqual(normalise_method("blatant"), METHOD_BLATANT)
        self.assertEqual(normalise_method("static"), METHOD_STATIC)

    def test_gap_bounds_helper_matches_cps_bounds(self) -> None:
        self.assertEqual(gap_bounds_ms(10, 10), (100.0, 100.0))
        short, long = gap_bounds_ms(2, 50)
        self.assertAlmostEqual(short, 20.0)
        self.assertAlmostEqual(long, 500.0)


class BoundsSyncTest(unittest.TestCase):
    """Mirrors the slider/spin-box interaction: low <= high always holds."""

    def test_low_past_high_pushes_high(self) -> None:
        self.assertEqual(sync_bounds(18, 14, changed="low"), (18.0, 18.0))

    def test_high_below_low_pushes_low(self) -> None:
        self.assertEqual(sync_bounds(18, 14, changed="high"), (14.0, 14.0))

    def test_valid_pair_is_untouched(self) -> None:
        self.assertEqual(sync_bounds(8, 14, changed="low"), (8.0, 14.0))
        self.assertEqual(sync_bounds(8, 14, changed="high"), (8.0, 14.0))

    def test_typed_wider_values_are_preserved(self) -> None:
        self.assertEqual(sync_bounds(45, 50, changed="low"), (45.0, 50.0))

    def test_equal_bounds_allowed(self) -> None:
        self.assertEqual(sync_bounds(12, 12, changed="low"), (12.0, 12.0))


class FakeBackend(ClickBackend):
    name = "fake"

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def press(self, button: str, target, own_pid: int) -> ClickResult:
        self.events.append(("press", button))
        return ClickResult(True)

    def release(self, button: str) -> ClickResult:
        self.events.append(("release", button))
        return ClickResult(True)


class SessionTest(unittest.TestCase):
    def test_runs_alternating_presses_and_stops_cleanly(self) -> None:
        backend = FakeBackend()
        session = AutoClickerSession(
            20.0,
            30.0,
            "left",
            Target.any_target(),
            backend,
            1,
            seed=5,
        )
        session.start()
        while sum(1 for kind, _ in backend.events if kind == "press") < 5:
            pass
        session.stop()
        session.wait(3000)
        self.assertFalse(session.snapshot()["held"], "button left logically down")
        self.assertEqual(backend.events[-1][0], "release")
        snap = session.snapshot()
        self.assertGreaterEqual(snap["sent"], 5)
        recent = snap["recent"]
        self.assertTrue(all(33.0 <= gap <= 51.0 for gap in recent), recent)
        summary = session.summary()
        self.assertGreater(summary["avg_cps"], 0)
        self.assertFalse(summary["skipped"])
        self.assertEqual(summary["method"], METHOD_BLATANT)

    def test_static_session_reports_exact_fixed_cps(self) -> None:
        backend = FakeBackend()
        session = AutoClickerSession(
            10.0,
            18.0,
            "left",
            Target.any_target(),
            backend,
            1,
            seed=3,
            method=METHOD_STATIC,
        )
        session.start()
        while sum(1 for kind, _ in backend.events if kind == "press") < 4:
            pass
        session.stop()
        session.wait(3000)
        snap = session.snapshot()
        self.assertAlmostEqual(snap["cps"], 14.0, places=6)
        expected_gap = 1000.0 / 14.0
        self.assertTrue(all(abs(gap - expected_gap) < 1e-9 for gap in snap["recent"]))

    def test_session_uses_selected_method_and_records_it(self) -> None:
        backend = FakeBackend()
        session = AutoClickerSession(
            1.0,
            30.0,
            "left",
            Target.any_target(),
            backend,
            1,
            seed=11,
            method=METHOD_GAUSSIAN,
            sigma=0.20,
        )
        session.start()
        while sum(1 for kind, _ in backend.events if kind == "press") < 4:
            pass
        session.stop()
        session.wait(3000)
        snap = session.snapshot()
        self.assertEqual(snap["method"], METHOD_GAUSSIAN)
        self.assertAlmostEqual(snap["sigma"], 0.20)
        self.assertTrue(all(33.0 <= gap <= 1000.0 for gap in snap["recent"]))
        self.assertEqual(session.summary()["method"], METHOD_GAUSSIAN)


if __name__ == "__main__":
    unittest.main()
