"""Random-CPS autoclicker with five selectable timing methods.

Every gap is generated in milliseconds and then clamped into
``[1000 / max_cps, 1000 / min_cps]`` so the realised CPS can never leave the
user's range.  The methods trade different shapes of "human noise":

* ``blatant`` (shown as **Random**) — gap ~ Uniform(short, long): the widest
  possible spread.
* ``gaussian`` — gap ~ Normal(mid_gap, sigma * mid_gap), clamped.
* ``poisson`` — gap ~ Exponential(rate = mid_cps): bursty arrivals.
* ``gaussian_poisson`` — rate ~ Normal(mid_cps, sigma * mid_cps), then
  gap ~ Exponential(rate): compound model with a per-click tempo.
* ``static`` (shown as **Static ⚠**) — one fixed gap at the midpoint CPS: no
  randomness at all.

Hold time is always jittered independently (10-45% of the gap, 3-120 ms).
"""

from __future__ import annotations

import math
import random
import threading
import time
from collections import deque

from PySide6.QtCore import QThread, Signal

from .backends import ClickBackend
from .win32 import user32, window_pid
from .windows import Target

MIN_CPS = 1.0
MAX_CPS = 50.0
MIN_HOLD_MS = 3.0
MAX_HOLD_MS = 120.0

METHOD_BLATANT = "blatant"
METHOD_GAUSSIAN = "gaussian"
METHOD_POISSON = "poisson"
METHOD_GAUSSIAN_POISSON = "gaussian_poisson"
METHOD_STATIC = "static"
METHODS = (
    METHOD_BLATANT,
    METHOD_GAUSSIAN,
    METHOD_POISSON,
    METHOD_GAUSSIAN_POISSON,
    METHOD_STATIC,
)
DEFAULT_METHOD = METHOD_BLATANT
DEFAULT_SIGMA = 0.15
MIN_SIGMA = 0.05
MAX_SIGMA = 0.40

METHOD_LABELS = {
    METHOD_BLATANT: "Random",
    METHOD_GAUSSIAN: "Gaussian",
    METHOD_POISSON: "Poisson",
    METHOD_GAUSSIAN_POISSON: "Gaussian + Poisson",
    METHOD_STATIC: "Static ⚠",
}

METHOD_DESCRIPTIONS = {
    METHOD_BLATANT: (
        "Gap uniformly random between 1000/upper and 1000/lower ms. Widest "
        "possible spread: the clicker really does spend time near both bounds."
    ),
    METHOD_GAUSSIAN: (
        "Gap drawn from a normal distribution centred on the midpoint CPS. "
        "Sigma is a percentage of the mean gap (default 15%), then clamped."
    ),
    METHOD_POISSON: (
        "Gaps drawn from an exponential distribution at the mean CPS (Poisson "
        "arrivals). Bursty: many short gaps plus occasional long ones, clamped."
    ),
    METHOD_GAUSSIAN_POISSON: (
        "Per click, a tempo is drawn from a Gaussian around the midpoint CPS "
        "(sigma % of the mean); the gap is then exponential at that tempo, "
        "clamped. Each click gets its own local speed."
    ),
    METHOD_STATIC: (
        "One fixed gap at the midpoint CPS — no random sampling, so the CPS "
        "never moves and every click is perfectly spaced. ⚠ Warn: a perfectly "
        "regular click train is the easiest pattern to spot. Set lower and "
        "upper equal for an exact target CPS."
    ),
}

#: Short hint shown in the compact overlay (limited space).
METHOD_SHORT_LABELS = {
    METHOD_BLATANT: "RANDOM",
    METHOD_GAUSSIAN: "GAUSS",
    METHOD_POISSON: "POISSON",
    METHOD_GAUSSIAN_POISSON: "GAUSS+POISSON",
    METHOD_STATIC: "STATIC ⚠",
}


def normalise_method(value: str | None) -> str:
    return value if value in METHODS else DEFAULT_METHOD


def clamp_sigma(value: float | None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return DEFAULT_SIGMA
    if not math.isfinite(number):
        return DEFAULT_SIGMA
    return min(max(number, MIN_SIGMA), MAX_SIGMA)


def method_label(method: str) -> str:
    return METHOD_LABELS[normalise_method(method)]


def validate_cps(low: float, high: float) -> tuple[float, float]:
    """Return clamped CPS bounds or raise ValueError with a user-facing message."""
    try:
        low_f = float(low)
        high_f = float(high)
    except (TypeError, ValueError):
        raise ValueError("CPS bounds must be numbers.")
    if not math.isfinite(low_f) or not math.isfinite(high_f) or low_f <= 0 or high_f <= 0:
        raise ValueError("CPS bounds must be positive, finite numbers.")
    low_f = min(max(low_f, MIN_CPS), MAX_CPS)
    high_f = min(max(high_f, MIN_CPS), MAX_CPS)
    if low_f > high_f:
        raise ValueError("Lower CPS must be less than or equal to upper CPS.")
    return low_f, high_f


def sync_bounds(low: float, high: float, *, changed: str) -> tuple[float, float]:
    """Keep low <= high after one bound moved.

    ``changed`` is ``"low"`` or ``"high"``: dragging/typing the low bound past
    the high bound pushes the high bound (and vice versa).  Values are clamped
    to the supported CPS range only when they were already out of range.
    """
    low = float(low)
    high = float(high)
    if changed == "low" and low > high:
        high = low
    elif changed == "high" and high < low:
        low = high
    return low, high


def gap_bounds_ms(min_cps: float, max_cps: float) -> tuple[float, float]:
    low_cps, high_cps = validate_cps(min_cps, max_cps)
    return 1000.0 / high_cps, 1000.0 / low_cps


def sample_gap_ms(
    min_cps: float,
    max_cps: float,
    rng: random.Random | None = None,
    method: str = DEFAULT_METHOD,
    sigma: float = DEFAULT_SIGMA,
) -> float:
    """Sample one inter-click gap (ms) for ``method``, clamped to the bounds."""
    low_cps, high_cps = validate_cps(min_cps, max_cps)
    rng = rng or random.Random()
    method = normalise_method(method)
    sigma = clamp_sigma(sigma)
    short, long = 1000.0 / high_cps, 1000.0 / low_cps
    mid_cps = (low_cps + high_cps) / 2.0
    mid_gap = 1000.0 / mid_cps

    if method == METHOD_BLATANT:
        gap = rng.uniform(short, long)
    elif method == METHOD_GAUSSIAN:
        gap = rng.gauss(mid_gap, sigma * mid_gap)
    elif method == METHOD_POISSON:
        gap = rng.expovariate(mid_cps / 1000.0)
    elif method == METHOD_STATIC:
        gap = mid_gap
    else:  # gaussian_poisson
        sigma_cps = sigma * mid_cps
        tempo = mid_cps
        for _ in range(24):
            candidate = rng.gauss(mid_cps, sigma_cps)
            if candidate >= 0.5:
                tempo = candidate
                break
        gap = rng.expovariate(tempo / 1000.0)
    return min(long, max(short, gap))


def sample_hold_ms(gap_ms: float, rng: random.Random | None = None) -> float:
    """Plausible jittered hold: 10-45% of the interval, clamped to 3-120 ms."""
    rng = rng or random.Random()
    low = max(MIN_HOLD_MS, gap_ms * 0.10)
    high = min(MAX_HOLD_MS, max(low, gap_ms * 0.45))
    if high <= low:
        return low
    return rng.uniform(low, high)


class AutoClickerSession(QThread):
    log = Signal(str, str)
    finished_run = Signal(dict)

    def __init__(
        self,
        min_cps: float,
        max_cps: float,
        button: str,
        target: Target,
        backend: ClickBackend,
        own_pid: int,
        restricted: bool = False,
        seed: int | None = None,
        method: str = DEFAULT_METHOD,
        sigma: float = DEFAULT_SIGMA,
        parent=None,
    ):
        super().__init__(parent)
        self.min_cps, self.max_cps = validate_cps(min_cps, max_cps)
        self.button = button
        self.target = target
        self.backend = backend
        self.own_pid = own_pid
        self.restricted = restricted
        self.method = normalise_method(method)
        self.sigma = clamp_sigma(sigma)
        self._rng = random.Random(seed)

        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._sent = 0
        self._skipped = 0
        self._attempts = 0
        self._press_times: deque[float] = deque()
        self._recent: deque[float] = deque(maxlen=240)
        self._held = False
        self._start = 0.0
        self._end = 0.0
        self._last_warn = 0.0
        self._had_target_focus = False
        self._finished = False

    def stop(self) -> None:
        self._stop.set()

    def wait_until(self, deadline: float) -> bool:
        remaining = deadline - time.perf_counter()
        if remaining > 0.008:
            return not self._stop.wait(remaining - 0.002)
        while time.perf_counter() < deadline:
            if self._stop.is_set():
                return False
        return not self._stop.is_set()

    def _foreground_is_target(self) -> bool:
        hwnd = int(user32.GetForegroundWindow() or 0)
        return bool(hwnd) and window_pid(hwnd) == self.target.pid

    def _scope_problem(self) -> str:
        if not self.restricted:
            return ""
        if not user32.IsWindow(self.target.hwnd):
            return "Target window closed"
        if self._foreground_is_target():
            self._had_target_focus = True
            return ""
        if self._had_target_focus:
            return "Target lost foreground focus"
        return ""

    def _cps_now(self) -> float:
        if self.method == METHOD_STATIC and self._recent:
            # The scheduled gap is constant, so report it directly instead of
            # letting a 1-second sliding count flicker between 13 and 14.
            return 1000.0 / (sum(self._recent) / len(self._recent))
        cutoff = time.perf_counter() - 1.0
        while self._press_times and self._press_times[0] < cutoff:
            self._press_times.popleft()
        return float(len(self._press_times))

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "running": not self._finished and not self._stop.is_set(),
                "cps": self._cps_now(),
                "sent": self._sent,
                "skipped": self._skipped,
                "attempts": self._attempts,
                "recent": list(self._recent),
                "min_cps": self.min_cps,
                "max_cps": self.max_cps,
                "button": self.button,
                "held": self._held,
                "method": self.method,
                "sigma": self.sigma,
            }

    def summary(self) -> dict:
        with self._lock:
            now = self._end or time.perf_counter()
            elapsed = max(0.0, now - self._start)
            return {
                "sent": self._sent,
                "skipped": self._skipped,
                "attempts": self._attempts,
                "elapsed_s": elapsed,
                "avg_cps": (self._sent / elapsed) if elapsed > 0 else 0.0,
                "recent": list(self._recent),
                "method": self.method,
            }

    def run(self) -> None:
        self._start = time.perf_counter()
        try:
            if self.restricted and not user32.IsWindow(self.target.hwnd):
                self.log.emit("error", "Target window is gone — auto-clicker did not start")
                return
            self._had_target_focus = (
                self._foreground_is_target() if self.restricted else False
            )
            while not self._stop.is_set():
                problem = self._scope_problem()
                if problem:
                    self.log.emit("error", f"{problem} — auto-clicker stopped")
                    break
                gap = sample_gap_ms(
                    self.min_cps, self.max_cps, self._rng, self.method, self.sigma
                )
                press_at = time.perf_counter()
                with self._lock:
                    self._attempts += 1
                    self._held = True
                result = self.backend.press(self.button, self.target, self.own_pid)
                if not result.ok:
                    with self._lock:
                        self._held = False
                        self._skipped += 1
                    now = time.perf_counter()
                    if now - self._last_warn > 1.0:
                        self._last_warn = now
                        self.log.emit(
                            "warn",
                            f"Click skipped: {result.reason or 'target guard rejected the press'}",
                        )
                    if not self.wait_until(press_at + gap / 1000.0):
                        break
                    continue

                with self._lock:
                    self._sent += 1
                    self._press_times.append(press_at)
                    self._recent.append(gap)
                hold = sample_hold_ms(gap, self._rng)
                try:
                    self.wait_until(press_at + min(hold, gap * 0.9) / 1000.0)
                finally:
                    # Release even when stopped mid-click.
                    self.backend.release(self.button)
                    with self._lock:
                        self._held = False
                next_at = press_at + gap / 1000.0
                if not self.wait_until(next_at):
                    break
        finally:
            self._end = time.perf_counter()
            self._finished = True
            try:
                self.backend.close()
            except Exception:
                pass
            self.finished_run.emit(self.summary())
