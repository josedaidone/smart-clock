"use strict";

const $ = (id) => document.getElementById(id);
const BUTTONS = ["dismiss", "snooze", "replay", "page", "dimmer", "brighter", "", "power"];
const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
// How bright each of the chip's eight levels looks (its duty cycles, roughly).
const GLOW = [0.3, 0.36, 0.45, 0.72, 0.79, 0.86, 0.93, 1];

const board = Board.build($("leds"), $("digits"));
const keys = [];
const down = new Set();

function say(text, isError) {
  $("log").textContent = text;
  $("log").classList.toggle("error", Boolean(isError));
}

// ----------------------------------------------------------------- buttons
function setButton(button, isDown) {
  if (isDown === down.has(button)) return;
  if (isDown) down.add(button); else down.delete(button);
  keys[button].classList.toggle("down", isDown);
  Board.api("/emulator/api/button", {button, down: isDown}).catch((error) => say(error.message, true));
}

BUTTONS.forEach((name, button) => {
  const key = document.createElement("button");
  key.type = "button";
  key.className = "key";
  key.setAttribute("aria-label", "S" + (button + 1) + (name ? " " + name : ""));
  const cap = document.createElement("span");
  cap.className = "cap";
  const label = document.createElement("span");
  label.className = "label";
  label.textContent = "S" + (button + 1);
  const role = document.createElement("span");
  role.className = "role";
  role.textContent = name || "–";
  key.append(cap, label, role);
  key.addEventListener("pointerdown", (event) => {
    key.setPointerCapture(event.pointerId);
    setButton(button, true);
  });
  for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) {
    key.addEventListener(type, () => setButton(button, false));
  }
  $("buttons").appendChild(key);
  keys.push(key);
});

function keyToButton(event) {
  if (event.target.matches("input") || event.ctrlKey || event.metaKey || event.altKey) return -1;
  const number = Number(event.key);
  return number >= 1 && number <= 8 ? number - 1 : -1;
}
document.addEventListener("keydown", (event) => {
  const button = keyToButton(event);
  if (button >= 0 && !event.repeat) setButton(button, true);
});
document.addEventListener("keyup", (event) => {
  const button = keyToButton(event);
  if (button >= 0) setButton(button, false);
});
window.addEventListener("blur", () => [...down].forEach((button) => setButton(button, false)));

// ------------------------------------------------------------------ buzzer
let audio = null;
let beeping = false;

function buzz(on) {
  $("buzzer").classList.toggle("on", on);
  if (!audio || on === beeping) return;
  beeping = on;
  const now = audio.context.currentTime;
  audio.gain.gain.cancelScheduledValues(now);
  audio.gain.gain.setValueAtTime(0, now);
  if (on) {
    // 0.4 s on, 0.4 s off, like the real buzzer; scheduled a minute ahead.
    for (let t = 0; t < 60; t += 0.8) {
      audio.gain.gain.setValueAtTime(0.08, now + t);
      audio.gain.gain.setValueAtTime(0, now + t + 0.4);
    }
  }
}

$("sound").addEventListener("change", (event) => {
  if (event.target.checked && !audio) {
    const context = new AudioContext();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = "square";
    oscillator.frequency.value = 2300;
    gain.gain.value = 0;
    oscillator.connect(gain).connect(context.destination);
    oscillator.start();
    audio = {context, gain};
  } else if (!event.target.checked && audio) {
    buzz(false);
    audio.context.close();
    audio = null;
    beeping = false;
  }
});

// ------------------------------------------------------------- board clock
async function jump(body, done) {
  try {
    const result = await Board.api("/emulator/api/time", body);
    say(done + " The board now says " + result.time + ".");
  } catch (error) {
    say(error.message, true);
  }
}

function tenSecondsBefore(hhmm) {
  const [hours, minutes] = hhmm.split(":").map(Number);
  const total = (hours * 3600 + minutes * 60 - 10 + 86400) % 86400;
  const pad = (n) => String(n).padStart(2, "0");
  return pad(Math.floor(total / 3600)) + ":" + pad(Math.floor(total / 60) % 60) + ":" + pad(total % 60);
}

function addJump(label, hhmm) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", () => jump({time: tenSecondsBefore(hhmm)}, "Jumped to 10 s before " + hhmm + "."));
  $("jumps").appendChild(button);
}

$("set-time").addEventListener("click", () => jump({time: $("time").value}, "Time set."));
$("reset-time").addEventListener("click", () => jump({reset: true}, "Back to the real time."));

async function loadInfo() {
  try {
    const info = await Board.api("/emulator/api/info");
    $("mode").textContent = info.wire_level
      ? "the real rpi_TM1638 library is driving an emulated TM1638 chip, and this shows what the chip received."
      : "a plain in-memory board (install rpi_TM1638 to emulate the chip itself).";
    if (!info.buttons_enabled) say("Buttons are switched off in the config (display.buttons = false).", true);
    for (const entry of info.schedule) {
      const days = entry.days ? " (" + entry.days.map((d) => DAYS[d]).join(", ") + " only)" : "";
      const text = entry.text.length > 28 ? entry.text.slice(0, 27) + "…" : entry.text;
      addJump((entry.alarm ? "Alarm " : "") + entry.time + " “" + text + "”" + days, entry.time);
    }
    if (info.night_start) addJump("Night dimming at " + info.night_start, info.night_start);
  } catch (error) {
    $("mode").textContent = "could not load: " + error.message;
  }
}

// ------------------------------------------------------------------- state
let busy = false;

async function refresh() {
  if (busy) return;
  busy = true;
  try {
    const state = await Board.api("/emulator/api/state");
    Board.draw(board, state.segments, state.leds);
    $("pcb").style.setProperty("--glow", GLOW[state.brightness === null ? 7 : state.brightness]);
    $("brightness-level").textContent = state.brightness === null ? "–" : state.brightness;
    $("board-time").textContent = state.time + (state.time_shifted ? " (shifted)" : "");
    buzz(state.buzzer);
  } catch (error) {
    $("board-time").textContent = "not reachable";
  } finally {
    busy = false;
  }
}

loadInfo();
refresh();
setInterval(refresh, 80);
