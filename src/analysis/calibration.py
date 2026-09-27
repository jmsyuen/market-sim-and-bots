'''
Scoring forecasts against resolved outcomes.

This is the file that justifies choosing a prediction market over equities.
An equity simulator cannot do this at all: there is no terminal truth to score
against. Here every market resolves to 0 or 1, so a forecast can be graded.

THE PUNCHLINE, and the only result that matters from this file: score the
MARKET'S implied probability and YOUR fair value over the same set of resolved
markets. Lower Brier or log loss than the market is measured edge, not a
backtest curve that could be luck.

Everything here takes probabilities in (0,1), not ticks. Divide by 100 at the
boundary and keep this file unit-free.
'''

import math

# log loss is infinite at p = 0 or 1, and a maker quoting 1 tick produces
# exactly that. Clip rather than crash - and report how often clipping bit,
# because a model that needs heavy clipping is badly calibrated at the tails.
EPSILON = 1e-9


def brier(probabilities, outcomes):
    '''
    mean((p - outcome)^2). Lower is better, range 0 to 1.

    A constant forecast of the base rate scores base_rate * (1 - base_rate),
    so 0.25 at p = 0.5. That is the number to beat; anything above it is worse
    than saying "I don't know".
    '''
    ...


def log_loss(probabilities, outcomes, epsilon=EPSILON):
    '''
    -mean(o * ln(p) + (1 - o) * ln(1 - p)).

    Punishes confident wrongness far harder than Brier does. Report both: a
    model that beats the market on Brier but loses on log loss is making a few
    catastrophic calls, which for a trader is the more important fact.
    '''
    ...


def reliability(probabilities, outcomes, bins=10):
    '''
    Bin the forecasts and compare predicted to realised frequency.

    Returns a list of (bin_centre, mean_predicted, empirical_frequency, count)
    with EMPTY BINS OMITTED - a bin with two observations is noise, and plotted
    naively it looks like a calibration failure.

    Plot against the diagonal. Flatter than the diagonal means overconfident:
    the things called 90% only happen 70% of the time.
    '''
    ...


def score_run(predictions, outcomes):
    '''
    Convenience: both scores plus the base-rate benchmark, as one dict.
    '''
    ...


def collect(build_engine, seeds, fee_per_contract=0.0):
    '''
    Run one market per seed and collect (prediction, outcome) pairs.

    ONE MARKET GIVES ONE OUTCOME. A reliability curve needs a few hundred
    independent resolved markets, so this loop is not optional - it is the
    whole reason calibration works at all.

    build_engine(seed) -> a fresh SimEngine. Vary p0 across seeds as well, or
    every prediction clusters near 0.5 and the reliability curve has one
    populated bin.

    The prediction is the reference (micro_price / 100) at the LAST snapshot
    before decision_time - not the final row, which is post-resolution and
    would be 0 or 1. Scoring that would give a perfect Brier and mean nothing.

    Returns (predictions, outcomes) ready for the functions above.
    '''
    ...
