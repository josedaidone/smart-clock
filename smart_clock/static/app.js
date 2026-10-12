"use strict";

// One rectangle per segment, in bit order (0 = top ... 6 = middle).
const SEGMENTS = [
  [12, 4, 36, 8], [48, 10, 8, 36], [48, 54, 8, 36], [12, 88, 36, 8],
  [4, 54, 8, 36], [4, 10, 8, 36], [12, 46, 36, 8],
];
const SVG = "http://www.w3.org/2000/svg";
const $ = (id) => document.getElementById(id);

const digits = [];
const leds = [];

function buildBoard() {
  for (let i = 0; i < 8; i++) {
    const led = document.createElement("span");
    led.className = "led";
    $("leds").appendChild(led);
    leds.push(led);

    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("viewBox", "0 0 74 100");
    svg.setAttribute("class", "digit");
    const parts = SEGMENTS.map(([x, y, w, h]) => {
      const rect = document.createElementNS(SVG, "rect");
      rect.setAttribute("x", x);
      rect.setAttribute("y", y);
      rect.setAttribute("width", w);
      rect.setAttribute("height", h);
      rect.setAttribute("rx", 4);
      svg.appendChild(rect);
      return rect;
    });
    const dot = document.createElementNS(SVG, "circle");
    dot.setAttribute("cx", 66);
    dot.setAttribute("cy", 92);
    dot.setAttribute("r", 5);
    svg.appendChild(dot);
    parts.push(dot);
    $("digits").appendChild(svg);
    digits.push(parts);
  }
}

function drawBoard(status) {
  status.segments.forEach((bits, i) => {
    digits[i].forEach((part, bit) => part.classList.toggle("lit", Boolean(bits & (1 << bit))));
  });
  status.leds.forEach((value, i) => {
    leds[i].classList.toggle("lit", value === 1);
    leds[i].classList.toggle("green", value === 2);
  });
}

async function api(path, body) {
  const options = body === undefined ? {} : {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  };
  const response = await fetch(path, options);
  let data = {};
  try { data = await response.json(); } catch (error) { /* not JSON */ }
  if (!response.ok) throw new Error(data.error || "HTTP " + response.status);
  return data;
}

function say(text, isError) {
  $("log").textContent = text;
  $("log").classList.toggle("error", Boolean(isError));
}

async function act(path, body, done) {
  try {
    await api(path, body);
    say(done);
    refresh();
  } catch (error) {
    say(error.message, true);
  }
}

async function refresh() {
  try {
    const status = await api("/api/status");
    drawBoard(status);
    let state = status.display_on ? "Display on" : "Display off";
    if (status.message) state = (status.alarm ? "Alarm: " : "Showing: ") + status.message;
    if (status.queued) state += " (" + status.queued + " waiting)";
    if (status.weather) state += " · " + status.weather;
    $("state").textContent = state;
    if (document.activeElement !== $("brightness")) $("brightness").value = status.brightness;
  } catch (error) {
    $("state").textContent = "Can't reach the clock: " + error.message;
  }
}

buildBoard();

$("message-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const text = $("text").value.trim();
  if (!text) return;
  act("/api/message", {text}, "Sent: " + text);
  $("text").value = "";
});
$("on").addEventListener("click", () => act("/api/display", {on: true}, "Display on"));
$("off").addEventListener("click", () => act("/api/display", {on: false}, "Display off"));
$("dismiss").addEventListener("click", () => act("/api/dismiss", {}, "Dismissed"));
$("brightness").addEventListener("change", (event) => {
  const level = Number(event.target.value);
  act("/api/brightness", {level}, "Brightness " + level);
});

refresh();
setInterval(refresh, 1000);
