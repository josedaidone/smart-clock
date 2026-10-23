"""`run --simulate`: the emulated board, its buttons, its clock and its page."""

import base64
import datetime as dt
import importlib.util
import socket
import threading
import time

import pytest
from werkzeug.security import generate_password_hash

from smart_clock import font
from smart_clock.__main__ import main
from smart_clock.config import Config, parse_config
from smart_clock.display import Display
from smart_clock.emulator import MIN_PRESS_SECONDS, Emulator
from smart_clock.engine import BUTTON_POWER, SmartClock
from smart_clock.web import create_app

PASSWORD = "correct horse battery"
HAVE_LIBRARY = importlib.util.find_spec("rpi_TM1638") is not None


def basic():
    token = base64.b64encode(f"jose:{PASSWORD}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture(params=["wire-level", "in-memory"])
def emulator(request, monkeypatch):
    if request.param == "wire-level" and not HAVE_LIBRARY:
        pytest.skip("rpi_TM1638 is not installed")
    if request.param == "in-memory":
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    emulator = Emulator(Config().display)
    assert emulator.wire_level == (request.param == "wire-level")
    return emulator


def running(emulator, config=None):
    config = config or Config()
    display = Display(emulator.backend, config.display.brightness)
    engine = SmartClock(config, display, buzzer=emulator.buzzer, clock=emulator.clock)
    thread = threading.Thread(target=engine.run, daemon=True)
    thread.start()
    return engine, thread


def wait_for(condition, seconds=3.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_board_shows_what_the_clock_writes_and_buttons_reach_the_clock(emulator):
    emulator.clock.set_time(dt.time(12, 0, 0))
    engine, thread = running(emulator)
    try:
        assert wait_for(lambda: emulator.state()["segments"][:2] == font.encode("12"))
        assert emulator.state()["brightness"] == 5

        emulator.set_button(BUTTON_POWER, True)
        emulator.set_button(BUTTON_POWER, False)       # a quick click
        assert emulator.state()["held"] == [BUTTON_POWER]
        assert wait_for(lambda: emulator.state()["segments"] == [0] * 8)
        assert wait_for(lambda: emulator.state()["held"] == [])
    finally:
        engine.stop()
        thread.join(timeout=2)


def test_jumping_the_clock_fires_the_schedule_and_the_buzzer(emulator):
    config = parse_config({"schedule": [{"time": "07:00", "text": "acorda", "alarm": True}]})
    emulator.clock.set_time(dt.time(6, 59, 58))
    engine, thread = running(emulator, config)
    try:
        assert emulator.state()["time_shifted"] is True
        assert wait_for(lambda: emulator.state()["buzzer"], seconds=5)
        assert engine.status()["alarm"] is True
    finally:
        engine.stop()
        thread.join(timeout=2)
    assert emulator.state()["buzzer"] is False


def test_a_click_is_held_long_enough_to_register(emulator):
    emulator.set_button(3, True)
    emulator.set_button(3, False)
    assert emulator.button_mask() == 1 << 3
    time.sleep(MIN_PRESS_SECONDS + 0.05)
    assert emulator.button_mask() == 0


# ------------------------------------------------------------------- the page
class StubClock:
    def status(self):
        return {}


@pytest.fixture
def config():
    return parse_config({
        "web": {"users": {"jose": generate_password_hash(PASSWORD)}},
        "schedule": [{"time": "19:00", "text": "sete horas", "days": ["mon"]}],
        "dimming": {"enabled": True, "night_start": "22:00"},
    })


def test_emulator_routes_exist_only_when_simulating(config):
    plain = create_app(StubClock(), config).test_client()
    for path in ("/emulator", "/emulator.js", "/emulator/api/state"):
        assert plain.get(path, headers=basic()).status_code == 404
    assert plain.post("/emulator/api/button", json={"button": 0, "down": True},
                      headers=basic()).status_code == 404
    with plain.get("/", headers=basic()) as response:
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_emulator_page_and_api(config, emulator):
    client = create_app(StubClock(), config, emulator=emulator).test_client()
    assert client.get("/emulator").status_code == 401
    assert client.get("/emulator/api/state").status_code == 401
    for path in ("/emulator", "/emulator.js", "/emulator.css", "/board.js"):
        with client.get(path, headers=basic()) as response:
            assert response.status_code == 200
            # Only this site may frame the control page.
            assert "frame-ancestors 'self'" in response.headers["Content-Security-Policy"]

    info = client.get("/emulator/api/info", headers=basic()).get_json()
    assert info["schedule"] == [{"time": "19:00", "text": "sete horas", "alarm": False, "days": [0]}]
    assert info["night_start"] == "22:00" and info["wire_level"] == emulator.wire_level

    post = lambda path, body: client.post(path, json=body, headers=basic())
    assert post("/emulator/api/button", {"button": 4, "down": True}).status_code == 200
    assert client.get("/emulator/api/state", headers=basic()).get_json()["held"] == [4]
    assert post("/emulator/api/button", {"button": 8, "down": True}).status_code == 400
    assert post("/emulator/api/button", {"button": 1, "down": "yes"}).status_code == 400

    assert post("/emulator/api/time", {"time": "18:59:50"}).get_json()["time"].startswith("18:59:5")
    assert client.get("/emulator/api/state", headers=basic()).get_json()["time_shifted"] is True
    assert post("/emulator/api/time", {"time": "25:00"}).status_code == 400
    assert post("/emulator/api/time", {"time": "soon"}).status_code == 400
    assert post("/emulator/api/time", {"reset": True}).status_code == 200
    assert client.get("/emulator/api/state", headers=basic()).get_json()["time_shifted"] is False


def test_board_redraws_are_not_rate_limited(config, emulator):
    client = create_app(StubClock(), config, emulator=emulator).test_client()
    codes = {client.get("/emulator/api/state", headers=basic()).status_code for _ in range(300)}
    assert codes == {200}


def test_simulate_stops_with_a_clear_error_when_the_port_is_taken(tmp_path, caplog):
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        missing = tmp_path / "config.toml"
        assert main(["run", "--simulate", "--config", str(missing), "--port", str(port)]) == 1
    assert "--port" in caplog.text
