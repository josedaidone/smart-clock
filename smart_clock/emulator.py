"""An emulated board for `run --simulate`.

The clock, the web control and (when it is installed) the rpi_TM1638
library all run for real. What is emulated is the far end of the wires:
`FakeChip` stands in for RPi.GPIO and decodes the bit-banged signals the
way the TM1638 would, so the emulator page shows what the chip received
and the buttons you click there come back through a real key scan.

Without rpi_TM1638 installed it falls back to a plain in-memory board.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import logging
import sys
import threading
import time
import types
from typing import List, Optional

from .config import DisplayConfig
from .display import WIDTH, SimBackend, TM1638Backend
from .engine import SystemClock

log = logging.getLogger(__name__)

MIN_PRESS_SECONDS = 0.15  # a quick click still looks like a real button press


class FakeChip:
    """Stands in for RPi.GPIO and for the TM1638 on the other end of the wires."""

    BCM, OUT, IN, PUD_UP = "BCM", "OUT", "IN", "PUD_UP"

    def __init__(self, dio: int, clk: int, stb: int) -> None:
        self.dio, self.clk, self.stb = dio, clk, stb
        self.key_source = None  # optional callable returning the four key-scan bytes
        self.reset()

    def reset(self) -> None:
        self.level = {}
        self.memory = [0] * 16       # even addresses: digits, odd: LEDs
        self.keys = [0, 0, 0, 0]     # what a key scan returns
        self.display_on = False
        self.brightness: Optional[int] = None
        self.fixed_address = False
        self._begin()

    # ---- the RPi.GPIO surface the library uses
    def setwarnings(self, flag) -> None:
        pass

    def setmode(self, mode) -> None:
        pass

    def setup(self, pin, direction, pull_up_down=None) -> None:
        pass

    def output(self, pin, value) -> None:
        value = bool(value)
        before = self.level.get(pin)
        self.level[pin] = value
        if pin == self.stb:
            if before is not False and value is False:
                self._begin()
        elif pin == self.clk and self.level.get(self.stb) is False:
            if value and before is False and not self.reading:
                self._clock_in(self.level.get(self.dio, False))
            elif not value and before and self.reading:
                self._clock_out()

    def input(self, pin) -> bool:
        return self.read_level

    # ---- the chip
    def _begin(self) -> None:
        self.bits = []
        self.reading = False
        self.address = None
        self.read_position = 0
        self.read_level = False

    def _clock_in(self, bit) -> None:
        self.bits.append(bit)
        if len(self.bits) == 8:
            byte = sum(1 << i for i, b in enumerate(self.bits) if b)  # LSB first
            self.bits = []
            self._byte(byte)

    def _clock_out(self) -> None:
        byte, bit = divmod(self.read_position, 8)
        self.read_level = bool(self.keys[byte % 4] >> bit & 1)
        self.read_position += 1

    def _byte(self, byte: int) -> None:
        if self.address is not None:            # data following an address command
            self.memory[self.address] = byte
            if not self.fixed_address:
                self.address = (self.address + 1) % 16
        elif byte & 0xC0 == 0x40:               # data command
            self.reading = bool(byte & 0x02)
            self.fixed_address = bool(byte & 0x04)
            if self.reading and self.key_source is not None:
                self.keys = self.key_source()
        elif byte & 0xC0 == 0xC0:               # address command
            self.address = byte & 0x0F
        elif byte & 0xC0 == 0x80:               # display control
            self.display_on = bool(byte & 0x08)
            self.brightness = byte & 0x07

    def as_gpio_module(self) -> types.ModuleType:
        module = types.ModuleType("RPi.GPIO")
        for name in ("BCM", "OUT", "IN", "PUD_UP", "setwarnings", "setmode",
                     "setup", "output", "input"):
            setattr(module, name, getattr(self, name))
        return module


def install_fake_gpio(chip: FakeChip) -> None:
    """Make `from RPi import GPIO` hand the library our emulated pins."""
    for name in list(sys.modules):
        if name.startswith("rpi_TM1638"):
            del sys.modules[name]
    package = types.ModuleType("RPi")
    package.GPIO = chip.as_gpio_module()
    sys.modules["RPi"] = package
    sys.modules["RPi.GPIO"] = package.GPIO


class SimClock(SystemClock):
    """Real time, plus an offset so the emulator can jump to any time of day."""

    def __init__(self) -> None:
        self.offset = dt.timedelta(0)

    def now(self) -> dt.datetime:
        return dt.datetime.now() + self.offset

    def set_time(self, when: dt.time) -> None:
        self.offset = dt.datetime.combine(dt.date.today(), when) - dt.datetime.now()

    def reset(self) -> None:
        self.offset = dt.timedelta(0)


class SimBuzzer:
    def __init__(self) -> None:
        self.on = False

    def start(self) -> None:
        self.on = True

    def stop(self) -> None:
        self.on = False


class _SimBoard(SimBackend):
    """The plain in-memory board, with buttons fed by the emulator page."""

    def __init__(self, button_mask) -> None:
        super().__init__()
        self._button_mask = button_mask

    def read_buttons(self) -> int:
        return self._button_mask()


class Emulator:
    """Everything `--simulate` swaps in for hardware: board, buzzer and clock."""

    def __init__(self, display: DisplayConfig) -> None:
        self.clock = SimClock()
        self.buzzer = SimBuzzer()
        self._lock = threading.Lock()
        self._pressed = set()
        self._down_at = {}
        self.chip: Optional[FakeChip] = None

        if importlib.util.find_spec("rpi_TM1638") is not None:
            self.chip = FakeChip(display.dio, display.clk, display.stb)
            self.chip.key_source = self._key_bytes
            install_fake_gpio(self.chip)
            self.backend = TM1638Backend(display.dio, display.clk, display.stb,
                                         display.brightness)
            log.info("emulating the TM1638 chip behind the real rpi_TM1638 library")
        else:
            self.backend = _SimBoard(self.button_mask)
            log.info("rpi_TM1638 is not installed: emulating a plain in-memory board")

    @property
    def wire_level(self) -> bool:
        return self.chip is not None

    def set_button(self, button: int, down: bool) -> None:
        with self._lock:
            if down:
                self._pressed.add(button)
                self._down_at[button] = time.monotonic()
            else:
                self._pressed.discard(button)

    def button_mask(self) -> int:
        """Buttons held now, or pressed so recently that the press still counts."""
        now = time.monotonic()
        mask = 0
        with self._lock:
            for button, since in list(self._down_at.items()):
                if button in self._pressed or now - since < MIN_PRESS_SECONDS:
                    mask |= 1 << button
                else:
                    del self._down_at[button]
        return mask

    def _key_bytes(self) -> List[int]:
        mask = self.button_mask()
        keys = [0, 0, 0, 0]
        for n in range(WIDTH):
            if mask & (1 << n):
                keys[n % 4] |= 0x01 if n < 4 else 0x10
        return keys

    def state(self) -> dict:
        if self.chip is not None:
            lit = self.chip.display_on
            segments = self.chip.memory[0::2] if lit else [0] * WIDTH
            leds = self.chip.memory[1::2] if lit else [0] * WIDTH
            brightness = self.chip.brightness
        else:
            segments, leds = self.backend.segments, self.backend.leds
            brightness = self.backend.brightness
        mask = self.button_mask()
        return {
            "segments": list(segments),
            "leds": list(leds),
            "brightness": brightness,
            "held": [n for n in range(WIDTH) if mask & (1 << n)],
            "buzzer": self.buzzer.on,
            "time": self.clock.now().strftime("%H:%M:%S"),
            "time_shifted": bool(self.clock.offset),
            "wire_level": self.wire_level,
        }
