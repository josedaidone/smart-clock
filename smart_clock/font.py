"""Seven-segment glyphs and text layout for the 8-digit display.

Every character becomes one "cell": an int whose bits say which segments
are lit. Nothing here touches hardware, so it can be tested anywhere.

    Segment bits:      0
                     -----
                  5 |     | 1
                     --6--
                  4 |     | 2
                     -----   . 7
                       3
"""

from __future__ import annotations

import unicodedata
from typing import List

WIDTH = 8
DOT = 0x80
BLANK = [0] * WIDTH

GLYPHS = {
    " ": 0x00,
    "0": 0x3F, "1": 0x06, "2": 0x5B, "3": 0x4F, "4": 0x66,
    "5": 0x6D, "6": 0x7D, "7": 0x07, "8": 0x7F, "9": 0x6F,
    # Letters use whichever case reads best on seven segments. Where both
    # cases are legible (C/c, H/h, ...) both are kept.
    "A": 0x77, "b": 0x7C, "C": 0x39, "c": 0x58, "d": 0x5E, "E": 0x79,
    "F": 0x71, "G": 0x3D, "H": 0x76, "h": 0x74, "I": 0x30, "i": 0x10,
    "J": 0x1E, "K": 0x75, "L": 0x38, "M": 0x15, "N": 0x37, "n": 0x54,
    "O": 0x3F, "o": 0x5C, "P": 0x73, "q": 0x67, "r": 0x50, "S": 0x6D,
    "t": 0x78, "U": 0x3E, "u": 0x1C, "V": 0x3E, "v": 0x1C, "W": 0x2A,
    "X": 0x76, "y": 0x6E, "Z": 0x5B,
    "-": 0x40, "_": 0x08, "=": 0x48, "?": 0x53, "!": 0x86, '"': 0x22,
    "'": 0x20, "°": 0x63, "*": 0x63, "/": 0x52, "\\": 0x64,
    "(": 0x39, "[": 0x39, ")": 0x0F, "]": 0x0F,
}


def normalize(text: str) -> str:
    """Strip accents (so "são" shows as "sao") and flatten whitespace."""
    decomposed = unicodedata.normalize("NFKD", text)
    out = []
    for ch in decomposed:
        if unicodedata.combining(ch):
            continue
        out.append(" " if ch.isspace() else ch)
    return "".join(out)


def glyph(ch: str) -> int:
    """Segment bits for one character; anything unknown renders blank."""
    for candidate in (ch, ch.upper(), ch.lower()):
        if candidate in GLYPHS:
            return GLYPHS[candidate]
    return 0


def encode(text: str) -> List[int]:
    """Turn text into cells. A '.' or ',' lights the previous cell's dot."""
    cells: List[int] = []
    for ch in normalize(text):
        if ch in ".,":
            if cells and not cells[-1] & DOT:
                cells[-1] |= DOT
            else:
                cells.append(DOT)
        else:
            cells.append(glyph(ch))
    return cells


def frames(text: str, width: int = WIDTH) -> List[List[int]]:
    """Frames needed to show text: one if it fits, a scroll otherwise.

    The scroll starts with the first `width` cells and ends with the last
    `width` cells, so every frame is full.
    """
    cells = encode(text)
    if len(cells) <= width:
        return [cells + [0] * (width - len(cells))]
    return [cells[i:i + width] for i in range(len(cells) - width + 1)]


def centered(text: str, width: int = WIDTH) -> List[int]:
    """One frame with the text centred (truncated if too long)."""
    cells = encode(text)[:width]
    left = (width - len(cells)) // 2
    return [0] * left + cells + [0] * (width - len(cells) - left)


def render_ascii(cells: List[int]) -> List[str]:
    """Three lines of ASCII art for a frame (used by the simulator)."""
    top = mid = bot = ""
    for bits in cells:
        top += " " + ("_" if bits & 0x01 else " ") + "  "
        mid += (("|" if bits & 0x20 else " ") + ("_" if bits & 0x40 else " ")
                + ("|" if bits & 0x02 else " ") + " ")
        bot += (("|" if bits & 0x10 else " ") + ("_" if bits & 0x08 else " ")
                + ("|" if bits & 0x04 else " ") + ("." if bits & DOT else " "))
    return [top, mid, bot]
