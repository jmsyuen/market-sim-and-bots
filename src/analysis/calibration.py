'''
Scoring forecasts against resolved outcomes.

This file is why the project is a PREDICTION market and not an equity
simulator: an equity has no terminal truth to score against, so "was the price
right?" is unanswerable. Here every market resolves to 0 or 1.

THE PUNCHLINE: score the MARKET'S implied probability and YOUR fair value over
the same resolved markets. Lower Brier or log loss than the market is measured
edge, not a backtest curve that could be luck.

Everything here is in PROBABILITY, not ticks. Convert at the boundary.
'''

import math

# log loss is infinite at 0 or 1, and a maker quoting 1 tick produces exactly
# that. Clip rather than crash.
EPSILON = 1e-9


def brier(probabilities, outcomes):
    '''
    mean((p - outcome)^2). Lower is better, 0 to 1.

    A constant forecast of the base rate scores base_rate * (1 - base_rate), so
    0.25 at p = 0.5. That is the number to beat: anything above it is worse
    than saying "I don't know".
    '''
    total = 0.0
    count = 0
    for probability, outcome in zip(probabilities, outcomes):
        total += (probability - outcome) ** 2
        count += 1
    if count == 0:
        return None
    return total / count


def log_loss(probabilities, outcomes, epsilon=EPSILON):
    '''
    -mean(o*ln(p) + (1-o)*ln(1-p)).

    Punishes confident wrongness far harder than Brier. Report both: a model
    that beats the market on Brier but loses on log loss is making a few
    catastrophic calls, which for a trader is the more important fact.
    '''
    total = 0.0
    count = 0
    for probability, outcome in zip(probabilities, outcomes):
        clipped = probability
        if clipped < epsilon:
            clipped = epsilon
        if clipped > 1.0 - epsilon:
            clipped = 1.0 - epsilon

        if outcome == 1:
            total += -math.log(clipped)
        else:
            total += -math.log(1.0 - clipped)
        count += 1
    if count == 0:
        return None
    return total / count


def base_rate_benchmark(outcomes):
    '''
    The Brier score of always forecasting the observed base rate. Every other
    number in this file is only meaningful next to it.
    '''
    count = len(outcomes)
    if count == 0:
        return None
    rate = sum(outcomes) / count
    return rate * (1.0 - rate)


def score(probabilities, outcomes):
    return {
        "brier": brier(probabilities, outcomes),
        "log_loss": log_loss(probabilities, outcomes),
        "n": len(outcomes),
    }


def reliability(probabilities, outcomes, bins=10):
    '''
    Bin forecasts and compare predicted to realised frequency. Empty bins are
    omitted: a bin with two observations is noise, and plotted naively it looks
    like a calibration failure.

    Flatter than the diagonal means overconfident - the things called 90% only
    happen 70% of the time.
    '''
    buckets = {}
    for probability, outcome in zip(probabilities, outcomes):
        index = int(probability * bins)
        if index == bins:
            index = bins - 1
        if index not in buckets:
            buckets[index] = []
        buckets[index].append((probability, outcome))

    rows = []
    for index in sorted(buckets):
        pairs = buckets[index]
        mean_predicted = sum(p for p, _ in pairs) / len(pairs)
        frequency = sum(o for _, o in pairs) / len(pairs)
        rows.append(((index + 0.5) / bins, mean_predicted, frequency, len(pairs)))
    return rows
