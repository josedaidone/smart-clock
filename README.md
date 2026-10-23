# smart-clock

A desk clock on a Raspberry Pi and a TM1638 "LED&KEY" board (8 digits, 8 LEDs, 8 buttons) that you can send messages to from your phone.

- Shows the time, and the date or outdoor temperature on request
- Scrolls messages sent from a small web page or a JSON API
- Shows messages on a schedule ("sete horas…" at 19:00)
- Alarms with snooze, and a buzzer if you have one
- Dims itself at night
- Uses the board's eight buttons

It runs as one Python 3 service. The web control lives inside the clock process, so nothing shells out and nothing runs as root.

## Wiring

| Board pin | Raspberry Pi | Setting |
|---|---|---|
| DIO | GPIO 17 (pin 11) | `display.dio` |
| CLK | GPIO 27 (pin 13) | `display.clk` |
| STB | GPIO 22 (pin 15) | `display.stb` |
| VCC | 3.3 V (pin 1) | |
| GND | Ground (pin 6) | |
| Buzzer + (optional) | GPIO 10 (pin 19) | `buzzer.pin` |

3.3 V is the safe choice for VCC: on these boards the data line is usually pulled up to VCC, and the Pi's GPIO pins are 3.3 V only. GPIO 10 is also the SPI data pin, so pick another pin for the buzzer if you have SPI turned on.

## Install on the Pi

```bash
sudo apt install python3-venv python3-gpiozero python3-rpi-lgpio git
git clone https://github.com/josedaidone/smart-clock
cd smart-clock
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install --no-deps git+https://github.com/thilaire/rpi-TM1638
```

`python3-rpi-lgpio` provides `RPi.GPIO` on every Pi model, including the Pi 5. If apt says it conflicts with `python3-rpi.gpio`, either one works on a Pi 4 or older. The display driver is installed with `--no-deps` so pip uses the system GPIO package instead of trying to build its own.

## Set it up

```bash
cp config.example.toml config.toml
.venv/bin/python -m smart_clock hash-password --user yourname
```

Paste the line that prints under `[web.users]` in `config.toml`. The web control stays off until there is at least one user. `config.toml` is git-ignored.

Check the wiring before anything else:

```bash
.venv/bin/python -m smart_clock hwtest
```

It lights every segment and LED, steps through the brightness levels, beeps the buzzer if enabled, then asks you to press each button.

Run it:

```bash
.venv/bin/python -m smart_clock run
```

To start it at boot, copy `systemd/smart-clock.service` to `/etc/systemd/system/` (edit the user and paths if yours differ), then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now smart-clock
journalctl -u smart-clock -f      # logs
```

Stopping the service blanks the display.

## Using it

Open `http://<pi-address>:5000` and log in. The page mirrors what the display is showing and lets you send a message, turn the display on or off, dismiss a message and set the brightness.

### Buttons

| Button | Does |
|---|---|
| S1 | Dismiss the current message or alarm |
| S2 | Snooze an alarm |
| S3 | Show the last message again |
| S4 | Next page: time, date, temperature (falls back to the time after 10 s) |
| S5 / S6 | Dimmer / brighter |
| S7 | Unused |
| S8 | Display on / off |

Set `buttons = false` under `[display]` to ignore the buttons.

### Schedule and alarms

Add as many `[[schedule]]` blocks to `config.toml` as you like:

```toml
[[schedule]]
time = "07:30"
days = ["mon", "tue", "wed", "thu", "fri"]   # optional, default every day
text = "bom dia"
duration = 60                                 # optional, seconds
alarm = true                                  # optional
```

A plain entry scrolls its text for `duration` seconds. An alarm repeats (and buzzes) until you dismiss or snooze it, or until `[alarm] timeout` runs out. If the display is off, plain entries are skipped and alarms still go off.

### Display notes

Seven segments can't draw everything. Accents are dropped (`são` shows as `sao`), letters use whichever case is legible, and characters with no shape show as a blank. Long text scrolls; a message always finishes at least one full pass.

### API

Everything needs the same login. Anything that changes the clock is a `POST` with a JSON body. Ten wrong passwords from one address lock that address out for five minutes.

```bash
curl -u yourname -H 'Content-Type: application/json' \
     -d '{"text": "oi linda", "duration": 30}' http://<pi-address>:5000/api/message
```

| Request | Body | |
|---|---|---|
| `GET /api/status` | | What the display shows, brightness, queue |
| `POST /api/message` | `{"text": "...", "duration": 30}` | `duration` is optional |
| `POST /api/display` | `{"on": false}` | Off also drops waiting messages |
| `POST /api/brightness` | `{"level": 0}` to `7` | |
| `POST /api/dismiss` | `{}` | |
| `POST /msg/` | `{"msg": "..."}` | Kept from the old version |

## Reaching it from outside your home

Don't forward a port to it. The login is HTTP Basic, which is only safe over HTTPS, and the clock itself speaks plain HTTP. Put it behind something that adds HTTPS and keeps it off the open internet:

- **Tailscale**: install it on the Pi and your phone, set `host = "127.0.0.1"` in `[web]`, and run `sudo tailscale serve --bg 5000`. The clock is then at `https://<pi-name>.<your-tailnet>.ts.net` for your devices only.
- **Cloudflare Tunnel**: point a tunnel at `http://localhost:5000` and put Cloudflare Access in front of it.

If the page loads behind a proxy but every button answers 403, the proxy is rewriting the `Host` header; turn that off.

## Try it without a Pi (the emulator)

`run --simulate` runs the real clock and the real web control against an emulated board, on any computer:

```bash
python -m venv .venv

# Windows
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m smart_clock run --simulate

# macOS / Linux
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m smart_clock run --simulate
```

It prints the emulator's address and a login made up for that run:

```
  Emulator:  http://127.0.0.1:5000/emulator
  Login:     demo / 3fXk0aQz   (made up for this run)
```

The emulator page has the board on one side (LEDs, digits, buzzer, and the eight buttons, which you press with the mouse or keys 1 to 8) and the real web control on the other. "Board clock" jumps the board's time, so you can land ten seconds before a scheduled message, an alarm or night dimming instead of waiting for it.

- With no `config.toml` it uses `config.example.toml`. With your own `config.toml` it uses your schedule and your users.
- If port 5000 is busy (macOS uses it for AirPlay), add `--port 8080`.
- To emulate the TM1638 chip itself, also run `pip install --no-deps git+https://github.com/thilaire/rpi-TM1638` in the same environment. The real driver library then bit-bangs a fake GPIO, and the page shows what the chip decoded. Without it the board is a plain in-memory stand-in.
- `run --simulate --no-web` draws the display in the terminal instead.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

The tests run the clock against the emulated board with a fake clock, so a minute of schedule takes milliseconds. `tests/test_tm1638_backend.py` drives the real `rpi_TM1638` library through the fake GPIO; it is skipped if the library isn't installed.

## Coming from the old scripts

| Before | Now |
|---|---|
| `sudo python clock.py start` / `stop` / `restart` | `sudo systemctl start` / `stop` / `restart smart-clock` |
| `clock.py msg "..."`, `control.py txt "..."` | The web page, or `POST /api/message` |
| `GET /text/<msg>` | `POST /api/message` |
| `GET /start/`, `GET /stop/` | `POST /api/display`, or button S8 |
| `secret_db.py` with plain passwords | `[web.users]` with password hashes |
| Messages at 19:00 and 20:00 in the code | `[[schedule]]` in `config.toml` |
| `plaquinha.py`, `control.py`, `teste.py` | `python -m smart_clock hwtest`, or just send a message |
