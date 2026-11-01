# SPDX-License-Identifier: GPL-3.0-or-later
"""The encoder and button logic (bridge/rpi-audio-ui/inputs.py): levels in, events out."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bridge" / "rpi-audio-ui"))
import inputs  # noqa: E402

# One detent clockwise on a KY-040-like encoder: `a` goes low first, then `b`; both come back high in that order.
CW = [(0, 1), (0, 0), (1, 0), (1, 1)]
CCW = [(1, 0), (0, 0), (0, 1), (1, 1)]


def steps(encoder, moves):
    return [encoder.feed(a, b) for a, b in moves]


def test_one_detent_one_step_either_way():
    e = inputs.Encoder()
    assert steps(e, CW) == [0, 0, 0, 1]
    assert steps(e, CCW) == [0, 0, 0, -1]
    assert sum(steps(e, CW * 5)) == 5 and sum(steps(e, CCW * 3)) == -3


def test_invert_swaps_the_direction():
    e = inputs.Encoder(invert=True)
    assert sum(steps(e, CW)) == -1 and sum(steps(e, CCW)) == 1


def test_bounce_and_partial_turns_make_no_step():
    e = inputs.Encoder()
    assert sum(steps(e, [(1, 0), (1, 1), (1, 0), (1, 1)])) == 0        # a click that went back
    assert sum(steps(e, [(1, 0), (0, 0), (1, 0), (1, 1)])) == 0        # half a detent and back
    assert sum(steps(e, [(0, 1), (0, 1), (0, 0), (1, 0), (0, 0), (1, 0), (1, 1)])) == 1   # bounce inside a detent
    assert e.feed(1, 1) == 0


def test_an_encoder_that_rests_low_works_too():
    e = inputs.Encoder()
    e.sync(0, 0)
    turn = [(1, 0), (1, 1), (0, 1), (0, 0)]   # the same turning, from the other rest
    assert steps(e, turn) == [0, 0, 0, 1] and steps(e, turn[::-1][1:] + [(0, 0)])[-1] == -1
    assert sum(steps(e, turn * 3)) == 3


def test_it_learns_the_rest_from_where_the_knob_stops():
    e = inputs.Encoder()   # starts expecting a rest of (1, 1) but the knob sits at (0, 0)
    assert e.feed(0, 0, 0.0) == 0 and e.state == 0b00
    got = [e.feed(a, b, 1.0 + n * 0.01) for n, (a, b) in enumerate([(1, 0), (1, 1), (0, 1), (0, 0)])]
    assert got == [0, 0, 0, 1]


def test_a_missed_edge_does_not_corrupt_the_next_detent():
    e = inputs.Encoder()
    assert sum(steps(e, [(1, 0), (0, 1), (1, 1)])) == 0   # a skipped state (an impossible jump) is ignored
    assert sum(steps(e, CW)) == 1


def test_button_press_once_and_debounced():
    b = inputs.Button(debounce=0.03)
    assert b.feed(True, 1.00) is True
    assert b.feed(True, 1.01) is False                  # still down
    assert b.feed(False, 1.02) is False                 # a bounce: too soon to count as a release
    assert b.feed(False, 1.10) is False                 # the release, accepted: no event
    assert b.feed(True, 1.20) is True                   # the next press
    assert b.feed(False, 1.21) is False and b.feed(True, 1.22) is False   # bounce on release: still the same press
    assert b.feed(False, 1.30) is False and b.feed(True, 1.40) is True


def test_panel_turns_lines_into_events():
    p = inputs.Panel()
    out = []
    for a, b in CW + CW + CCW:
        out += p.edge("a", a, 0.0) if a != p.level["a"] else []
        out += p.edge("b", b, 0.0) if b != p.level["b"] else []
    assert out == ["cw", "cw", "ccw"]
    assert p.edge("confirm", 0, 1.0) == ["confirm"] and p.edge("confirm", 1, 1.2) == []
    assert p.edge("back", 0, 2.0) == ["back"] and p.edge("push", 0, 3.0) == ["push"]
    assert p.edge("confirm", 0, 4.0) == ["confirm"] and p.edge("push", 1, 4.1) == []   # a release is no event


def test_pins_match_the_documented_wiring():
    assert inputs.PINS == {"a": 17, "b": 27, "push": 22, "confirm": 23, "back": 24}
