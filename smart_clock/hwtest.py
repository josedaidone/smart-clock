"""Wiring check: lights everything, then reports button presses.

Replaces the old one-off scripts (control.py, plaquinha.py, teste.py).
Stop the clock service first; two programs can't share the board.
"""

from __future__ import annotations

import time

from .config import Config
from .display import WIDTH, Display, TM1638Backend


def run_hwtest(config: Config) -> int:
    d = config.display
    display = Display(TM1638Backend(d.dio, d.clk, d.stb, d.brightness),
                      d.brightness, d.led_color)
    try:
        print("All segments and LEDs on for 2 seconds...")
        display.show_text("8.8.8.8.8.8.8.8.")
        display.set_leds(True)
        time.sleep(2)

        print("Brightness 0 to 7...")
        for level in range(8):
            display.set_brightness(level)
            display.show_text(f"bright {level}")
            time.sleep(0.4)
        display.set_brightness(d.brightness)
        display.set_leds(False)

        if config.buzzer.enabled:
            from .buzzer import GpioBuzzer

            print(f"Buzzer on GPIO {config.buzzer.pin} for 1 second...")
            buzzer = GpioBuzzer(config.buzzer.pin)
            buzzer.start()
            time.sleep(1)
            buzzer.stop()

        print("Press the buttons (S1-S8); each should light its LED. 15 seconds...")
        display.show_text("buttons")
        seen = 0
        end = time.monotonic() + 15
        while time.monotonic() < end:
            mask = display.read_buttons()
            for n in range(WIDTH):
                display.set_led(n, bool(mask & (1 << n)))
            for n in range(WIDTH):
                if mask & ~seen & (1 << n):
                    print(f"  S{n + 1} works")
            seen |= mask
            time.sleep(0.05)
        missing = [f"S{n + 1}" for n in range(WIDTH) if not seen & (1 << n)]
        print("Not pressed: " + ", ".join(missing) if missing else "All 8 buttons seen.")
    finally:
        display.clear()
    return 0
