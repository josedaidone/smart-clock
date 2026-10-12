"""Shared test rig: a simulated board and a clock that runs instantly."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from smart_clock import font  # noqa: E402
from smart_clock.config import Config  # noqa: E402
from smart_clock.display import Display, SimBackend  # noqa: E402
from smart_clock.engine import SmartClock  # noqa: E402

MONDAY_NOON = dt.datetime(2026, 1, 5, 12, 0, 0)


class FakeClock:
    """Time only moves when the engine sleeps, so a minute takes milliseconds."""

    def __init__(self, start: dt.datetime) -> None:
        self.start = start
        self.t = 0.0
        self.events = []
        self.stop_at = None
        self.engine = None

    def now(self) -> dt.datetime:
        return self.start + dt.timedelta(seconds=self.t)

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += max(seconds, 0.0)
        while self.events and self.events[0][0] <= self.t:
            self.events.pop(0)[1]()
        if self.stop_at is not None and self.t >= self.stop_at:
            self.engine.stop()

    def at(self, t: float, action) -> None:
        self.events.append((t, action))
        self.events.sort(key=lambda event: event[0])


class FakeBuzzer:
    def __init__(self) -> None:
        self.on = False
        self.starts = 0

    def start(self) -> None:
        self.on = True
        self.starts += 1

    def stop(self) -> None:
        self.on = False


class Rig:
    def __init__(self, config=None, start=MONDAY_NOON, weather=None) -> None:
        self.config = config or Config()
        self.backend = SimBackend()
        self.history = []
        self.display = Display(
            self.backend, self.config.display.brightness, self.config.display.led_color,
            on_change=lambda d: self.history.append(list(d.segments)),
        )
        self.clock = FakeClock(start)
        self.buzzer = FakeBuzzer()
        self.engine = SmartClock(self.config, self.display, buzzer=self.buzzer,
                                 weather=weather, clock=self.clock)
        self.clock.engine = self.engine
        self.snapshots = {}

    def at(self, t, action) -> None:
        self.clock.at(t, action)

    def tap(self, t, button) -> None:
        """Press a button at time t and let go shortly after."""
        self.at(t, lambda: self.backend.press(button))
        self.at(t + 0.2, self.backend.release)

    def snapshot(self, t, name=None) -> None:
        self.at(t, lambda: self.snapshots.__setitem__(name or t, list(self.display.segments)))

    def run(self, seconds) -> None:
        self.clock.stop_at = seconds
        self.engine.run()


def cells(text):
    return font.frames(text)[0]


@pytest.fixture
def rig():
    return Rig()
