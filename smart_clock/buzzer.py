"""Optional buzzer for alarms."""

from __future__ import annotations


class NullBuzzer:
    """Used when no buzzer is configured."""

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class GpioBuzzer:
    """An active buzzer on a GPIO pin (same wiring the old teste.py used)."""

    def __init__(self, pin: int) -> None:
        from gpiozero import Buzzer

        self._buzzer = Buzzer(pin)

    def start(self) -> None:
        # Beeps in a background thread until stop() is called.
        self._buzzer.beep(on_time=0.4, off_time=0.4)

    def stop(self) -> None:
        self._buzzer.off()
