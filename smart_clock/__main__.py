"""Command line: python -m smart_clock run | hash-password | hwtest"""

from __future__ import annotations

import argparse
import getpass
import logging
import secrets
import signal
import sys
import threading
from pathlib import Path

from . import font
from .buzzer import GpioBuzzer, NullBuzzer
from .config import Config, ConfigError, load_config
from .display import Display, TM1638Backend
from .engine import SmartClock

log = logging.getLogger("smart_clock")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m smart_clock")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run the clock and its web control")
    run.add_argument("--config", default="config.toml")
    run.add_argument("--simulate", action="store_true",
                     help="no hardware: emulate the board, with a page to control it")
    run.add_argument("--port", type=int, help="web port (overrides the config)")
    run.add_argument("--no-web", action="store_true", help="clock only")
    run.add_argument("--verbose", action="store_true")

    hashpw = commands.add_parser("hash-password",
                                 help="make a password line for [web.users]")
    hashpw.add_argument("--user", default="you")

    hwtest = commands.add_parser("hwtest", help="check the board's wiring")
    hwtest.add_argument("--config", default="config.toml")

    args = parser.parse_args(argv)
    try:
        if args.command == "hash-password":
            return _hash_password(args.user)
        if args.command == "hwtest":
            from .hwtest import run_hwtest
            return run_hwtest(load_config(args.config))
        return _run(args)
    except ConfigError as exc:
        print(f"Config problem: {exc}", file=sys.stderr)
        return 2


def _run(args) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("waitress").setLevel(logging.WARNING)
    config = _load_config(args)
    if args.port:
        config.web.port = args.port
    use_web = config.web.enabled and not args.no_web

    emulator = None
    engine_clock = None
    if args.simulate:
        from .emulator import Emulator

        emulator = Emulator(config.display)
        draw_in_terminal = not use_web and sys.stdout.isatty()
        display = Display(emulator.backend, config.display.brightness,
                          config.display.led_color,
                          on_change=_terminal_painter() if draw_in_terminal else None)
        buzzer = emulator.buzzer
        engine_clock = emulator.clock
    else:
        d = config.display
        display = Display(TM1638Backend(d.dio, d.clk, d.stb, d.brightness),
                          d.brightness, d.led_color)
        buzzer = GpioBuzzer(config.buzzer.pin) if config.buzzer.enabled else NullBuzzer()

    weather = None
    if config.weather.enabled:
        from .weather import Weather
        weather = Weather(config.weather.latitude, config.weather.longitude,
                          config.weather.unit)
        weather.start()

    clock = SmartClock(config, display, buzzer=buzzer, weather=weather, clock=engine_clock)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: clock.stop())

    if use_web and not _start_web(clock, config, emulator) and emulator is not None:
        return 1  # the emulator is its page; no point running without it

    clock.run()
    return 0


def _load_config(args) -> Config:
    if not args.simulate or Path(args.config).exists():
        return load_config(args.config)
    # Trying it out without a config.toml: use the example so there is a schedule.
    example = Path(__file__).resolve().parent.parent / "config.example.toml"
    if example.exists():
        log.info("%s not found, using %s", args.config, example.name)
        return load_config(example)
    log.info("%s not found, using default settings", args.config)
    return Config()


def _start_web(clock: SmartClock, config: Config, emulator=None) -> bool:
    """Start the web control in the background. Returns False if it is not running."""
    login = None
    if emulator is not None and not config.web.users:
        # Nothing real is being controlled, so make up a login for this run
        # and keep it on this computer only.
        from werkzeug.security import generate_password_hash

        login = ("demo", secrets.token_urlsafe(6))
        config.web.users = {login[0]: generate_password_hash(login[1])}
        config.web.host = "127.0.0.1"
    if not config.web.users:
        log.warning(
            "web control is OFF: no users in [web.users]. "
            "Run `python -m smart_clock hash-password` and add the line it prints."
        )
        return False
    from .web import create_app, make_server

    app = create_app(clock, config, emulator=emulator)
    try:
        server = make_server(app, config.web.host, config.web.port)
    except OSError as exc:
        log.error("web control could not start on %s:%d (%s). "
                  "Is something else using the port? Try --port 8080.",
                  config.web.host, config.web.port, exc)
        return False
    threading.Thread(target=server.run, name="web", daemon=True).start()
    shown_host = "127.0.0.1" if config.web.host in ("0.0.0.0", "::") else config.web.host
    base = f"http://{shown_host}:{config.web.port}"
    log.info("web control on %s", base)
    if emulator is not None:
        print(f"\n  Emulator:  {base}/emulator")
        if login:
            print(f"  Login:     {login[0]} / {login[1]}   (made up for this run)")
        print("  Stop with Ctrl+C\n", flush=True)
    return True


def _hash_password(user: str) -> int:
    from werkzeug.security import generate_password_hash

    try:
        first = getpass.getpass("Password: ")
        if len(first) < 8:
            print("Use at least 8 characters.", file=sys.stderr)
            return 1
        if first != getpass.getpass("Again: "):
            print("The two entries did not match.", file=sys.stderr)
            return 1
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.", file=sys.stderr)
        return 1
    print("\nAdd this line under [web.users] in config.toml:\n")
    print(f'{user} = "{generate_password_hash(first)}"')
    return 0


def _terminal_painter():
    """Redraw the simulated display in place, four lines tall."""
    fresh = [True]
    lock = threading.Lock()

    def start_fresh_after_log_line(record) -> bool:
        fresh[0] = True  # a log line was printed; draw below it, not over it
        return True

    for handler in logging.getLogger().handlers:
        handler.addFilter(start_fresh_after_log_line)

    def paint(display: Display) -> None:
        lines = font.render_ascii(display.segments)
        lines.append(" ".join(" o " if led else " . " for led in display.leds))
        with lock:
            if not fresh[0]:
                sys.stdout.write("\x1b[4A")
            fresh[0] = False
            sys.stdout.write("".join(f"\x1b[2K{line}\n" for line in lines))
            sys.stdout.flush()

    return paint


if __name__ == "__main__":
    sys.exit(main())
