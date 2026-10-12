"""Load and validate config.toml.

Every setting has a default, so an empty file gives a plain clock. Unknown
keys are rejected so a typo doesn't silently do nothing.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class ConfigError(ValueError):
    """Raised with a message that names the bad setting."""


@dataclass
class DisplayConfig:
    dio: int = 17
    clk: int = 27
    stb: int = 22
    brightness: int = 5
    led_color: str = "red"
    buttons: bool = True
    scroll_step: float = 0.3
    time_format: str = "%H %M %S"
    date_format: str = "%d-%m-%y"


@dataclass
class DimmingConfig:
    enabled: bool = False
    night_start: dt.time = dt.time(22, 0)
    night_end: dt.time = dt.time(7, 0)
    night_brightness: int = 0

    def is_night(self, now: dt.time) -> bool:
        if self.night_start <= self.night_end:
            return self.night_start <= now < self.night_end
        return now >= self.night_start or now < self.night_end


@dataclass
class MessagesConfig:
    default_duration: float = 15.0
    max_length: int = 200
    max_queue: int = 10


@dataclass
class ScheduleEntry:
    time: dt.time
    text: str
    days: Optional[FrozenSet[int]] = None  # None = every day; 0 = Monday
    duration: Optional[float] = None
    alarm: bool = False

    def matches(self, now: dt.datetime) -> bool:
        if (now.hour, now.minute) != (self.time.hour, self.time.minute):
            return False
        return self.days is None or now.weekday() in self.days


@dataclass
class AlarmConfig:
    timeout: float = 120.0
    snooze_minutes: float = 5.0


@dataclass
class BuzzerConfig:
    enabled: bool = False
    pin: int = 10


@dataclass
class WeatherConfig:
    enabled: bool = False
    latitude: float = 0.0
    longitude: float = 0.0
    unit: str = "celsius"
    rotate: bool = True


@dataclass
class WebConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 5000
    users: Dict[str, str] = field(default_factory=dict)


@dataclass
class Config:
    display: DisplayConfig = field(default_factory=DisplayConfig)
    dimming: DimmingConfig = field(default_factory=DimmingConfig)
    messages: MessagesConfig = field(default_factory=MessagesConfig)
    schedule: List[ScheduleEntry] = field(default_factory=list)
    alarm: AlarmConfig = field(default_factory=AlarmConfig)
    buzzer: BuzzerConfig = field(default_factory=BuzzerConfig)
    weather: WeatherConfig = field(default_factory=WeatherConfig)
    web: WebConfig = field(default_factory=WebConfig)


def load_config(path) -> Config:
    path = Path(path)
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        raise ConfigError(
            f"{path} not found. Copy config.example.toml to {path.name} and edit it."
        ) from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from None
    return parse_config(data)


def parse_config(data: Dict[str, Any]) -> Config:
    data = dict(data)
    config = Config()

    s = _Section(data.pop("display", {}), "display")
    d = config.display
    d.dio = s.integer("dio", d.dio, 0, 27)
    d.clk = s.integer("clk", d.clk, 0, 27)
    d.stb = s.integer("stb", d.stb, 0, 27)
    d.brightness = s.integer("brightness", d.brightness, 0, 7)
    d.led_color = s.choice("led_color", d.led_color, ("red", "green"))
    d.buttons = s.boolean("buttons", d.buttons)
    d.scroll_step = s.number("scroll_step", d.scroll_step, 0.05, 5)
    d.time_format = s.string("time_format", d.time_format)
    d.date_format = s.string("date_format", d.date_format)
    s.done()

    s = _Section(data.pop("dimming", {}), "dimming")
    m = config.dimming
    m.enabled = s.boolean("enabled", m.enabled)
    m.night_start = s.time("night_start", m.night_start)
    m.night_end = s.time("night_end", m.night_end)
    m.night_brightness = s.integer("night_brightness", m.night_brightness, 0, 7)
    s.done()

    s = _Section(data.pop("messages", {}), "messages")
    g = config.messages
    g.default_duration = s.number("default_duration", g.default_duration, 1, 600)
    g.max_length = s.integer("max_length", g.max_length, 1, 2000)
    g.max_queue = s.integer("max_queue", g.max_queue, 1, 100)
    s.done()

    s = _Section(data.pop("alarm", {}), "alarm")
    a = config.alarm
    a.timeout = s.number("timeout", a.timeout, 5, 3600)
    a.snooze_minutes = s.number("snooze_minutes", a.snooze_minutes, 0.1, 120)
    s.done()

    s = _Section(data.pop("buzzer", {}), "buzzer")
    b = config.buzzer
    b.enabled = s.boolean("enabled", b.enabled)
    b.pin = s.integer("pin", b.pin, 0, 27)
    s.done()

    s = _Section(data.pop("weather", {}), "weather")
    w = config.weather
    w.enabled = s.boolean("enabled", w.enabled)
    w.latitude = s.number("latitude", w.latitude, -90, 90)
    w.longitude = s.number("longitude", w.longitude, -180, 180)
    w.unit = s.choice("unit", w.unit, ("celsius", "fahrenheit"))
    w.rotate = s.boolean("rotate", w.rotate)
    s.done()

    s = _Section(data.pop("web", {}), "web")
    e = config.web
    e.enabled = s.boolean("enabled", e.enabled)
    e.host = s.string("host", e.host)
    e.port = s.integer("port", e.port, 1, 65535)
    e.users = s.users("users")
    s.done()

    entries = data.pop("schedule", [])
    if not isinstance(entries, list):
        raise ConfigError("schedule must be written as [[schedule]] entries")
    for index, raw in enumerate(entries, start=1):
        config.schedule.append(_schedule_entry(raw, f"schedule entry {index}"))

    if data:
        raise ConfigError(f"unknown section(s): {', '.join(sorted(data))}")
    return config


def _schedule_entry(raw: Any, name: str) -> ScheduleEntry:
    s = _Section(raw, name)
    if "time" not in s.data or "text" not in s.data:
        raise ConfigError(f"{name}: needs both time and text")
    when = s.time("time", dt.time(0, 0))
    text = s.string("text", "")
    if not text.strip():
        raise ConfigError(f"{name}: text is empty")
    days_raw = s.data.pop("days", None)
    days: Optional[FrozenSet[int]] = None
    if days_raw is not None:
        if not isinstance(days_raw, list) or not days_raw:
            raise ConfigError(f'{name}: days must be a list like ["mon", "fri"]')
        picked = []
        for day in days_raw:
            key = str(day).strip().lower()[:3]
            if key not in DAYS:
                raise ConfigError(f"{name}: unknown day {day!r}")
            picked.append(DAYS.index(key))
        days = frozenset(picked)
    duration = None
    if "duration" in s.data:
        duration = s.number("duration", 0, 1, 3600)
    alarm = s.boolean("alarm", False)
    s.done()
    return ScheduleEntry(time=when, text=text, days=days, duration=duration, alarm=alarm)


class _Section:
    """Pops validated values out of one TOML table."""

    def __init__(self, data: Any, name: str) -> None:
        if not isinstance(data, dict):
            raise ConfigError(f"{name}: expected a table of settings")
        self.data = dict(data)
        self.name = name

    def _fail(self, key: str, expected: str) -> ConfigError:
        return ConfigError(f"{self.name}.{key}: expected {expected}")

    def boolean(self, key: str, default: bool) -> bool:
        value = self.data.pop(key, default)
        if not isinstance(value, bool):
            raise self._fail(key, "true or false")
        return value

    def integer(self, key: str, default: int, low: int, high: int) -> int:
        value = self.data.pop(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise self._fail(key, f"a whole number from {low} to {high}")
        return value

    def number(self, key: str, default: float, low: float, high: float) -> float:
        value = self.data.pop(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            raise self._fail(key, f"a number from {low} to {high}")
        return float(value)

    def string(self, key: str, default: str) -> str:
        value = self.data.pop(key, default)
        if not isinstance(value, str):
            raise self._fail(key, "text in quotes")
        return value

    def choice(self, key: str, default: str, options) -> str:
        value = self.data.pop(key, default)
        if value not in options:
            raise self._fail(key, "one of " + ", ".join(options))
        return value

    def time(self, key: str, default: dt.time) -> dt.time:
        value = self.data.pop(key, default)
        if isinstance(value, dt.time):
            return value.replace(second=0, microsecond=0, tzinfo=None)
        if isinstance(value, str):
            try:
                hour, minute = value.strip().split(":")
                return dt.time(int(hour), int(minute))
            except ValueError:
                pass
        raise self._fail(key, 'a time like "19:00"')

    def users(self, key: str) -> Dict[str, str]:
        value = self.data.pop(key, {})
        if not isinstance(value, dict):
            raise self._fail(key, "a table of name = password hash")
        for user, stored in value.items():
            if not isinstance(stored, str) or "$" not in stored:
                raise ConfigError(
                    f"{self.name}.{key}.{user}: expected a password hash made with "
                    "`python -m smart_clock hash-password`, not a plain password"
                )
        return dict(value)

    def done(self) -> None:
        if self.data:
            unknown = ", ".join(sorted(self.data))
            raise ConfigError(f"{self.name}: unknown setting(s): {unknown}")
