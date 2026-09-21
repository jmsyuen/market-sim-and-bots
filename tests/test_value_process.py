# tests for src/market/value_process.py
#
# PASS 1 - the transform pair.
#
# _logit and _sigmoid are two lines each and look too trivial to test. They are
# not. A sign error here does not crash: the walk still runs, p still lands in
# (0,1), and the symptom surfaces three layers later as "volatility is behaving
# oddly" - at which point you go hunting in advance_to and find nothing wrong.
# Testing the pair in isolation removes that entire class of confusion for the
# price of five assertions.

import math

import pytest

from src.market.value_process import ValueProcess


# ----------------------------------------------------------------------
# helper
# ----------------------------------------------------------------------
# __init__ is still a skeleton (its body is `...`), so constructing a
# ValueProcess sets no state - but it does not raise either, which is all we
# need to reach the two methods. Once __init__ is written this keeps working
# unchanged.


def make_process() -> ValueProcess:
    return ValueProcess(p0=0.5, vol=1.0, resolve_time=1.0, seed=0)


# ----------------------------------------------------------------------
# PASS 1 - the transform pair
# ----------------------------------------------------------------------


def test_round_trip_recovers_p():
    """sigmoid(logit(p)) == p across the usable range.

    The headline property: the two functions are inverses. Error should be
    around 1e-15, so pytest.approx's default relative tolerance is generous.
    """
    process = make_process()
    probabilities = [0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99]

    for p in probabilities:
        recovered = process._sigmoid(process._logit(p))
        assert recovered == pytest.approx(p)


def test_anchor_point_is_exact():
    """logit(0.5) == 0 and sigmoid(0) == 0.5, exactly.

    Both are exact in float64 - log(1.0) is 0.0 and 1/(1+1) is 0.5 - so assert
    equality rather than approx. This pins the sign convention at the origin.
    """
    process = make_process()

    assert process._logit(0.5) == 0.0
    assert process._sigmoid(0.0) == 0.5


def test_direction_is_not_inverted():
    """Probabilities above 0.5 map to positive log-odds, below to negative.

    THE LOAD-BEARING TEST. An inverted pair still round-trips correctly, so
    test_round_trip_recovers_p passes happily with both signs flipped. This is
    the only assertion here that catches that.
    """
    process = make_process()

    assert process._logit(0.9) > 0.0
    assert process._logit(0.1) < 0.0
    assert process._sigmoid(2.0) > 0.5
    assert process._sigmoid(-2.0) < 0.5


def test_sigmoid_is_symmetric():
    """sigmoid(-x) == 1 - sigmoid(x).

    Free, and catches a misplaced minus in the exponent that the round trip
    would absorb.
    """
    process = make_process()

    for x in [0.5, 1.0, 3.0, 10.0]:
        assert process._sigmoid(-x) == pytest.approx(1.0 - process._sigmoid(x))


def test_sigmoid_stays_strictly_inside_unit_interval():
    """0 < sigmoid(x) < 1 for extreme x.

    Looks trivial; it is the property the whole design rests on. The reason we
    walk in logit space at all is that no reachable x produces a p that needs
    clipping.

    Note x = 40 is close to where float64 gives up: 1 + exp(-40) rounds to 1.0
    at about x = 37, so this asserts the boundary we would hit if the state
    were ever stored as p and round-tripped.
    """
    process = make_process()

    for x in [-40.0, -10.0, 0.0, 10.0, 36.0]:
        value = process._sigmoid(x)
        assert 0.0 < value < 1.0


def test_logit_is_monotonic():
    """Larger probability, larger log-odds - no folding anywhere in the range.

    A monotonicity check over the whole interval is a cheap way to catch an
    absolute value or a squared term that the spot checks above would miss.
    """
    process = make_process()
    probabilities = [0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99]

    previous = -math.inf
    for p in probabilities:
        current = process._logit(p)
        assert current > previous
        previous = current
