"use strict";

// Shared by the control page and the emulator: draws eight LEDs and eight
// seven-segment digits, and talks to the JSON API.
const Board = (() => {
  // One rectangle per segment, in bit order (0 = top ... 6 = middle).
  const SEGMENTS = [
    [12, 4, 36, 8], [48, 10, 8, 36], [48, 54, 8, 36], [12, 88, 36, 8],
    [4, 54, 8, 36], [4, 10, 8, 36], [12, 46, 36, 8],
  ];
  const SVG = "http://www.w3.org/2000/svg";

  function build(ledsElement, digitsElement) {
    const board = {digits: [], leds: []};
    for (let i = 0; i < 8; i++) {
      const led = document.createElement("span");
      led.className = "led";
      ledsElement.appendChild(led);
      board.leds.push(led);

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
      digitsElement.appendChild(svg);
      board.digits.push(parts);
    }
    return board;
  }

  function draw(board, segments, leds) {
    segments.forEach((bits, i) => {
      board.digits[i].forEach((part, bit) => part.classList.toggle("lit", Boolean(bits & (1 << bit))));
    });
    leds.forEach((value, i) => {
      board.leds[i].classList.toggle("lit", value === 1);
      board.leds[i].classList.toggle("green", value === 2);
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

  return {build, draw, api};
})();
