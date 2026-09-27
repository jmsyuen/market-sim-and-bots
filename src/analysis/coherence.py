'''
Coherence arbitrage: prices that cannot all be right at once.

YES + NO must pay exactly 100 ticks. If you can BUY both for less than 100 you
have locked in the difference; if you can SELL both for more, likewise.

THE POINT IS THE FILTER, NOT THE DETECTION. Counting violations on headline
prices is easy and meaningless - most vanish once you use executable prices and
subtract costs. The reportable number is what fraction SURVIVES. That is a
market-efficiency finding, and it is a better answer than "I found lots of free
money", which any interviewer will immediately disbelieve.
'''

from src.orderbook.order import Side

FULL_SET_TICKS = 100


def check_outcome_set(books):
    '''
    Guard: the outcomes must be mutually exclusive AND exhaustive.

    Applying this arithmetic to a set that is neither is the classic way to
    report arbitrage that does not exist - "above 100 / above 200 / above 300"
    is not a partition and the sum of its prices means nothing.

    A YES/NO pair is trivially a partition, which is exactly why it is the
    right place to start.
    '''
    if len(books) < 2:
        raise ValueError("a complete outcome set needs at least two books")


def _walk(levels, quantity):
    '''
    Consume `quantity` from a depth ladder and return what it actually costs.

    NOT best_price * quantity. The second contract costs more than the first
    once the touch is exhausted, and an arb that exists for one contract
    usually evaporates by ten. Returns None if the ladder is too thin.
    '''
    remaining = quantity
    total = 0
    for price, size in levels:
        if remaining <= 0:
            break
        taken = min(remaining, size)
        total += price * taken
        remaining -= taken
    if remaining > 0:
        return None
    return total


def executable_cost_to_buy_set(books, quantity, depth_levels=10):
    '''Walk the ASK ladder of every leg.'''
    total = 0
    for book in books:
        levels = book.depth(depth_levels)[Side.SELL]
        cost = _walk(levels, quantity)
        if cost is None:
            return None
        total += cost
    return total


def executable_proceeds_to_sell_set(books, quantity, depth_levels=10):
    '''Walk the BID ladder of every leg.'''
    total = 0
    for book in books:
        levels = book.depth(depth_levels)[Side.BUY]
        proceeds = _walk(levels, quantity)
        if proceeds is None:
            return None
        total += proceeds
    return total


def max_sets_available(books, side, depth_levels=10):
    '''The binding constraint is the THINNEST leg.'''
    smallest = None
    for book in books:
        levels = book.depth(depth_levels)[side]
        available = 0
        for _, size in levels:
            available += size
        if smallest is None or available < smallest:
            smallest = available
    if smallest is None:
        return 0
    return smallest


def headline_violation(books):
    '''
    The naive check, on touch prices only, size ignored. Kept deliberately so
    the survival rate has a denominator.
    '''
    ask_sum = 0
    bid_sum = 0
    for book in books:
        if book.best_ask is None or book.best_bid is None:
            return None
        ask_sum += book.best_ask
        bid_sum += book.best_bid

    if ask_sum < FULL_SET_TICKS:
        return "buy"
    if bid_sum > FULL_SET_TICKS:
        return "sell"
    return None


def find_arbitrage(books, fee_per_leg=0.0, gas=0.0, max_size=None,
                   depth_levels=10):
    '''
    The best executable opportunity, or None.

        buy the set  : cost + costs < 100 per set
        sell the set : proceeds - costs > 100 per set

    COSTS ARE PER LEG. A two-outcome set is two fills, so the fee doubles - and
    that doubling is what kills most of the violations you will find. `gas` is
    a FIXED cost, so a small arbitrage is unprofitable even at a positive
    per-unit edge. Profit is therefore reported AT the executable size, never
    per unit.

    Size starts at the largest the depth allows and walks down, because depth
    makes the edge worse with size: an arb that fails in ten may still clear in
    two.

    NOT MODELLED, and stated rather than hidden: LEG RISK. The arithmetic
    assumes both legs fill simultaneously. In reality you lift one and the
    other moves, which is precisely why these violations persist in real
    venues.
    '''
    check_outcome_set(books)
    legs = len(books)
    target = FULL_SET_TICKS

    best = None

    for direction in ("buy", "sell"):
        if direction == "buy":
            side = Side.SELL
        else:
            side = Side.BUY

        available = max_sets_available(books, side, depth_levels)
        if max_size is not None and available > max_size:
            available = max_size
        if available <= 0:
            continue

        size = available
        while size > 0:
            fees = fee_per_leg * legs * size + gas

            if direction == "buy":
                cost = executable_cost_to_buy_set(books, size, depth_levels)
                if cost is not None:
                    profit = target * size - cost - fees
                else:
                    profit = None
            else:
                proceeds = executable_proceeds_to_sell_set(books, size, depth_levels)
                if proceeds is not None:
                    profit = proceeds - target * size - fees
                else:
                    profit = None

            if profit is not None and profit > 0:
                if best is None or profit > best["profit"]:
                    best = {
                        "direction": direction,
                        "size": size,
                        "profit": profit,
                        "profit_per_set": profit / size,
                        "fees": fees,
                    }
                break
            size -= 1

    return best


def violation_frequency(book_pairs, fee_per_leg=0.0, gas=0.0, max_size=None):
    '''
    THE HEADLINE NUMBER.

    book_pairs is a sequence of (yes_book, no_book) snapshots - in practice one
    pair per engine run, since a live book cannot be rewound.

    Returns headline / executable / net counts and the SURVIVAL RATE. Report
    that rate with its cost assumptions attached: a number without them is not
    credible.
    '''
    headline = 0
    executable = 0
    net = 0
    observed = 0

    for books in book_pairs:
        observed += 1
        flag = headline_violation(books)
        if flag is None:
            continue

        headline += 1

        gross = find_arbitrage(books, fee_per_leg=0.0, gas=0.0, max_size=max_size)
        if gross is not None:
            executable += 1

        after_costs = find_arbitrage(books, fee_per_leg=fee_per_leg, gas=gas,
                                     max_size=max_size)
        if after_costs is not None:
            net += 1

    if headline == 0:
        survival = None
    else:
        survival = net / headline

    return {
        "snapshots": observed,
        "headline": headline,
        "executable": executable,
        "net": net,
        "survival_rate": survival,
    }
