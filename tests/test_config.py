import datetime as dt
from pathlib import Path

import pytest

from smart_clock.config import Config, ConfigError, load_config, parse_config

ROOT = Path(__file__).resolve().parents[1]


def test_example_config_loads_and_keeps_the_original_two_messages():
    config = load_config(ROOT / "config.example.toml")
    assert [(e.time, e.duration) for e in config.schedule] == [
        (dt.time(19, 0), 60.0), (dt.time(20, 0), 60.0),
    ]
    assert config.display.dio == 17 and config.display.clk == 27 and config.display.stb == 22
    assert config.web.users == {}


def test_empty_config_is_a_plain_clock():
    config = parse_config({})
    assert config == Config()
    assert config.dimming.enabled is False and config.schedule == []


def test_missing_file_says_what_to_do(tmp_path):
    with pytest.raises(ConfigError, match="config.example.toml"):
        load_config(tmp_path / "config.toml")


@pytest.mark.parametrize("data, hint", [
    ({"display": {"brightnes": 3}}, "unknown setting"),
    ({"dispaly": {}}, "unknown section"),
    ({"display": {"brightness": 9}}, "0 to 7"),
    ({"display": {"brightness": True}}, "0 to 7"),
    ({"dimming": {"night_start": "25:00"}}, "19:00"),
    ({"schedule": [{"time": "19:00"}]}, "time and text"),
    ({"schedule": [{"time": "19:00", "text": "x", "days": ["funday"]}]}, "unknown day"),
    ({"web": {"users": {"jose": "hunter2"}}}, "hash-password"),
])
def test_mistakes_are_rejected_with_a_pointer(data, hint):
    with pytest.raises(ConfigError, match=hint):
        parse_config(data)


def test_schedule_days_and_matching():
    config = parse_config({"schedule": [
        {"time": "07:30", "text": "bom dia", "days": ["Mon", "friday"], "alarm": True},
    ]})
    entry = config.schedule[0]
    assert entry.alarm and entry.days == frozenset({0, 4})
    assert entry.matches(dt.datetime(2026, 1, 5, 7, 30, 12))      # Monday
    assert not entry.matches(dt.datetime(2026, 1, 6, 7, 30))      # Tuesday
    assert not entry.matches(dt.datetime(2026, 1, 5, 7, 31))


def test_night_window_wraps_past_midnight():
    dimming = parse_config({"dimming": {"night_start": "22:00", "night_end": "07:00"}}).dimming
    assert dimming.is_night(dt.time(23, 0))
    assert dimming.is_night(dt.time(3, 0))
    assert not dimming.is_night(dt.time(7, 0))
    assert not dimming.is_night(dt.time(12, 0))
