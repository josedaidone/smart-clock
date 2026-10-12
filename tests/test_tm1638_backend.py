"""The real rpi_TM1638 library, driven through a fake GPIO that decodes the
bit-banged protocol the way the chip does.

This is as close to the board as a test can get without one. It is skipped
when rpi_TM1638 is not installed.
"""

import sys
import types

import pytest

from smart_clock.display import Display, TM1638Backend

DIO, CLK, STB = 17, 27, 22


class FakeChip:
    """Stands in for RPi.GPIO and for the TM1638 on the other end of the wires."""

    BCM, OUT, IN, PUD_UP = "BCM", "OUT", "IN", "PUD_UP"

    def __init__(self):
        self.reset()

    def reset(self):
        self.level = {}
        self.memory = [0] * 16       # even addresses: digits, odd: LEDs
        self.keys = [0, 0, 0, 0]     # what a key scan returns
        self.display_on = False
        self.brightness = None
        self.fixed_address = False
        self._begin()

    # ---- RPi.GPIO surface
    def setwarnings(self, flag):
        pass

    def setmode(self, mode):
        assert mode == self.BCM

    def setup(self, pin, direction, pull_up_down=None):
        pass

    def output(self, pin, value):
        value = bool(value)
        before = self.level.get(pin)
        self.level[pin] = value
        if pin == STB:
            if before is not False and value is False:
                self._begin()
        elif pin == CLK and self.level.get(STB) is False:
            if value and before is False and not self.reading:
                self._clock_in(self.level.get(DIO, False))
            elif not value and before and self.reading:
                self._clock_out()

    def input(self, pin):
        assert pin == DIO
        return self.read_level

    # ---- the chip
    def _begin(self):
        self.bits = []
        self.reading = False
        self.address = None
        self.read_position = 0
        self.read_level = False

    def _clock_in(self, bit):
        self.bits.append(bit)
        if len(self.bits) == 8:
            byte = sum(1 << i for i, b in enumerate(self.bits) if b)  # LSB first
            self.bits = []
            self._byte(byte)

    def _clock_out(self):
        byte, bit = divmod(self.read_position, 8)
        self.read_level = bool(self.keys[byte] >> bit & 1)
        self.read_position += 1

    def _byte(self, byte):
        if self.address is not None:            # data following an address command
            self.memory[self.address] = byte
            if not self.fixed_address:
                self.address = (self.address + 1) % 16
        elif byte & 0xC0 == 0x40:               # data command
            self.reading = bool(byte & 0x02)
            self.fixed_address = bool(byte & 0x04)
        elif byte & 0xC0 == 0xC0:               # address command
            self.address = byte & 0x0F
        elif byte & 0xC0 == 0x80:               # display control
            self.display_on = bool(byte & 0x08)
            self.brightness = byte & 0x07


@pytest.fixture(scope="module")
def chip():
    fake = FakeChip()
    module = types.ModuleType("RPi.GPIO")
    for name in ("BCM", "OUT", "IN", "PUD_UP", "setwarnings", "setmode", "setup",
                 "output", "input"):
        setattr(module, name, getattr(fake, name))
    package = types.ModuleType("RPi")
    package.GPIO = module
    saved = {name: sys.modules.get(name) for name in ("RPi", "RPi.GPIO")}
    for name in list(sys.modules):
        if name.startswith("rpi_TM1638"):
            del sys.modules[name]
    sys.modules["RPi"], sys.modules["RPi.GPIO"] = package, module
    pytest.importorskip("rpi_TM1638")
    yield fake
    for name, original in saved.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


@pytest.fixture
def display(chip):
    chip.reset()
    return Display(TM1638Backend(DIO, CLK, STB, 5), brightness=5)


def digits(chip):
    return chip.memory[0::2]


def leds(chip):
    return chip.memory[1::2]


def test_starts_on_at_the_configured_brightness_and_blank(chip, display):
    assert chip.display_on and chip.brightness == 5
    assert chip.memory == [0] * 16


def test_text_lands_on_the_digits_with_dots_merged(chip, display):
    display.show_text("12.5")
    assert digits(chip) == [0x06, 0x5B | 0x80, 0x6D, 0, 0, 0, 0, 0]
    assert leds(chip) == [0] * 8


def test_full_width_text_and_overlong_text_do_not_overflow(chip, display):
    display.show_text("12 00 05 and more")
    assert digits(chip) == [0x06, 0x5B, 0, 0x3F, 0x3F, 0, 0x3F, 0x6D]


def test_leds_red_and_green(chip, display):
    display.set_led(3, True)
    assert leds(chip) == [0, 0, 0, 1, 0, 0, 0, 0]
    chip.reset()
    green = Display(TM1638Backend(DIO, CLK, STB, 5), led_color="green")
    green.set_led(0, True)
    assert leds(chip)[0] == 2


def test_same_text_shows_again_after_a_clear(chip, display):
    # The library's own text cache goes stale after clearDisplay(); ours must not.
    display.show_text("8")
    display.clear()
    assert chip.memory == [0] * 16
    display.show_text("8")
    assert digits(chip)[0] == 0x7F


def test_brightness_and_off(chip, display):
    display.set_brightness(2)
    assert chip.brightness == 2 and chip.display_on
    display.show_text("12 00 05")
    display.set_led(0, True)
    display.set_power(False)
    assert chip.memory == [0] * 16   # dark, but the controller (and buttons) stay alive
    display.show_text("ignored while off")
    assert chip.memory == [0] * 16
    display.set_power(True)
    display.show_text("oi")
    assert digits(chip)[:2] != [0, 0]


def test_buttons_including_two_held_at_once(chip, display):
    assert display.read_buttons() == 0
    chip.keys = [0x11, 0x00, 0x00, 0x10]          # S1 + S5 share a byte; S8
    assert display.read_buttons() == (1 << 0) | (1 << 4) | (1 << 7)
    chip.keys = [0x00, 0x01, 0x10, 0x00]          # S2, S7
    assert display.read_buttons() == (1 << 1) | (1 << 6)
    display.show_text("still ok")                 # writing still works after a read
    assert digits(chip)[0] != 0
