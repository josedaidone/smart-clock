"""Web control for the clock.

Runs inside the clock's own process and calls it directly: no shell
commands, no sudo. Every route needs a login, anything that changes
state is a JSON POST, and requests from other websites are refused.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import logging
import time
from collections import deque
from pathlib import Path
from typing import Deque, Dict
from urllib.parse import urlsplit

from flask import Flask, jsonify, request, send_from_directory
from flask_httpauth import HTTPBasicAuth
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

from .config import Config

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
MAX_DURATION_SECONDS = 600
MAX_FAILED_LOGINS = 10          # per address ...
FAILED_LOGIN_WINDOW = 5 * 60    # ... within this many seconds


def create_app(clock, config: Config, emulator=None) -> Flask:
    """Build the web control. `emulator` is set only by `run --simulate`."""
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024

    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["120 per minute"],
        storage_uri="memory://",
    )
    message_limit = limiter.shared_limit("20 per minute", scope="message")
    status_limit = limiter.limit("180 per minute")  # the page polls once a second

    auth = HTTPBasicAuth(realm="smart-clock")
    users: Dict[str, str] = dict(config.web.users)
    verified: Dict[str, bytes] = {}
    decoy_hash = generate_password_hash("decoy")
    failures: Dict[str, Deque[float]] = {}

    def note_failure(username):
        if len(failures) > 1000:
            failures.clear()
        attempts = failures.setdefault(request.remote_addr, deque(maxlen=MAX_FAILED_LOGINS))
        attempts.append(time.monotonic())
        log.warning("failed login for %r from %s", username, request.remote_addr)

    @auth.verify_password
    def verify_password(username, password):
        if not username or not password:
            return None
        stored = users.get(username)
        if stored is None:
            check_password_hash(decoy_hash, password)  # same cost as a real check
            note_failure(username)
            return None
        # Password hashing is slow on purpose (and slower on a Pi), so remember
        # a digest of the password that passed instead of redoing it per request.
        digest = hashlib.sha256(password.encode("utf-8")).digest()
        known = verified.get(username)
        if known is not None and hmac.compare_digest(known, digest):
            return username
        if check_password_hash(stored, password):
            verified[username] = digest
            return username
        note_failure(username)
        return None

    @app.before_request
    def slow_down_password_guessing():
        attempts = failures.get(request.remote_addr)
        if not attempts:
            return None
        cutoff = time.monotonic() - FAILED_LOGIN_WINDOW
        while attempts and attempts[0] < cutoff:
            attempts.popleft()
        if len(attempts) >= MAX_FAILED_LOGINS:
            return _error(429, "too many failed logins, wait a few minutes")
        return None

    @app.before_request
    def refuse_cross_site_and_non_json():
        if request.method in SAFE_METHODS:
            return None
        origin = request.headers.get("Origin")
        if origin and urlsplit(origin).netloc != request.host:
            return _error(403, "cross-site requests are not allowed")
        if not request.is_json:
            return _error(415, "send JSON with Content-Type: application/json")
        return None

    @app.before_request
    @auth.login_required
    def require_login():
        return None

    @app.after_request
    def security_headers(response):
        # The emulator page shows the control page in a frame; nothing else may.
        framing = "'self'" if emulator is not None else "'none'"
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; frame-ancestors {framing}"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.path.startswith(("/api/", "/emulator/api/")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @auth.error_handler
    def unauthorized(status):
        return _error(status, "login required")

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return _error(exc.code, exc.description)

    # ---------------------------------------------------------------- pages
    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/app.js")
    def script():
        return send_from_directory(STATIC_DIR, "app.js")

    @app.get("/board.js")
    def board_script():
        return send_from_directory(STATIC_DIR, "board.js")

    @app.get("/style.css")
    def stylesheet():
        return send_from_directory(STATIC_DIR, "style.css")

    @app.get("/favicon.ico")
    def favicon():
        return "", 204

    # ------------------------------------------------------------------ API
    @app.get("/api/status")
    @status_limit
    def status():
        return jsonify(clock.status())

    def queue_message(text, duration=None):
        if not isinstance(text, str) or not text.strip():
            return _error(400, "text is required")
        text = text.strip()
        limit = config.messages.max_length
        if len(text) > limit:
            return _error(400, f"text is longer than {limit} characters")
        if duration is not None:
            if (isinstance(duration, bool) or not isinstance(duration, (int, float))
                    or not 1 <= duration <= MAX_DURATION_SECONDS):
                return _error(400, f"duration must be 1 to {MAX_DURATION_SECONDS} seconds")
        if not clock.submit(text, duration):
            return _error(429, "too many messages waiting, try again shortly")
        return jsonify({"queued": text})

    @app.post("/api/message")
    @message_limit
    def message():
        body = _body()
        return queue_message(body.get("text"), body.get("duration"))

    @app.post("/msg/")
    @message_limit
    def legacy_message():
        # Same shape the old endpoint accepted: {"msg": "..."}
        return queue_message(_body().get("msg"))

    @app.post("/api/display")
    def display():
        on = _body().get("on")
        if not isinstance(on, bool):
            return _error(400, "on must be true or false")
        clock.set_power(on)
        return jsonify({"display_on": on})

    @app.post("/api/brightness")
    def brightness():
        level = _body().get("level")
        if isinstance(level, bool) or not isinstance(level, int) or not 0 <= level <= 7:
            return _error(400, "level must be a whole number from 0 to 7")
        clock.set_brightness(level)
        return jsonify({"brightness": level})

    @app.post("/api/dismiss")
    def dismiss():
        clock.dismiss()
        return jsonify({"dismissed": True})

    if emulator is not None:
        _add_emulator_routes(app, limiter, config, emulator)
    return app


def _add_emulator_routes(app: Flask, limiter: Limiter, config: Config, emulator) -> None:
    """The emulated board: what it shows, its buttons and its clock."""

    @app.get("/emulator")
    def emulator_page():
        return send_from_directory(STATIC_DIR, "emulator.html")

    @app.get("/emulator.js")
    def emulator_script():
        return send_from_directory(STATIC_DIR, "emulator.js")

    @app.get("/emulator.css")
    def emulator_stylesheet():
        return send_from_directory(STATIC_DIR, "emulator.css")

    @app.get("/emulator/api/info")
    def emulator_info():
        dimming = config.dimming
        return jsonify({
            "wire_level": emulator.wire_level,
            "buttons_enabled": config.display.buttons,
            "schedule": [
                {"time": entry.time.strftime("%H:%M"), "text": entry.text,
                 "alarm": entry.alarm,
                 "days": sorted(entry.days) if entry.days is not None else None}
                for entry in config.schedule
            ],
            "night_start": dimming.night_start.strftime("%H:%M") if dimming.enabled else None,
        })

    @app.get("/emulator/api/state")
    @limiter.exempt  # the page redraws the board many times a second
    def emulator_state():
        return jsonify(emulator.state())

    @app.post("/emulator/api/button")
    @limiter.exempt
    def emulator_button():
        body = _body()
        button, down = body.get("button"), body.get("down")
        if isinstance(button, bool) or not isinstance(button, int) or not 0 <= button <= 7:
            return _error(400, "button must be 0 to 7")
        if not isinstance(down, bool):
            return _error(400, "down must be true or false")
        emulator.set_button(button, down)
        return jsonify({"button": button, "down": down})

    @app.post("/emulator/api/time")
    def emulator_time():
        body = _body()
        if body.get("reset") is True:
            emulator.clock.reset()
        else:
            try:
                parts = [int(part) for part in str(body.get("time", "")).split(":")]
                when = dt.time(*parts) if 2 <= len(parts) <= 3 else None
            except ValueError:
                when = None
            if when is None:
                return _error(400, 'time must look like "18:59:50"')
            emulator.clock.set_time(when)
        return jsonify({"time": emulator.clock.now().strftime("%H:%M:%S")})


def make_server(app: Flask, host: str, port: int):
    """A waitress server (production grade), bound now so a busy port fails loudly.

    Call .run() on the result to serve. Never Flask's debug server.
    """
    from waitress import create_server

    sockets: dict = {}
    try:
        return create_server(app, map=sockets, host=host, port=port, threads=4,
                             ident="smart-clock")
    except OSError:
        for half_open in list(sockets.values()):  # don't leave waitress's sockets behind
            half_open.close()
        raise


def _body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _error(code: int, message: str):
    return jsonify({"error": message}), code
