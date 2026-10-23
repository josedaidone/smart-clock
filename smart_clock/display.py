"""The one place that talks to the TM1638 board.

`Display` is what the rest of the program uses. It sits on a backend:
`TM1638Backend` for the real board, `SimBackend` for running without one.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence

from . import font

WIDTH = font.WIDTH
MAX_BRIGHTNESS = 7


class SimBackend:
    """In-memory stand-in for the board (tests and --simulate)."""

    def __init__(self) -> None:
        self.segments = [0] * WIDTH
        self.leds = [0] * WIDTH
        self.brightness: Optional[int] = None
        self.buttons = 0
        self.writes = 0

    def write_segment(self, pos: int, bits: int) -> None:
        self.segments[pos] = bits
        self.writes += 1

    def write_led(self, pos: int, value: int) -> None:
        self.leds[pos] = value
        self.writes += 1

    def clear(self) -> None:
        self.segments = [0] * WIDTH
        self.leds = [0] * WIDTH

    def set_brightness(self, level: int) -> None:
        self.brightness = level

    def read_buttons(self) -> int:
        return self.buttons

    # Test helpers ---------------------------------------------------------
    def press(self, *buttons: int) -> None:
        for button in buttons:
            self.buttons |= 1 << button

    def release(self) -> None:
        self.buttons = 0


class TM1638Backend:
    """Real board, driven through the rpi_TM1638 library."""

    def __init__(self, dio: int, clk: int, stb: int, brightness: int) -> None:
        # Imported here so everything else works on a machine without GPIO.
        from rpi_TM1638 import TMBoards

        self._tm = TMBoards(dio, clk, [stb], brightness)

    def write_segment(self, pos: int, bits: int) -> None:
        # Digits live at the even addresses.
        self._tm.sendData(pos * 2, bits, 0)

    def write_led(self, pos: int, value: int) -> None:
        # LEDs live at the odd addresses: 1 = red, 2 = green (bicolour boards).
        self._tm.sendData(pos * 2 + 1, value, 0)

    def clear(self) -> None:
        self._tm.clearDisplay()

    def set_brightness(self, level: int) -> None:
        self._tm.turnOn(level)

    def read_buttons(self) -> int:
        # Four bytes come back; button n is bit 0 (S1-S4) or bit 4 (S5-S8)
        # of byte n % 4. Reading the bits (not comparing the whole byte)
        # keeps two buttons held together from cancelling each other out.
        data = self._tm.getData(0)
        mask = 0
        for n in range(WIDTH):
            if data[n % 4] & (0x01 if n < 4 else 0x10):
                mask |= 1 << n
        return mask


class Display:
    """Eight digits, eight LEDs, eight buttons.

    Only changed cells are sent to the board. "Off" blanks every segment
    rather than switching the controller off, so the buttons keep working
    and the power button can turn it back on.
    """

    def __init__(self, backend, brightness: int = 5, led_color: str = "red",
                 on_change: Optional[Callable[["Display"], None]] = None) -> None:
        self.backend = backend
        self._led_on = 2 if led_color == "green" else 1
        self.on_change = on_change
        self.powered = True
        self.brightness = _clamp(brightness)
        self.segments: List[int] = [0] * WIDTH
        self.leds: List[int] = [0] * WIDTH
        self.backend.clear()
        self.backend.set_brightness(self.brightness)

    def show(self, cells: Sequence[int]) -> None:
        """Put a frame of up to eight cells on the digits."""
        if not self.powered:
            return
        cells = list(cells)[:WIDTH]
        cells += [0] * (WIDTH - len(cells))
        changed = False
        for pos, bits in enumerate(cells):
            if self.segments[pos] != bits:
                self.backend.write_segment(pos, bits)
                self.segments[pos] = bits
                changed = True
        if changed:
            self._notify()

    def show_text(self, text: str) -> None:
        """Show the first eight cells of text, left aligned."""
        self.show(font.frames(text)[0])

    def set_led(self, pos: int, on: bool) -> None:
        if not self.powered:
            return
        value = self._led_on if on else 0
        if self.leds[pos] != value:
            self.backend.write_led(pos, value)
            self.leds[pos] = value
            self._notify()

    def set_leds(self, on: bool) -> None:
        for pos in range(WIDTH):
            self.set_led(pos, on)

    def clear(self) -> None:
        self.backend.clear()
        self.segments = [0] * WIDTH
        self.leds = [0] * WIDTH
        self._notify()

    def set_brightness(self, level: int) -> None:
        self.brightness = _clamp(level)
        self.backend.set_brightness(self.brightness)

    def set_power(self, on: bool) -> None:
        if on == self.powered:
            return
        if not on:
            self.clear()
        self.powered = on

    def read_buttons(self) -> int:
        """Bitmask of the buttons held right now (bit 0 = S1)."""
        return self.backend.read_buttons()

    def _notify(self) -> None:
        if self.on_change is not None:
            self.on_change(self)


def _clamp(level: int) -> int:
    return max(0, min(MAX_BRIGHTNESS, int(level)))
