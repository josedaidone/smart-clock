"use strict";

const $ = (id) => document.getElementById(id);
const board = Board.build($("leds"), $("digits"));

function say(text, isError) {
  $("log").textContent = text;
  $("log").classList.toggle("error", Boolean(isError));
}

async function act(path, body, done) {
  try {
    await Board.api(path, body);
    say(done);
    refresh();
  } catch (error) {
    say(error.message, true);
  }
}

async function refresh() {
  try {
    const status = await Board.api("/api/status");
    Board.draw(board, status.segments, status.leds);
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
