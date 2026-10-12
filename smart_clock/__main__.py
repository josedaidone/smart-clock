"""Command line: python -m smart_clock run | hash-password | hwtest"""

from __future__ import annotations

import argparse
import getpass
import logging
import signal
import sys
import threading
from pathlib import Path

from . import font
from .buzzer import GpioBuzzer, NullBuzzer
from .config import Config, ConfigError, load_config
from .display import Display, SimBackend, TM1638Backend
from .engine import SmartClock

log = logging.getLogger("smart_clock")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m smart_clock")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run the clock and its web control")
    run.add_argument("--config", default="config.toml")
    run.add_argument("--simulate", action="store_true",
                     help="no hardware: draw the display in the terminal")
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
    if args.simulate and not Path(args.config).exists():
        log.info("%s not found, simulating with default settings", args.config)
        config = Config()
    else:
        config = load_config(args.config)

    if args.simulate:
        display = Display(SimBackend(), config.display.brightness,
                          config.display.led_color,
                          on_change=_terminal_painter() if sys.stdout.isatty() else None)
        buzzer = NullBuzzer()
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

    clock = SmartClock(config, display, buzzer=buzzer, weather=weather)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: clock.stop())

    if config.web.enabled and not args.no_web:
        _start_web(clock, config)

    clock.run()
    return 0


def _start_web(clock: SmartClock, config: Config) -> None:
    if not config.web.users:
        log.warning(
            "web control is OFF: no users in [web.users]. "
            "Run `python -m smart_clock hash-password` and add the line it prints."
        )
        return
    from .web import create_app, serve

    app = create_app(clock, config)
    thread = threading.Thread(
        target=serve, args=(app, config.web.host, config.web.port),
        name="web", daemon=True,
    )
    thread.start()
    log.info("web control on http://%s:%d", config.web.host, config.web.port)


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
