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
import statistics

import pytest

from src.market.value_process import ValueProcess


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
# Default construction: no news, decision_time defaults to resolve_time. Pass
# overrides per test. p0=0.5 puts x at exactly 0.0, which makes several of the
# assertions below exact rather than approximate.


def make_process() -> ValueProcess:
    return ValueProcess(p0=0.5, vol=1.0, resolve_time=1.0, seed=0)


def walk_to(process, end_time, steps):
    """Advance in `steps` equal increments up to end_time.

    Many small steps rather than one large one, because the martingale drift
    uses p at the START of each interval (Euler). One giant step would leave a
    discretisation error big enough to swamp the property being tested.
    """
    for step_index in range(1, steps + 1):
        process.advance_to(end_time * step_index / steps)


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

    THE LOAD-BEARING TEST of pass 1. An inverted pair still round-trips
    correctly, so test_round_trip_recovers_p passes happily with both signs
    flipped. This is the only assertion here that catches that.
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


# ----------------------------------------------------------------------
# PASS 2 - the walk
# ----------------------------------------------------------------------


def test_p_stays_inside_unit_interval_over_a_long_walk():
    """100k steps at vol=2.0 and p never touches a boundary.

    This is the whole reason the logit transform exists, so assert it directly
    rather than trusting the maths.

    Note the ceiling on how hard this can be pushed: past x = 37, sigmoid
    returns EXACTLY 1.0 in float64 and this assertion would fail. That is not a
    bug in the walk - x is fine, only the view saturates - and it is precisely
    why the STATE is x and not p. A process that stored p could not recover.
    """
    process = ValueProcess(p0=0.5, vol=2.0, resolve_time=1.0, seed=7)
    steps = 100_000
    end_time = 0.9999          # stop short of decision_time; after it p is 0 or 1

    for step_index in range(1, steps + 1):
        p = process.advance_to(end_time * step_index / steps)
        assert 0.0 < p < 1.0


def test_same_seed_reproduces_the_path():
    """Identical seeds give identical paths; different seeds do not.

    This is the basis of every Mode A counterfactual: re-run the same world
    with one strategy knob changed. If this fails, no comparison across runs
    means anything.
    """
    first = ValueProcess(p0=0.5, vol=1.0, resolve_time=1.0, seed=42)
    second = ValueProcess(p0=0.5, vol=1.0, resolve_time=1.0, seed=42)
    other = ValueProcess(p0=0.5, vol=1.0, resolve_time=1.0, seed=43)

    for step_index in range(1, 101):
        time = 0.99 * step_index / 100
        first.advance_to(time)
        second.advance_to(time)
        other.advance_to(time)

    assert first.x == second.x
    assert first.x != other.x


def test_advance_to_a_passed_time_is_a_no_op():
    """Events can share a timestamp, and the engine may hand back a stale one."""
    process = make_process()
    process.advance_to(0.5)

    x_after_first_call = process.x
    returned = process.advance_to(0.3)

    assert process.x == x_after_first_call
    assert process.last_time == 0.5
    assert returned == process.p


def test_terminal_spread_scales_with_sqrt_of_time():
    """std(x) at T=4 is about DOUBLE std(x) at T=1, not quadruple.

    LOAD-BEARING. A dt-instead-of-sqrt(dt) bug does not crash and does not
    violate any invariant - it just makes realised volatility wrong, which
    reads as "vol is higher than I set it" and gets fixed by retuning the
    parameter instead of the code.

    vol is small and p0 = 0.5 so the drift term contributes almost nothing and
    the diffusion is measured cleanly. decision_time is far away so nothing
    freezes mid-run.
    """
    runs = 2000
    standard_deviations = {}

    for horizon in [1.0, 4.0]:
        terminal_values = []
        for seed in range(runs):
            process = ValueProcess(p0=0.5, vol=0.1, resolve_time=100.0, seed=seed)
            walk_to(process, horizon, 20)
            terminal_values.append(process.x)
        standard_deviations[horizon] = statistics.stdev(terminal_values)

    ratio = standard_deviations[4.0] / standard_deviations[1.0]

    assert 1.85 < ratio < 2.15


# ----------------------------------------------------------------------
# PASS 3 - the martingale property
# ----------------------------------------------------------------------


@pytest.mark.slow
def test_p_is_a_martingale():
    """E[p_T] == p0, and E[outcome] == p0, at an OFF-CENTRE p0.

    LOAD-BEARING, and the only test that touches the drift term. Delete
    `self.x += (self.p - 0.5) * self.vol ** 2 * dt` and this is what fails.

    p0 = 0.8, not 0.5. The bias the drift term corrects is exactly zero at 0.5
    because sigmoid is symmetric there, so a test at 0.5 passes whether or not
    the correction exists and proves nothing.

    Two assertions, deliberately:
      - mean terminal p    - low variance, tests the process directly
      - mean outcome       - higher variance, tests the process AND the
                             Bernoulli draw end to end. This is the quantity
                             calibration.py will score against, so it is the
                             one that has to be right.
    """
    p0 = 0.8
    runs = 3000
    steps = 200

    terminal_probabilities = []
    outcomes = []

    for seed in range(runs):
        process = ValueProcess(p0=p0, vol=1.0, resolve_time=1.0, seed=seed)
        walk_to(process, 0.9995, steps)       # stop just short of the freeze
        terminal_probabilities.append(process.p)
        process.advance_to(1.0)               # crosses decision_time, draws the outcome
        outcomes.append(process.outcome)

    mean_probability = statistics.fmean(terminal_probabilities)
    mean_outcome = statistics.fmean(outcomes)

    probability_tolerance = 4.0 * statistics.stdev(terminal_probabilities) / math.sqrt(runs)
    outcome_tolerance = 4.0 * math.sqrt(p0 * (1.0 - p0) / runs)

    assert abs(mean_probability - p0) < probability_tolerance
    assert abs(mean_outcome - p0) < outcome_tolerance


# ----------------------------------------------------------------------
# PASS 4 - resolution
# ----------------------------------------------------------------------


def test_resolve_is_idempotent():
    """The analysis layer may ask more than once; re-drawing would give a
    different answer each time and silently corrupt every score."""
    process = make_process()
    process.advance_to(0.9)

    first = process.resolve()
    second = process.resolve()

    assert first == second
    assert first in (0, 1)


def test_outcome_is_not_a_threshold_on_p():
    """Both outcomes occur from the same p0, so the draw is genuinely random.

    If outcome were round(p_T), a model that merely parrots the market's price
    would score a perfect Brier and the whole validation layer would reward
    overconfidence instead of calibration. A proper scoring rule is only proper
    against a genuinely stochastic outcome.
    """
    observed = set()

    for seed in range(200):
        process = ValueProcess(p0=0.5, vol=0.2, resolve_time=1.0, seed=seed)
        process.advance_to(1.0)
        observed.add(process.outcome)

    assert observed == {0, 1}


def test_the_walk_freezes_once_decided():
    """After decision_time: p is exactly 1.0 or 0.0, and nothing moves again."""
    process = ValueProcess(p0=0.5, vol=1.0, resolve_time=1.0, seed=3, decision_time=0.5)
    process.advance_to(0.6)

    assert process.outcome is not None
    assert process.p in (0.0, 1.0)
    assert process.tick_price in (0.0, 100.0)

    x_at_freeze = process.x
    last_time_at_freeze = process.last_time
    process.advance_to(1.0)

    assert process.x == x_at_freeze
    assert process.last_time == last_time_at_freeze


def test_clamping_stops_the_walk_at_decision_time():
    """A call that overshoots must only diffuse as far as the freeze point.

    Without the clamp, last_time would be set to the requested time and that
    final interval would receive more volatility than the calendar allows.
    """
    process = ValueProcess(p0=0.5, vol=1.0, resolve_time=1.0, seed=5, decision_time=0.4)
    process.advance_to(0.9)

    assert process.last_time == 0.4


def test_decision_precedes_settlement():
    """The answer is known while the market is still open.

    That window is the resolution hazard: stale quotes sit in the book with the
    outcome already determined. Resolution-aware widening exists to defend
    against exactly this, so if the window cannot be constructed the feature
    would measure zero and look useless.
    """
    process = ValueProcess(p0=0.5, vol=1.0, resolve_time=1.0, seed=11, decision_time=0.5)
    process.advance_to(0.5)

    assert process.outcome is not None
    assert process.last_time < process.resolve_time


# ----------------------------------------------------------------------
# PASS 5 - news
# ----------------------------------------------------------------------


def test_jumps_gap_the_price_and_only_at_news_times():
    """LOAD-BEARING. vol=0 isolates the jumps: any movement at all IS a jump.

    An off-by-one in the (last_time, target] window is completely invisible in
    normal running - the jump just lands in the neighbouring interval, or fires
    twice - so it has to be tested directly rather than inferred from a path.
    """
    process = ValueProcess(
        p0=0.5,
        vol=0.0,
        resolve_time=1.0,
        seed=2,
        news_times=(0.5,),
        jump_vol=2.0,
    )

    assert process.x == 0.0

    process.advance_to(0.3)                      # no news in (0.0, 0.3]
    assert process.x == 0.0

    process.advance_to(0.6)                      # news at 0.5 lands here
    x_after_news = process.x
    assert x_after_news != 0.0

    process.advance_to(0.9)                      # no news left
    assert process.x == x_after_news


def test_each_news_event_fires_exactly_once():
    """Three events, three shocks, however the intervals are carved up.

    Asserted through the pointer, not by comparing the two x values. Those
    differ, and legitimately so: gauss() consumes the RNG stream whether or not
    sigma is zero, so a walk advanced in 99 calls draws 99 diffusion values
    before its jumps while a walk advanced in one call draws one. Same
    distribution, different realisation. See the README note on what that costs
    a counterfactual.
    """
    fine = ValueProcess(
        p0=0.5, vol=0.0, resolve_time=1.0, seed=4,
        news_times=(0.2, 0.5, 0.8), jump_vol=1.0,
    )
    coarse = ValueProcess(
        p0=0.5, vol=0.0, resolve_time=1.0, seed=4,
        news_times=(0.2, 0.5, 0.8), jump_vol=1.0,
    )

    for step_index in range(1, 100):
        fine.advance_to(0.99 * step_index / 99)
    coarse.advance_to(0.99)

    assert fine._news_index == 3
    assert coarse._news_index == 3

    # and neither fires again
    fine.advance_to(0.995)
    coarse.advance_to(0.995)
    assert fine._news_index == 3
    assert coarse._news_index == 3


def test_unscheduled_news_never_leaks_into_the_public_view():
    """THE INTEGRITY TEST. scheduled_news_times is the ONLY thing the market
    maker may read about news.

    If a surprise appears here the maker can pull quotes before it, the
    scheduled-vs-unscheduled comparison measures nothing, and every result
    downstream is void.

    news_times is passed unsorted on purpose - the schedule must sort it.
    """
    process = ValueProcess(
        p0=0.5,
        vol=1.0,
        resolve_time=1.0,
        seed=1,
        news_times=(0.7, 0.3),
        jump_vol=2.0,
        surprise_rate=20.0,
    )

    assert process.scheduled_news_times == (0.3, 0.7)
    assert len(process._news_events) > 2      # surprises exist, privately


def test_news_schedule_is_deterministic_and_off_by_default():
    """Same seed, same schedule. surprise_rate=0 generates nothing."""
    first = ValueProcess(
        p0=0.5, vol=1.0, resolve_time=1.0, seed=9,
        news_times=(0.4,), surprise_rate=8.0, jump_vol=1.0,
    )
    second = ValueProcess(
        p0=0.5, vol=1.0, resolve_time=1.0, seed=9,
        news_times=(0.4,), surprise_rate=8.0, jump_vol=1.0,
    )

    assert first._news_events == second._news_events

    quiet = ValueProcess(p0=0.5, vol=1.0, resolve_time=1.0, seed=9)
    assert quiet._news_events == []
    assert quiet.scheduled_news_times == ()


def test_news_after_decision_time_is_dropped():
    """An event past the freeze point could never fire, so it should not be in
    the schedule at all - and must not appear in the public view, where it
    would advertise a jump that never happens."""
    process = ValueProcess(
        p0=0.5, vol=1.0, resolve_time=1.0, seed=6, decision_time=0.5,
        news_times=(0.2, 0.8), jump_vol=1.0,
    )

    assert process.scheduled_news_times == (0.2,)
