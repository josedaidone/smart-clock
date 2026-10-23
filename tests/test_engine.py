"""The clock loop, run against the simulated board with a fake clock."""

import datetime as dt

from conftest import MONDAY_NOON, Rig, cells

from smart_clock import font
from smart_clock.config import parse_config
from smart_clock.engine import (BUTTON_BRIGHTER, BUTTON_DIMMER, BUTTON_DISMISS,
                                BUTTON_PAGE, BUTTON_POWER, BUTTON_REPLAY,
                                BUTTON_SNOOZE)

BLANK = [0] * 8
LONG = "ja sao oito - hora de comer biscoito"


def count_plays(rig):
    played = []
    original = rig.engine._play

    def spy(message):
        played.append(message.text)
        original(message)

    rig.engine._play = spy
    return played


def test_shows_every_second_without_skipping(rig):
    rig.run(10)
    seconds = [f"12 00 0{n}" for n in range(1, 10)]
    shown = [frame for frame in rig.history if frame in [cells(s) for s in seconds]]
    assert shown == [cells(s) for s in seconds]


def test_display_is_blank_after_stopping(rig):
    # The old daemon was killed mid-flight and left the last time frozen on screen.
    rig.run(3)
    assert cells("12 00 02") in rig.history
    assert rig.backend.segments == BLANK
    assert rig.backend.leds == BLANK


def test_long_message_scrolls_in_order_then_the_time_comes_back(rig):
    rig.engine.submit(LONG, duration=1)
    rig.snapshot(15.5)
    rig.run(17)
    frames = font.frames(LONG)
    scrolled = [frame for frame in rig.history if frame in frames]
    assert scrolled == frames
    assert rig.snapshots[15.5] == cells("12 00 15")


def test_message_stays_for_its_duration_even_across_a_minute_change():
    # Old behaviour: messages vanished whenever the minute rolled over.
    rig = Rig(start=dt.datetime(2026, 1, 5, 12, 0, 58))
    rig.engine.submit("hello", duration=10)
    rig.snapshot(8)
    rig.snapshot(14.5)
    rig.run(16)
    assert rig.snapshots[8] == cells("hello")
    assert rig.snapshots[14.5] == cells("12 01 12")


def test_odd_characters_do_not_crash_the_clock(rig):
    text = "olá ✨ #1!"
    rig.engine.submit(text, duration=2)
    rig.run(8)
    assert font.frames(text)[0] in rig.history


def test_queue_is_bounded():
    rig = Rig(parse_config({"messages": {"max_queue": 2}}))
    assert rig.engine.submit("one")
    assert rig.engine.submit("two")
    assert not rig.engine.submit("three")


def test_scheduled_message_fires_once_at_its_minute():
    config = parse_config({"schedule": [{"time": "19:00", "text": "sete horas", "duration": 5}]})
    rig = Rig(config, start=dt.datetime(2026, 1, 5, 18, 59, 50))
    played = count_plays(rig)
    rig.run(100)
    assert played == ["sete horas"]


def test_schedule_skips_other_days_and_the_minute_it_booted_in():
    config = parse_config({"schedule": [
        {"time": "12:00", "text": "already this minute"},
        {"time": "12:01", "text": "tuesdays only", "days": ["tue"]},
    ]})
    rig = Rig(config, start=MONDAY_NOON)
    played = count_plays(rig)
    rig.run(90)
    assert played == []


def test_turning_the_display_off_blanks_it_and_a_message_wakes_it(rig):
    state = {}
    rig.at(2, lambda: rig.engine.set_power(False))
    rig.snapshot(3)
    rig.at(3, lambda: state.update(off=rig.display.powered))
    rig.at(4, lambda: rig.engine.submit("hi", duration=3))
    rig.snapshot(7)
    rig.snapshot(10.5)
    rig.run(12)
    assert rig.snapshots[3] == BLANK and state["off"] is False
    assert rig.snapshots[7] == cells("hi")
    assert rig.snapshots[10.5] == cells("12 00 10")


def test_turning_off_drops_the_current_and_waiting_messages(rig):
    rig.engine.submit(LONG, duration=60)
    rig.engine.submit("next", duration=60)
    rig.at(5, lambda: rig.engine.set_power(False))
    rig.snapshot(6)
    rig.at(6, lambda: rig.snapshots.update(status=rig.engine.status()))
    rig.run(8)
    assert rig.snapshots[6] == BLANK
    status = rig.snapshots["status"]
    assert status["message"] is None and status["queued"] == 0
    assert status["display_on"] is False


def test_power_button_toggles_the_display(rig):
    rig.tap(2, BUTTON_POWER)
    rig.snapshot(3)
    rig.tap(4, BUTTON_POWER)
    rig.snapshot(5.5)
    rig.run(7)
    assert rig.snapshots[3] == BLANK
    assert rig.snapshots[5.5] == cells("12 00 05")


def test_a_single_noisy_button_read_is_ignored(rig):
    state = {}
    rig.at(2, lambda: rig.backend.press(BUTTON_POWER))
    rig.at(2.04, rig.backend.release)          # visible to exactly one poll
    rig.at(3, lambda: state.update(powered=rig.display.powered))
    rig.run(4)
    assert state["powered"] is True


def test_buttons_can_be_switched_off_in_the_config():
    rig = Rig(parse_config({"display": {"buttons": False}}))
    state = {}
    rig.tap(2, BUTTON_POWER)
    rig.at(3, lambda: state.update(powered=rig.display.powered))
    rig.run(4)
    assert state["powered"] is True


def test_dismiss_button_ends_a_message_early(rig):
    rig.engine.submit(LONG, duration=60)
    rig.tap(5, BUTTON_DISMISS)
    rig.snapshot(7.5)
    rig.run(9)
    assert rig.snapshots[7.5] == cells("12 00 07")


def test_replay_button_shows_the_last_message_again(rig):
    played = count_plays(rig)
    rig.engine.submit("hi", duration=2)
    rig.tap(6, BUTTON_REPLAY)
    rig.run(12)
    assert played == ["hi", "hi"]


def test_page_button_shows_the_date_then_falls_back_to_the_time(rig):
    rig.tap(1, BUTTON_PAGE)
    rig.snapshot(2.5)
    rig.snapshot(13.5)
    rig.run(15)
    assert rig.snapshots[2.5] == cells("05-01-26")
    assert rig.snapshots[13.5] == cells("12 00 13")


def test_brightness_buttons_and_night_dimming():
    config = parse_config({"dimming": {
        "enabled": True, "night_start": "22:00", "night_end": "07:00", "night_brightness": 1,
    }})
    rig = Rig(config, start=dt.datetime(2026, 1, 5, 21, 59, 30))
    levels = {}
    rig.at(0.5, lambda: levels.update(day=rig.backend.brightness))
    rig.tap(1, BUTTON_BRIGHTER)
    rig.tap(2, BUTTON_BRIGHTER)
    rig.tap(3, BUTTON_DIMMER)
    rig.at(20, lambda: levels.update(manual=rig.backend.brightness))
    rig.at(35, lambda: levels.update(night=rig.backend.brightness))
    rig.run(40)
    assert levels == {"day": 5, "manual": 6, "night": 1}


def test_alarm_buzzes_snoozes_and_comes_back():
    config = parse_config({
        "schedule": [{"time": "07:00", "text": "acorda", "alarm": True}],
        "alarm": {"snooze_minutes": 1, "timeout": 120},
    })
    rig = Rig(config, start=dt.datetime(2026, 1, 5, 6, 59, 55))
    seen = {}
    rig.at(8, lambda: seen.update(ringing=rig.buzzer.on))
    rig.tap(10, BUTTON_SNOOZE)
    rig.at(12, lambda: seen.update(snoozed=rig.buzzer.on))
    rig.snapshot(12.5)
    rig.at(75, lambda: seen.update(back=rig.buzzer.on))
    rig.tap(80, BUTTON_DISMISS)
    rig.at(85, lambda: seen.update(dismissed=rig.buzzer.on))
    rig.run(200)
    assert seen == {"ringing": True, "snoozed": False, "back": True, "dismissed": False}
    assert rig.snapshots[12.5] == cells("07 00 07")
    assert rig.buzzer.starts == 2 and rig.buzzer.on is False


def test_alarm_wakes_a_dark_display_and_turns_it_off_again_afterwards():
    config = parse_config({
        "schedule": [
            {"time": "07:00", "text": "acorda", "alarm": True},
            {"time": "07:00", "text": "not an alarm"},
        ],
        "alarm": {"timeout": 5},
    })
    rig = Rig(config, start=dt.datetime(2026, 1, 5, 6, 59, 55))
    played = count_plays(rig)
    seen = {}
    rig.at(1, lambda: rig.engine.set_power(False))
    rig.at(9, lambda: seen.update(during=(rig.display.powered, rig.buzzer.on)))
    rig.at(25, lambda: seen.update(after=(rig.display.powered, rig.buzzer.on)))
    rig.snapshot(25)
    rig.run(30)
    assert played == ["acorda"]  # the plain message stays quiet while the display is off
    assert seen == {"during": (True, True), "after": (False, False)}
    assert rig.snapshots[25] == BLANK


def test_weather_page_rotates_in_and_out():
    class StubWeather:
        def text(self):
            return "23.5°C"

    rig = Rig(start=dt.datetime(2026, 1, 5, 12, 0, 25), weather=StubWeather())
    rig.snapshot(6.5)
    rig.snapshot(10.5)
    rig.at(10.5, lambda: rig.snapshots.update(status=rig.engine.status()))
    rig.run(12)
    assert rig.snapshots[6.5] == font.centered("23.5°C")
    assert rig.snapshots[10.5] == cells("12 00 35")
    assert rig.snapshots["status"]["weather"] == "23.5°C"
