'''
Coherence arbitrage: detecting prices that cannot all be right at once.

A complete, mutually exclusive, exhaustive set of outcomes must price to
exactly 100 ticks. If you can BUY the whole set for less, you have locked in
the difference; if you can SELL it for more, likewise.

THE POINT OF THIS FILE IS THE FILTER, NOT THE DETECTION. Counting violations on
headline prices is easy and meaningless - most vanish once you use executable
prices and subtract costs. The interesting, reportable number is what fraction
SURVIVES. That is a market-efficiency finding, and it is a better answer than
"I found lots of free money", which any interviewer will immediately disbelieve.
'''

FULL_SET_TICKS = 100


def check_outcome_set(books):
    '''
    Guard: the outcomes must be mutually exclusive AND exhaustive.

    Raise if not. Applying this arithmetic to a set that is neither is the
    classic way to report arbitrage that does not exist - "will the price be
    above 100 / above 200 / above 300" is not a partition, and the sum of its
    prices means nothing.

    For a YES/NO pair this is trivially satisfied, which is exactly why the
    pair is the right place to start.
    '''
    ...


def executable_cost_to_buy_set(books, quantity):
    '''
    What it ACTUALLY costs to buy `quantity` complete sets right now.

    Walk the ASK side of each book, consuming depth level by level, and sum the
    real fill prices. NOT best_ask * quantity: the second set costs more than
    the first once the touch is exhausted, and an arb that exists for one
    contract usually evaporates by ten.

    Return None if any leg lacks the depth.
    '''
    ...


def executable_proceeds_to_sell_set(books, quantity):
    '''
    The mirror: walk the BID side of each book.
    '''
    ...


def max_sets_available(books):
    '''
    The binding constraint is the THINNEST leg. You cannot buy more complete
    sets than the smallest per-leg depth allows.
    '''
    ...


def find_arbitrage(books, fee_per_leg=0.0, gas=0.0, max_size=None):
    '''
    Returns a dict describing the best executable opportunity, or None.

    Two directions:
        buy the set  : cost + costs < 100  -> profit (100 - cost) per set
        sell the set : proceeds - costs > 100 -> profit (proceeds - 100) per set

    COSTS ARE PER LEG, not per trade. A two-outcome set is two fills, so the
    fee is doubled - and that doubling is what kills most of the violations you
    will find. On-chain venues add `gas`, a FIXED cost, which means small
    arbitrages are unprofitable even when the per-unit edge is positive. Size
    matters, so report profit at the executable size, never per unit.

    Size the trade by max_size or max_sets_available, whichever is smaller, and
    report profit at THAT size.

    NOT MODELLED, and worth saying so in the README rather than pretending
    otherwise: LEG RISK. The arithmetic assumes both legs fill simultaneously.
    In reality you lift one and the other moves, which is precisely why these
    violations persist. That is a limitation to state, not a bug to fix.
    '''
    ...


def violation_frequency(snapshots, fee_per_leg=0.0, gas=0.0):
    '''
    THE HEADLINE NUMBER. Scan a run's snapshots and report:

        headline_violations  - how often the touch prices sum away from 100
        executable_violations- how many survive walking real depth
        net_violations       - how many survive fees and gas too
        survival_rate        - net / headline

    The survival rate is the finding. Report it as a fraction with the cost
    assumptions stated, e.g. "38% of apparent violations survived executable
    prices and a 1-tick-per-leg fee". A number with its assumptions attached is
    credible; a number without them is not.
    '''
    ...
