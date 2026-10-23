"""The web control: logins, the old holes staying closed, and the API."""

import base64
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

from smart_clock.config import parse_config
from smart_clock.web import MAX_FAILED_LOGINS, create_app

PASSWORD = "correct horse battery"
PACKAGE = Path(__file__).resolve().parents[1] / "smart_clock"


class StubClock:
    def __init__(self):
        self.messages = []
        self.calls = []
        self.accept = True

    def submit(self, text, duration=None):
        if not self.accept:
            return False
        self.messages.append((text, duration))
        return True

    def dismiss(self):
        self.calls.append("dismiss")

    def set_power(self, on):
        self.calls.append(("power", on))

    def set_brightness(self, level):
        self.calls.append(("brightness", level))

    def status(self):
        return {"display_on": True, "brightness": 5, "segments": [0] * 8,
                "leds": [0] * 8, "message": None, "alarm": False, "queued": 0,
                "weather": None, "time": "12:00:00"}


def basic(user="jose", password=PASSWORD):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture(scope="module")
def password_hash():
    return generate_password_hash(PASSWORD)


@pytest.fixture
def clock():
    return StubClock()


@pytest.fixture
def client(clock, password_hash):
    config = parse_config({"web": {"users": {"jose": password_hash}},
                           "messages": {"max_length": 50}})
    return create_app(clock, config).test_client()


# ------------------------------------------------------------------ logins
@pytest.mark.parametrize("method, path", [
    ("get", "/"), ("get", "/app.js"), ("get", "/api/status"),
    ("post", "/api/message"), ("post", "/api/display"), ("post", "/msg/"),
])
def test_everything_needs_a_login(client, clock, method, path):
    response = getattr(client, method)(path, json={"text": "x", "msg": "x", "on": False}
                                       if method == "post" else None)
    assert response.status_code == 401
    assert "Basic" in response.headers["WWW-Authenticate"]
    assert clock.messages == [] and clock.calls == []


def test_wrong_password_and_unknown_user_are_refused(client):
    assert client.get("/api/status", headers=basic(password="nope")).status_code == 401
    assert client.get("/api/status", headers=basic(user="root")).status_code == 401


def test_repeated_wrong_passwords_lock_that_address_out(client):
    for _ in range(MAX_FAILED_LOGINS):
        assert client.get("/api/status", headers=basic(password="guess")).status_code == 401
    assert client.get("/api/status", headers=basic()).status_code == 429


def test_page_loads_with_a_strict_content_security_policy(client):
    with client.get("/", headers=basic()) as response:
        assert response.status_code == 200 and b"Smart Clock" in response.data
        assert response.headers["Content-Security-Policy"].startswith("default-src 'self'")
    for asset in ("/app.js", "/style.css"):
        with client.get(asset, headers=basic()) as response:
            assert response.status_code == 200


# --------------------------------------------- the old holes stay closed
def test_shell_metacharacters_are_just_text(client, clock):
    payload = '"; touch /tmp/pwned; echo "'
    response = client.post("/api/message", json={"text": payload}, headers=basic())
    assert response.status_code == 200
    assert clock.messages == [(payload, None)]
    assert response.is_json  # echoed back as JSON, never as an HTML page


def test_nothing_shells_out_or_runs_in_debug_mode():
    source = "\n".join(path.read_text() for path in PACKAGE.rglob("*.py"))
    for forbidden in ("os.system", "subprocess", "shell=True", "debug=True"):
        assert forbidden not in source, forbidden


@pytest.mark.parametrize("path", ["/text/hello", "/start/", "/stop/"])
def test_old_get_endpoints_are_gone(client, clock, path):
    assert client.get(path, headers=basic()).status_code == 404
    assert clock.messages == [] and clock.calls == []


def test_changing_state_with_get_is_not_possible(client, clock):
    for path in ("/api/message", "/api/display", "/api/dismiss", "/api/brightness", "/msg/"):
        assert client.get(path, headers=basic()).status_code == 405
    assert clock.messages == [] and clock.calls == []


def test_form_posts_from_other_sites_are_refused(client, clock):
    # What a hidden <form> on a malicious page can send: no JSON content type.
    form = client.post("/api/message", data={"text": "x"}, headers=basic())
    text = client.post("/api/message", data='{"text": "x"}', content_type="text/plain",
                       headers=basic())
    assert form.status_code == 415 and text.status_code == 415
    assert clock.messages == []


def test_cross_origin_json_is_refused_but_same_origin_is_fine(client, clock):
    evil = client.post("/api/message", json={"text": "x"},
                       headers={**basic(), "Origin": "http://evil.example"})
    assert evil.status_code == 403 and clock.messages == []
    own = client.post("/api/message", json={"text": "x"},
                      headers={**basic(), "Origin": "http://localhost"})
    assert own.status_code == 200


# ------------------------------------------------------------------- API
def test_message_validation(client, clock):
    post = lambda body: client.post("/api/message", json=body, headers=basic())
    assert post({"text": "  oi linda  ", "duration": 30}).status_code == 200
    assert clock.messages == [("oi linda", 30)]
    assert post({}).status_code == 400
    assert post({"text": "   "}).status_code == 400
    assert post({"text": 42}).status_code == 400
    assert post({"text": "x" * 51}).status_code == 400
    assert post({"text": "x", "duration": 0}).status_code == 400
    assert post({"text": "x", "duration": "long"}).status_code == 400
    assert len(clock.messages) == 1


def test_full_queue_is_reported(client, clock):
    clock.accept = False
    response = client.post("/api/message", json={"text": "x"}, headers=basic())
    assert response.status_code == 429 and "error" in response.get_json()


def test_messages_are_rate_limited(client, clock):
    codes = [client.post("/api/message", json={"text": "x"}, headers=basic()).status_code
             for _ in range(25)]
    assert codes[:20] == [200] * 20 and set(codes[20:]) == {429}
    assert len(clock.messages) == 20


def test_legacy_msg_endpoint_still_accepts_the_old_json(client, clock):
    response = client.post("/msg/", json={"msg": "oi"}, headers=basic())
    assert response.status_code == 200 and clock.messages == [("oi", None)]


def test_display_brightness_and_dismiss(client, clock):
    post = lambda path, body: client.post(path, json=body, headers=basic())
    assert post("/api/display", {"on": False}).get_json() == {"display_on": False}
    assert post("/api/display", {"on": "yes"}).status_code == 400
    assert post("/api/brightness", {"level": 3}).status_code == 200
    assert post("/api/brightness", {"level": 8}).status_code == 400
    assert post("/api/brightness", {"level": True}).status_code == 400
    assert post("/api/dismiss", {}).status_code == 200
    assert clock.calls == [("power", False), ("brightness", 3), "dismiss"]


def test_status_is_json_and_not_cached(client):
    response = client.get("/api/status", headers=basic())
    assert response.get_json()["segments"] == [0] * 8
    assert response.headers["Cache-Control"] == "no-store"
