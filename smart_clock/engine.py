"""The clock itself: one loop that owns the display.

Only the thread inside `run()` touches the board. The web server (or
anything else) talks to it through `submit()`, `dismiss()`, `set_power()`
and `set_brightness()`, which just leave a note for the loop to pick up.
"""

from __future__ import annotations

import datetime as dt
import logging
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from typing import Deque, List, Optional, Tuple

from . import font
from .buzzer import NullBuzzer
from .config import Config
from .display import Display

log = logging.getLogger(__name__)

POLL_SECONDS = 0.05         # how often commands and the schedule are checked
BUTTON_SAMPLE_SECONDS = 0.04  # minimum gap between two button reads
SCROLL_HOLD_SECONDS = 0.8   # pause on the first and last frame of a scroll
ALARM_HOLD_SECONDS = 3.0    # a short alarm text re-animates this often
MIN_HOLD_SECONDS = 1.0
PAGE_SECONDS = 10.0         # date/weather page falls back to the time after this
SWEEP_CELL = 0x08           # bottom segment
SWEEP_PATH = tuple(range(8)) + tuple(range(6, -1, -1))

(BUTTON_DISMISS, BUTTON_SNOOZE, BUTTON_REPLAY, BUTTON_PAGE,
 BUTTON_DIMMER, BUTTON_BRIGHTER, BUTTON_UNUSED, BUTTON_POWER) = range(8)


@dataclass
class Message:
    text: str
    duration: float
    alarm: bool = False
    source: str = "web"


class SystemClock:
    """Real time. Tests swap in a fake one to run instantly."""

    def now(self) -> dt.datetime:
        return dt.datetime.now()

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class _Dismissed(Exception):
    pass


class _Stopped(Exception):
    pass


class SmartClock:
    def __init__(self, config: Config, display: Display, buzzer=None,
                 weather=None, clock=None) -> None:
        self.config = config
        self.display = display
        self.buzzer = buzzer or NullBuzzer()
        self.weather = weather
        self.clock = clock or SystemClock()

        # Shared with other threads.
        self._lock = threading.Lock()
        self._messages: Deque[Message] = deque()
        self._commands: "queue.SimpleQueue[tuple]" = queue.SimpleQueue()
        self._stop = threading.Event()

        # Touched only by the thread running run().
        self._current: Optional[Message] = None
        self._last: Optional[Message] = None
        self._dismiss = False
        self._snooze = False
        self._snoozed: List[Tuple[dt.datetime, Message]] = []
        self._buttons = 0
        self._raw_buttons = 0
        self._buttons_read_at = -1.0
        self._page = "time"
        self._page_until = 0.0
        self._minute: Optional[tuple] = None
        self._period: Optional[str] = None
        self._dirty = False

    # ---------------------------------------------------------------- public
    def submit(self, text: str, duration: Optional[float] = None,
               source: str = "web") -> bool:
        """Queue a message. Returns False when the queue is full."""
        message = Message(
            text=text,
            duration=float(duration or self.config.messages.default_duration),
            source=source,
        )
        with self._lock:
            if len(self._messages) >= self.config.messages.max_queue:
                return False
            self._messages.append(message)
        return True

    def dismiss(self) -> None:
        self._commands.put(("dismiss",))

    def set_power(self, on: bool) -> None:
        self._commands.put(("power", bool(on)))

    def set_brightness(self, level: int) -> None:
        self._commands.put(("brightness", int(level)))

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict:
        current = self._current
        with self._lock:
            queued = len(self._messages)
        return {
            "time": self.clock.now().strftime("%H:%M:%S"),
            "display_on": self.display.powered,
            "brightness": self.display.brightness,
            "segments": list(self.display.segments),
            "leds": list(self.display.leds),
            "message": current.text if current else None,
            "alarm": bool(current and current.alarm),
            "queued": queued,
            "weather": self.weather.text() if self.weather else None,
        }

    def run(self) -> None:
        """Run until stop() is called. Always leaves the display blank."""
        log.info("clock running")
        try:
            now = self.clock.now()
            self._minute = _minute_key(now)  # don't fire this minute's entries on boot
            self._apply_dimming(now)
            self._sweep(step=0.05)
            while True:
                self._poll()
                message = self._take_message()
                if message is not None:
                    self._play(message)
                    continue
                if self.display.powered:
                    self._render_idle()
                self._idle_wait()
        except _Stopped:
            pass
        finally:
            self.buzzer.stop()
            self.display.clear()
            log.info("clock stopped, display cleared")

    # ------------------------------------------------------------- the loop
    def _poll(self) -> None:
        if self._stop.is_set():
            raise _Stopped()
        self._run_commands()
        self._read_buttons()
        now = self.clock.now()
        self._check_schedule(now)
        self._check_snoozed(now)
        self._apply_dimming(now)

    def _sleep(self, seconds: float) -> None:
        """Wait, staying responsive. Raises if the message was dismissed."""
        end = self.clock.monotonic() + seconds
        while True:
            self._poll()
            if self._dismiss:
                raise _Dismissed()
            left = end - self.clock.monotonic()
            if left <= 0:
                return
            self.clock.sleep(min(POLL_SECONDS, left))

    def _idle_wait(self) -> None:
        """Wait for the next whole second, or until there is something to do."""
        self._dirty = False
        end = self.clock.monotonic() + 1.0 - self.clock.now().microsecond / 1e6
        while True:
            left = end - self.clock.monotonic()
            if left <= 0:
                return
            self.clock.sleep(min(POLL_SECONDS, left))
            self._poll()
            if self._dirty or self._has_messages():
                return

    def _render_idle(self) -> None:
        now = self.clock.now()
        if self._page != "time" and self.clock.monotonic() >= self._page_until:
            self._page = "time"
        page = self._page
        weather_text = self.weather.text() if self.weather else None
        if (page == "time" and weather_text and self.config.weather.rotate
                and 30 <= now.second < 33):
            page = "weather"
        if page == "date":
            cells = font.frames(now.strftime(self.config.display.date_format))[0]
        elif page == "weather":
            cells = font.centered(weather_text or "no data")
        else:
            cells = font.frames(now.strftime(self.config.display.time_format))[0]
        self.display.show(cells)

    # ------------------------------------------------------------- messages
    def _play(self, message: Message) -> None:
        was_powered = self.display.powered
        if not was_powered:
            self.display.set_power(True)
        self._current = message
        self._dismiss = self._snooze = False
        log.info("showing %s message: %r", message.source, message.text)
        frames = font.frames(message.text)
        started: Optional[float] = None
        try:
            if message.alarm:
                self.buzzer.start()
            while True:
                self._sweep()
                if started is None:
                    started = self.clock.monotonic()
                self.display.show(frames[0])
                if len(frames) == 1:
                    left = message.duration - (self.clock.monotonic() - started)
                    if message.alarm:
                        left = min(left, ALARM_HOLD_SECONDS)
                    self._sleep(max(left, MIN_HOLD_SECONDS))
                else:
                    self._sleep(SCROLL_HOLD_SECONDS)
                    for frame in frames[1:]:
                        self.display.show(frame)
                        self._sleep(self.config.display.scroll_step)
                    self._sleep(SCROLL_HOLD_SECONDS)
                if self.clock.monotonic() - started >= message.duration:
                    break
        except _Dismissed:
            if self._snooze and message.alarm:
                due = self.clock.now() + dt.timedelta(minutes=self.config.alarm.snooze_minutes)
                self._snoozed.append((due, message))
                log.info("alarm snoozed until %s", due.strftime("%H:%M:%S"))
            else:
                log.info("message dismissed")
        finally:
            self.buzzer.stop()
            self.display.set_leds(False)
            self._current = None
            self._last = message
            self._dismiss = self._snooze = False
            self._dirty = True
            if message.alarm and not was_powered:
                self.display.set_power(False)

    def _sweep(self, step: float = 0.1) -> None:
        """The back-and-forth light that announces a message."""
        display = self.display
        display.set_leds(False)
        for pos in SWEEP_PATH:
            cells = [0] * font.WIDTH
            cells[pos] = SWEEP_CELL
            display.show(cells)
            display.set_led(font.WIDTH - 1 - pos, True)
            self._sleep(step)
            display.set_led(font.WIDTH - 1 - pos, False)
        display.show(font.BLANK)

    def _take_message(self) -> Optional[Message]:
        with self._lock:
            return self._messages.popleft() if self._messages else None

    def _has_messages(self) -> bool:
        with self._lock:
            return bool(self._messages)

    def _enqueue(self, message: Message, front: bool = False) -> None:
        with self._lock:
            if front:
                self._messages.appendleft(message)
            else:
                self._messages.append(message)

    # ------------------------------------------------- schedule and dimming
    def _check_schedule(self, now: dt.datetime) -> None:
        key = _minute_key(now)
        if key == self._minute:
            return
        self._minute = key
        for entry in self.config.schedule:
            if not entry.matches(now):
                continue
            if not entry.alarm and not self.display.powered:
                continue  # display is off; only alarms wake it
            fallback = (self.config.alarm.timeout if entry.alarm
                        else self.config.messages.default_duration)
            self._enqueue(Message(
                text=entry.text,
                duration=entry.duration or fallback,
                alarm=entry.alarm,
                source="schedule",
            ))

    def _check_snoozed(self, now: dt.datetime) -> None:
        if not self._snoozed:
            return
        due = [message for when, message in self._snoozed if when <= now]
        if due:
            self._snoozed = [(w, m) for w, m in self._snoozed if w > now]
            for message in due:
                self._enqueue(message, front=True)

    def _apply_dimming(self, now: dt.datetime) -> None:
        dimming = self.config.dimming
        if not dimming.enabled:
            return
        period = "night" if dimming.is_night(now.time()) else "day"
        if period != self._period:
            # Only on the change, so a manual adjustment lasts until then.
            self._period = period
            self.display.set_brightness(
                dimming.night_brightness if period == "night"
                else self.config.display.brightness
            )

    # --------------------------------------------------- commands and buttons
    def _run_commands(self) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                return
            if command[0] == "dismiss":
                self._request_dismiss()
            elif command[0] == "power":
                self._set_power(command[1])
            elif command[0] == "brightness":
                self.display.set_brightness(command[1])

    def _read_buttons(self) -> None:
        if not self.config.display.buttons:
            return
        now = self.clock.monotonic()
        if now - self._buttons_read_at < BUTTON_SAMPLE_SECONDS:
            return
        self._buttons_read_at = now
        raw = self.display.read_buttons()
        # Two matching reads a moment apart, so one noisy read can't press a button.
        mask = raw if raw == self._raw_buttons else self._buttons
        self._raw_buttons = raw
        pressed = mask & ~self._buttons  # act on the press, not the hold
        self._buttons = mask
        for button in range(font.WIDTH):
            if pressed & (1 << button):
                self._on_button(button)

    def _on_button(self, button: int) -> None:
        if button == BUTTON_POWER:
            self._set_power(not self.display.powered)
            return
        if not self.display.powered:
            return
        if button == BUTTON_DISMISS:
            self._request_dismiss()
        elif button == BUTTON_SNOOZE:
            if self._current is not None and self._current.alarm:
                self._request_dismiss(snooze=True)
        elif button == BUTTON_REPLAY:
            if self._current is None and self._last is not None:
                duration = (self.config.messages.default_duration if self._last.alarm
                            else self._last.duration)
                self._enqueue(replace(self._last, duration=duration,
                                      alarm=False, source="replay"))
        elif button == BUTTON_PAGE:
            pages = ["time", "date"] + (["weather"] if self.weather else [])
            self._page = pages[(pages.index(self._page) + 1) % len(pages)]
            self._page_until = self.clock.monotonic() + PAGE_SECONDS
            self._dirty = True
        elif button == BUTTON_DIMMER:
            self.display.set_brightness(self.display.brightness - 1)
        elif button == BUTTON_BRIGHTER:
            self.display.set_brightness(self.display.brightness + 1)

    def _request_dismiss(self, snooze: bool = False) -> None:
        if self._current is not None:
            self._dismiss = True
            self._snooze = snooze

    def _set_power(self, on: bool) -> None:
        if on == self.display.powered:
            return
        if not on:
            with self._lock:
                self._messages.clear()
            self._request_dismiss()
        self.display.set_power(on)
        self._dirty = True
        log.info("display turned %s", "on" if on else "off")


def _minute_key(now: dt.datetime) -> tuple:
    return (now.date(), now.hour, now.minute)
