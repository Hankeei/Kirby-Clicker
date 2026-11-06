"""Playback scheduler with millisecond-accurate hold/gap timing."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Signal

from . import win32
from .backends import ClickBackend, ClickResult, NullBackend
from .profile import Click, ClickProfile, ProfileStats, compute_stats
from .windows import Target


@dataclass
class PlaybackSnapshot:
    running: bool = False
    held: bool = False
    dry_run: bool = False
    sent: int = 0
    skipped: int = 0
    attempts: int = 0
    cps_now: float = 0.0
    target_cps: float = 0.0
    intervals_ms: list[float] = field(default_factory=list)
    duration_ms: float = 0.0
    loops: int = 0
    last_reason: str = ""
    button: str = "left"


@dataclass
class DryRunEvent:
    lap: int
    index: int
    planned_down_ms: float
    actual_down_ms: float
    hold_ms: int
    gap_ms: int
    actual_hold_ms: float


class PlaybackSession(QThread):
    log = Signal(str, str)  # level, message
    finished_playback = Signal(object)

    def __init__(
        self,
        profile: ClickProfile,
        target: Target,
        backend: ClickBackend,
        own_pid: int,
        dry_run: bool = False,
        restricted: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.clicks: list[Click] = list(profile.clicks)
        self.button = profile.button
        self.stats: ProfileStats = compute_stats(self.clicks)
        self.target = target
        self.backend = backend if not dry_run else NullBackend()
        self.own_pid = own_pid
        self.dry_run = dry_run
        self.restricted = restricted

        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._start = 0.0
        self._end = 0.0
        self._down_times: list[float] = []
        self._intervals: list[float] = []
        self._held = False
        self._sent = 0
        self._skipped = 0
        self._attempts = 0
        self._loops = 0
        self._last_reason = ""
        self._last_warn = 0.0
        self._stop_reason = ""
        self._had_target_focus = False
        self._finished = False
        self._summary: dict = {}
        self._dry_events: list[DryRunEvent] = []

    # -- UI polling --------------------------------------------------------
    def snapshot(self) -> PlaybackSnapshot:
        now = time.perf_counter()
        with self._lock:
            recent = [t for t in self._down_times if now - t <= 1.0]
            intervals = list(self._intervals[-40:])
            duration = (now - self._start) * 1000 if self._start else 0.0
            return PlaybackSnapshot(
                running=self.isRunning(),
                held=self._held,
                dry_run=self.dry_run,
                sent=self._sent,
                skipped=self._skipped,
                attempts=self._attempts,
                cps_now=float(len(recent)),
                target_cps=self.stats.avg_cps,
                intervals_ms=intervals,
                duration_ms=max(0.0, duration),
                loops=self._loops,
                last_reason=self._last_reason,
                button=self.button,
            )

    def dry_run_events(self) -> list[DryRunEvent]:
        with self._lock:
            return list(self._dry_events)

    def summary(self) -> dict:
        with self._lock:
            return dict(self._summary)

    # -- lifecycle ---------------------------------------------------------
    def stop(self) -> None:
        self._stop.set()

    def _wait_until(self, deadline: float) -> bool:
        """Sleep to a perf_counter deadline, spinning the last ~2 ms.

        timeBeginPeriod(1) is active, so the Event.wait() coarse sleep plus spin
        keeps the cadence at roughly +/- a millisecond instead of 15.6 ms ticks.
        """
        while True:
            if self._stop.is_set():
                return False
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return True
            if remaining > 0.002:
                self._stop.wait(min(remaining - 0.0008, 0.004))
            # else: tight spin for the final two milliseconds

    def _warn(self, message: str) -> None:
        now = time.perf_counter()
        if now - self._last_warn < 1.0:
            return
        self._last_warn = now
        self.log.emit("warn", message)

    def _stats(self) -> dict:
        now = self._end if self._end else time.perf_counter()
        start = self._start or now
        elapsed = max(0.0, now - start)
        return {
            "sent": self._sent,
            "skipped": self._skipped,
            "attempts": self._attempts,
            "elapsed_s": elapsed,
            "loops": self._loops,
            "dry_run": self.dry_run,
            "target_cps": self.stats.avg_cps,
            "button": self.button,
            "restricted": self.restricted,
            "stop_reason": self._stop_reason,
        }

    def _foreground_is_target(self) -> bool:
        hwnd = int(win32.user32.GetForegroundWindow() or 0)
        return bool(hwnd) and win32.window_pid(hwnd) == self.target.pid

    def _scope_problem(self) -> str:
        """Reason to stop a restricted real playback, or '' when it is safe."""
        if not self.restricted or self.dry_run:
            return ""
        if not win32.is_window(self.target.hwnd):
            return "Target window closed"
        if self._foreground_is_target():
            self._had_target_focus = True
            return ""
        if self._had_target_focus:
            return "Target lost foreground focus"
        return ""

    def _abort(self, reason: str) -> None:
        self._stop_reason = reason
        self.log.emit("error", f"{reason} — restricted playback stopped")

    def run(self) -> None:  # noqa: C901 - timing loop is intentionally explicit
        try:
            win32.winmm.timeBeginPeriod(1)
        except Exception:
            pass
        self._start = time.perf_counter()
        try:
            if not self.clicks:
                self.log.emit("error", "Cannot play an empty profile")
                return
            if not self.target.any_process and not win32.is_window(self.target.hwnd):
                self.log.emit("error", f"Target window is gone: {self.target.label}")
                return
            if self.restricted and not self.dry_run:
                self._had_target_focus = self._foreground_is_target()

            mode = "Dry-run preview" if self.dry_run else "Playback ARMED"
            self.log.emit(
                "accent",
                f"{mode} — {self.stats.clicks} clicks · target {self.stats.avg_cps:.2f} CPS · "
                f"backend {'dry-run (no clicks)' if self.dry_run else self.backend.name}",
            )

            plan_ms = 0.0
            lap = 0
            while not self._stop.is_set():
                for index, click in enumerate(self.clicks):
                    if self._stop.is_set():
                        break
                    if not self.target.any_process and not win32.is_window(self.target.hwnd):
                        self.log.emit("error", f"Target window closed — playback stopped")
                        return
                    problem = self._scope_problem()
                    if problem:
                        self._abort(problem)
                        return

                    deadline = self._start + plan_ms / 1000.0
                    if not self._wait_until(deadline):
                        break
                    problem = self._scope_problem()
                    if problem:
                        self._abort(problem)
                        return
                    down_at = time.perf_counter()
                    with self._lock:
                        self._attempts += 1
                    result = (
                        ClickResult(True)
                        if self.dry_run
                        else self.backend.press(self.button, self.target, self.own_pid)
                    )
                    hold_start = down_at
                    if result.ok:
                        with self._lock:
                            self._sent += 1
                            self._held = True
                            if self._down_times:
                                self._intervals.append((down_at - self._down_times[-1]) * 1000.0)
                            self._down_times.append(down_at)
                            if len(self._down_times) > 256:
                                del self._down_times[:128]
                            if len(self._intervals) > 256:
                                del self._intervals[:128]
                        if self.dry_run:
                            with self._lock:
                                self._dry_events.append(
                                    DryRunEvent(
                                        lap=lap,
                                        index=index,
                                        planned_down_ms=plan_ms,
                                        actual_down_ms=(down_at - self._start) * 1000.0,
                                        hold_ms=click.hold_ms,
                                        gap_ms=click.gap_ms,
                                        actual_hold_ms=0.0,
                                    )
                                )
                            self.log.emit(
                                "dry",
                                f"DRY #{index + 1} lap {lap + 1} @ {plan_ms:.1f}ms "
                                f"hold={click.hold_ms}ms gap={click.gap_ms}ms",
                            )
                        try:
                            hold_finished = self._wait_until(
                                hold_start + click.hold_ms / 1000.0
                            )
                        finally:
                            # Always finish the in-flight press, even when the
                            # hold trigger was released mid-click.
                            if not self.dry_run:
                                self.backend.release(self.button)
                            with self._lock:
                                self._held = False
                                if self.dry_run and self._dry_events:
                                    self._dry_events[-1].actual_hold_ms = (
                                        time.perf_counter() - hold_start
                                    ) * 1000.0
                        if not hold_finished:
                            break
                    else:
                        with self._lock:
                            self._skipped += 1
                            self._last_reason = result.reason
                        self._warn(f"Click skipped: {result.reason}")

                    plan_ms += max(1, click.hold_ms + click.gap_ms)
                    elapsed_ms = (time.perf_counter() - self._start) * 1000.0
                    if plan_ms < elapsed_ms + 0.05:
                        plan_ms = elapsed_ms + 0.05
                    if self._stop.is_set():
                        break
                else:
                    with self._lock:
                        self._loops += 1
                    lap += 1
                    continue
                break

        finally:
            self.backend.close()
            with self._lock:
                self._held = False
                self._end = time.perf_counter()
                self._summary = self._stats()
                self._finished = True
            try:
                win32.winmm.timeEndPeriod(1)
            except Exception:
                pass
            summary = self.summary()
            elapsed = summary.get("elapsed_s", 0.0)
            stop_note = (
                f" · stopped: {summary['stop_reason']}" if summary.get("stop_reason") else ""
            )
            self.log.emit(
                "info",
                f"{'Preview' if self.dry_run else 'Playback'} stopped — "
                f"sent {summary.get('sent', 0)} clicks · skipped {summary.get('skipped', 0)} · "
                f"{elapsed:.2f}s · {summary.get('loops', 0)} loop(s){stop_note}",
            )
            self.finished_playback.emit(summary)
