import string

from smart_clock import font


def test_dot_lights_the_previous_digit_instead_of_using_a_cell():
    assert font.encode("12.5") == [0x06, 0x5B | font.DOT, 0x6D]


def test_leading_and_repeated_dots_get_their_own_cells():
    assert font.encode("..") == [font.DOT, font.DOT]


def test_accents_are_stripped_not_dropped():
    assert font.encode("são já") == font.encode("sao ja")


def test_unknown_characters_render_blank_instead_of_crashing():
    assert font.encode("#✨") == [0, 0]


def test_every_letter_and_digit_has_a_glyph():
    for ch in string.ascii_letters + string.digits:
        assert font.glyph(ch) != 0, ch


def test_short_text_is_one_padded_frame():
    assert font.frames("oi") == [font.encode("oi") + [0] * 6]


def test_scroll_ends_on_the_last_full_window():
    # The old loop ran two steps too far and showed "iscoito", "scoito".
    text = "ja sao oito - hora de comer biscoito"
    frames = font.frames(text)
    assert all(len(frame) == font.WIDTH for frame in frames)
    assert frames[0] == font.encode("ja sao o")
    assert frames[-1] == font.encode("biscoito")
    assert len(frames) == len(text) - font.WIDTH + 1


def test_centered_pads_both_sides():
    # Five cells ("3." is one), so one blank on the left and two on the right.
    assert font.centered("23.5°C") == [0] + font.encode("23.5°C") + [0, 0]


def test_ascii_art_for_an_eight():
    assert font.render_ascii([0x7F | font.DOT]) == [" _  ", "|_| ", "|_|."]
