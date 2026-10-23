"""The real rpi_TM1638 library, driven through a fake GPIO that decodes the
bit-banged protocol the way the chip does (smart_clock.emulator.FakeChip).

This is as close to the board as a test can get without one. It is skipped
when rpi_TM1638 is not installed.
"""

import importlib.util
import sys

import pytest

from smart_clock.display import Display, TM1638Backend
from smart_clock.emulator import FakeChip, install_fake_gpio

DIO, CLK, STB = 17, 27, 22


@pytest.fixture(scope="module")
def chip():
    if importlib.util.find_spec("rpi_TM1638") is None:
        pytest.skip("rpi_TM1638 is not installed")
    saved = {name: sys.modules.get(name) for name in ("RPi", "RPi.GPIO")}
    fake = FakeChip(DIO, CLK, STB)
    install_fake_gpio(fake)
    yield fake
    for name, original in saved.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


@pytest.fixture
def display(chip):
    chip.reset()
    install_fake_gpio(chip)   # another test may have pointed the library elsewhere
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
