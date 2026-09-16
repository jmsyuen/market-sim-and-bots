import random
from itertools import count

import pytest
from src.orderbook.book import OrderBook
from src.orderbook.order import Order, OrderType, Side, TimeInForce

'''
Useful tests in bash
python -m pytest -v                 # one line per test
python -m pytest -q                 # compact, good once the suite is large
python -m pytest --lf               # rerun only last session's failures
python -m pytest -m slow            # the 2M-operation fuzz run
'''


# ----------------------------------------------------------------------
# factories — fix type and tif so a test body contains no enum noise
# ----------------------------------------------------------------------

def limit(order_id, side, price, quantity, trader_id=None):
    """A GTC limit order. IDs passed explicitly so tests can assert on them."""
    return Order(
        id=order_id,
        side=side,
        price=price,
        quantity=quantity,
        type=OrderType.LIMIT,
        tif=TimeInForce.GTC,
        trader_id=trader_id,
    )


def market(order_id, side, quantity, trader_id=None):
    """A market order: no price, never rests. MARKET+GTC is rejected by Order."""
    return Order(
        id=order_id,
        side=side,
        quantity=quantity,
        type=OrderType.MARKET,
        tif=TimeInForce.IOC,
        trader_id=trader_id,
    )


def ioc(order_id, side, price, quantity, trader_id=None):
    """Immediate-or-cancel: fill what crosses now, discard the remainder."""
    return Order(
        id=order_id,
        side=side,
        price=price,
        quantity=quantity,
        type=OrderType.LIMIT,
        tif=TimeInForce.IOC,
        trader_id=trader_id,
    )


def fok(order_id, side, price, quantity, trader_id=None):
    """Fill-or-kill: fill entirely or touch nothing at all."""
    return Order(
        id=order_id,
        side=side,
        price=price,
        quantity=quantity,
        type=OrderType.LIMIT,
        tif=TimeInForce.FOK,
        trader_id=trader_id,
    )


def level_ids(book, side, price):
    """Order ids at a level, front (oldest) to back.

    THE ONLY place in this file that touches level internals. When the deque
    becomes a PriceLevel linked list for O(1) cancel, this function changes and
    nothing else in the suite does.
    """
    book_side = book._book_for(side)
    if price not in book_side:
        return []

    ids = []
    for order in book_side[price]:
        ids.append(order.id)
    return ids


@pytest.fixture
def book():
    # a fresh counter per test, so seq values are deterministic and a failing
    # test reports the same numbers every run.
    #
    # the post-yield assert_invariants runs after EVERY test that uses this
    # fixture, so structural corruption surfaces at the test that caused it
    # rather than three tests later.
    fresh = OrderBook(seq_source=count(1))
    yield fresh
    fresh.assert_invariants()


# ======================================================================
# PASS 1 — resting, priority, id uniqueness
# ======================================================================

def test_single_order_rests(book):
    order = limit(1, Side.BUY, 40, 10)
    book.submit(order)

    assert book.best_bid == 40
    assert len(book.bids) == 1
    assert book.resting[1] is order


def test_better_price_becomes_best_bid(book):
    book.submit(limit(1, Side.BUY, 40, 10))
    book.submit(limit(2, Side.BUY, 42, 10))

    assert book.best_bid == 42
    assert len(book.bids) == 2


def test_same_price_queues_fifo(book):
    # the only test before Pass 4 that catches an appendleft/append mix-up
    book.submit(limit(1, Side.BUY, 40, 10))
    book.submit(limit(2, Side.BUY, 40, 10))

    assert level_ids(book, Side.BUY, 40) == [1, 2]   # front = oldest = fills first


def test_seq_assigned_on_arrival(book):
    first = limit(1, Side.BUY, 40, 10)
    second = limit(2, Side.BUY, 41, 10)
    book.submit(first)
    book.submit(second)

    assert first.seq < second.seq


def test_duplicate_id_rejected(book):
    book.submit(limit(1, Side.BUY, 40, 10))

    with pytest.raises(ValueError):
        book.submit(limit(1, Side.SELL, 60, 5))


# ======================================================================
# PASS 2 — accessors
# ======================================================================

def test_micro_price_leans_toward_thin_side(book):
    book.submit(limit(1, Side.BUY, 40, 300))
    book.submit(limit(2, Side.SELL, 42, 100))

    # I = 300 / 400 = 0.75  ->  micro = 40 + 0.75 * 2 = 41.5
    assert book.micro_price == 41.5
    assert book.mid == 41.0


def test_micro_price_inverts_correctly(book):
    # the mirror case. a symmetric 300/300 book would pass even with the
    # imbalance the wrong way round, so this asymmetric pair is the real test.
    book.submit(limit(1, Side.BUY, 40, 100))
    book.submit(limit(2, Side.SELL, 42, 300))

    assert book.micro_price == 40.5


def test_accessors_none_on_empty_book(book):
    assert book.best_bid is None
    assert book.best_ask is None
    assert book.mid is None
    assert book.spread is None
    assert book.micro_price is None


def test_accessors_none_with_one_side_only(book):
    book.submit(limit(1, Side.BUY, 40, 10))

    assert book.best_bid == 40
    assert book.best_ask is None
    assert book.mid is None
    assert book.spread is None
    assert book.micro_price is None


def test_size_at_missing_level_is_zero(book):
    book.submit(limit(1, Side.BUY, 40, 10))

    assert book.size_at(Side.BUY, 40) == 10
    assert book.size_at(Side.BUY, 39) == 0
    assert book.size_at(Side.SELL, 40) == 0


def test_depth_is_best_first(book):
    book.submit(limit(1, Side.BUY, 38, 10))
    book.submit(limit(2, Side.BUY, 40, 20))
    book.submit(limit(3, Side.SELL, 44, 30))
    book.submit(limit(4, Side.SELL, 42, 40))

    snapshot = book.depth()

    assert snapshot[Side.BUY] == [(40, 20), (38, 10)]
    assert snapshot[Side.SELL] == [(42, 40), (44, 30)]


# ======================================================================
# PASS 3 — cancel
# ======================================================================

def test_cancel_removes_order(book):
    book.submit(limit(1, Side.BUY, 40, 10))

    assert book.cancel(1) is True
    assert book.best_bid is None
    assert book.resting == {}
    assert len(book.bids) == 0


def test_cancel_falls_back_to_next_level(book):
    # the stale-empty-level test. if cancel leaves an empty deque behind,
    # _best_of reports a price with no size and the next _match raises
    # IndexError on level[0]. a one-level book cannot show this.
    book.submit(limit(1, Side.BUY, 40, 10))
    book.submit(limit(2, Side.BUY, 38, 10))

    assert book.cancel(1) is True
    assert book.best_bid == 38
    assert book.size_at(Side.BUY, 40) == 0
    assert len(book.bids) == 1


def test_cancel_leaves_siblings(book):
    book.submit(limit(1, Side.BUY, 40, 10))
    book.submit(limit(2, Side.BUY, 40, 7))

    assert book.cancel(1) is True
    assert level_ids(book, Side.BUY, 40) == [2]
    assert book.size_at(Side.BUY, 40) == 7
    assert 1 not in book.resting


def test_cancel_unknown_id_returns_false(book):
    # cancels race fills in real flow, so a miss is normal, not an error
    assert book.cancel(99) is False


def test_cancel_twice_returns_false(book):
    book.submit(limit(1, Side.BUY, 40, 10))

    assert book.cancel(1) is True
    assert book.cancel(1) is False


def test_cancelled_order_does_not_fill(book):
    book.submit(limit(1, Side.BUY, 40, 10))
    book.cancel(1)

    trades = book.submit(limit(2, Side.SELL, 40, 10))

    assert trades == []
    assert book.best_bid is None
    assert book.best_ask == 40


# ======================================================================
# PASS 4 — the matching walk
# ======================================================================

def test_incoming_takes_resting_price(book):
    # price improvement. a buy limit at 45 hitting a resting ask at 42 trades
    # at 42. trading at 45 silently hands the taker's edge to the maker and
    # corrupts every P&L number downstream.
    book.submit(limit(1, Side.SELL, 42, 10))

    trades = book.submit(limit(2, Side.BUY, 45, 10))

    assert len(trades) == 1
    assert trades[0].price == 42
    assert trades[0].quantity == 10


def test_full_fill_empties_book(book):
    book.submit(limit(1, Side.SELL, 42, 10))
    book.submit(limit(2, Side.BUY, 42, 10))

    assert book.best_bid is None
    assert book.best_ask is None
    assert book.resting == {}


def test_partial_fill_keeps_queue_position(book):
    # a resting order that partially fills stays at the FRONT with reduced
    # remaining — it does not go to the back of the queue.
    first = limit(1, Side.SELL, 42, 10)
    second = limit(2, Side.SELL, 42, 10)
    book.submit(first)
    book.submit(second)

    trades = book.submit(limit(3, Side.BUY, 42, 4))

    assert len(trades) == 1
    assert trades[0].maker_id == 1
    assert first.remaining == 6
    assert level_ids(book, Side.SELL, 42) == [1, 2]
    assert book.size_at(Side.SELL, 42) == 16


def test_incoming_remainder_rests(book):
    book.submit(limit(1, Side.SELL, 42, 5))

    trades = book.submit(limit(2, Side.BUY, 42, 12))

    assert len(trades) == 1
    assert trades[0].quantity == 5
    assert book.best_ask is None
    assert book.best_bid == 42                  # remainder rests at its OWN price
    assert book.size_at(Side.BUY, 42) == 7


def test_sweep_is_best_first(book):
    # asks submitted worst-price-first on purpose: insertion order must not
    # determine fill order. if the side iteration is inverted, this fails.
    book.submit(limit(1, Side.SELL, 43, 5))
    book.submit(limit(2, Side.SELL, 42, 5))

    trades = book.submit(limit(3, Side.BUY, 43, 10))

    assert len(trades) == 2
    prices = []
    for trade in trades:
        prices.append(trade.price)
    assert prices == [42, 43]


def test_sweep_stops_at_limit(book):
    book.submit(limit(1, Side.SELL, 42, 5))
    book.submit(limit(2, Side.SELL, 44, 5))

    trades = book.submit(limit(3, Side.BUY, 43, 10))

    assert len(trades) == 1
    assert trades[0].price == 42
    assert book.best_ask == 44                  # 44 never crossed 43
    assert book.best_bid == 43                  # remainder rested
    assert book.size_at(Side.BUY, 43) == 5
    assert book.spread == 1


def test_time_priority_within_level(book):
    book.submit(limit(1, Side.SELL, 42, 5))
    book.submit(limit(2, Side.SELL, 42, 5))

    trades = book.submit(limit(3, Side.BUY, 42, 5))

    assert len(trades) == 1
    assert trades[0].maker_id == 1              # oldest fills first
    assert level_ids(book, Side.SELL, 42) == [2]


def test_no_match_when_not_crossing(book):
    book.submit(limit(1, Side.BUY, 40, 10))

    trades = book.submit(limit(2, Side.SELL, 42, 10))

    assert trades == []
    assert book.best_bid == 40
    assert book.best_ask == 42
    assert book.spread == 2


def test_taker_side_buy_aggresses(book):
    # taker_side has no default so a forgotten argument raises. a WRONG one is
    # silent and inverts every markout sign, so both directions get a test.
    book.submit(limit(1, Side.SELL, 42, 10))

    trades = book.submit(limit(2, Side.BUY, 42, 10))

    assert trades[0].taker_side is Side.BUY
    assert trades[0].maker_id == 1
    assert trades[0].taker_id == 2


def test_taker_side_sell_aggresses(book):
    book.submit(limit(1, Side.BUY, 42, 10))

    trades = book.submit(limit(2, Side.SELL, 42, 10))

    assert trades[0].taker_side is Side.SELL
    assert trades[0].maker_id == 1
    assert trades[0].taker_id == 2


def test_returned_trades_are_this_call_only(book):
    book.submit(limit(1, Side.SELL, 42, 5))
    book.submit(limit(2, Side.SELL, 42, 5))

    first_call = book.submit(limit(3, Side.BUY, 42, 5))
    second_call = book.submit(limit(4, Side.BUY, 42, 5))

    assert len(first_call) == 1
    assert len(second_call) == 1
    assert len(book.trades) == 2                # the book keeps the whole history


def test_trade_seq_strictly_increases(book):
    book.submit(limit(1, Side.SELL, 42, 5))
    book.submit(limit(2, Side.SELL, 43, 5))

    trades = book.submit(limit(3, Side.BUY, 43, 10))

    assert len(trades) == 2
    assert trades[0].seq < trades[1].seq


def test_taker_seq_precedes_its_trades(book):
    # time priority is earned on ARRIVAL, so the taker's seq is stamped before
    # any fill it causes.
    book.submit(limit(1, Side.SELL, 42, 10))
    taker = limit(2, Side.BUY, 42, 10)

    trades = book.submit(taker)

    assert taker.seq < trades[0].seq


# ======================================================================
# PASS 5 — order types and self-trade prevention
# ======================================================================

def test_market_sweeps_best_first(book):
    book.submit(limit(1, Side.SELL, 43, 5))
    book.submit(limit(2, Side.SELL, 42, 5))

    trades = book.submit(market(3, Side.BUY, 10))

    prices = []
    for trade in trades:
        prices.append(trade.price)
    assert prices == [42, 43]


def test_market_discards_remainder(book):
    book.submit(limit(1, Side.SELL, 42, 3))

    trades = book.submit(market(2, Side.BUY, 10))

    assert len(trades) == 1
    assert trades[0].quantity == 3
    assert book.best_bid is None                # nothing rested
    assert book.resting == {}


def test_market_on_empty_book_returns_nothing(book):
    trades = book.submit(market(1, Side.BUY, 10))

    assert trades == []
    assert book.resting == {}


def test_ioc_fills_then_discards(book):
    book.submit(limit(1, Side.SELL, 42, 5))

    trades = book.submit(ioc(2, Side.BUY, 42, 10))

    assert len(trades) == 1
    assert trades[0].quantity == 5
    assert book.best_bid is None
    assert book.best_ask is None


def test_ioc_no_fill_rests_nothing(book):
    book.submit(limit(1, Side.SELL, 44, 5))

    trades = book.submit(ioc(2, Side.BUY, 42, 5))

    assert trades == []
    assert book.best_bid is None
    assert book.best_ask == 44


def test_fok_fills_completely(book):
    book.submit(limit(1, Side.SELL, 42, 10))

    trades = book.submit(fok(2, Side.BUY, 42, 10))

    assert len(trades) == 1
    assert trades[0].quantity == 10
    assert book.resting == {}


def test_fok_spans_levels(book):
    book.submit(limit(1, Side.SELL, 42, 5))
    book.submit(limit(2, Side.SELL, 43, 5))

    trades = book.submit(fok(3, Side.BUY, 43, 10))

    assert len(trades) == 2
    total = 0
    for trade in trades:
        total += trade.quantity
    assert total == 10


def test_fok_insufficient_depth_touches_nothing(book):
    # "touches nothing" is stronger than "returns no trades". a buggy FOK that
    # partially fills and then bails would pass a return-value-only assertion.
    resting = limit(1, Side.SELL, 42, 5)
    book.submit(resting)

    trades = book.submit(fok(2, Side.BUY, 42, 10))

    assert trades == []
    assert book.trades == []
    assert resting.remaining == 5
    assert book.size_at(Side.SELL, 42) == 5
    assert 2 not in book.resting


def test_fok_ignores_depth_beyond_limit(book):
    # total depth is 10 but only 5 of it is priced at or through the limit.
    # an _available_quantity that forgets the price check fills this wrongly.
    book.submit(limit(1, Side.SELL, 42, 5))
    book.submit(limit(2, Side.SELL, 44, 5))

    trades = book.submit(fok(3, Side.BUY, 43, 10))

    assert trades == []
    assert book.trades == []
    assert book.size_at(Side.SELL, 42) == 5
    assert book.size_at(Side.SELL, 44) == 5


def test_fok_excludes_own_depth(book):
    # same-owner depth is CANCELLED by _match, not filled, so it is not
    # available depth. counting it lets an FOK pass the check and then
    # under-fill, which is exactly what FOK exists to prevent.
    mine = limit(1, Side.SELL, 42, 10, trader_id=7)
    book.submit(mine)

    trades = book.submit(fok(2, Side.BUY, 42, 10, trader_id=7))

    assert trades == []
    assert book.trades == []
    assert mine.remaining == 10
    assert 1 in book.resting                    # rejected before _match ran


def test_stp_cancels_resting_and_continues(book):
    # cancel-oldest, not reject-incoming: the aggressive order is a CURRENT
    # intent, the resting one is stale.
    mine = limit(1, Side.SELL, 42, 5, trader_id=7)
    theirs = limit(2, Side.SELL, 42, 5, trader_id=8)
    book.submit(mine)
    book.submit(theirs)

    trades = book.submit(limit(3, Side.BUY, 42, 5, trader_id=7))

    assert len(trades) == 1
    assert trades[0].maker_id == 2              # walked past mine, filled theirs
    assert 1 not in book.resting                # mine was cancelled
    assert mine.remaining == 5                  # cancelled, not filled
    assert book.size_at(Side.SELL, 42) == 0


def test_stp_ignores_none_trader_ids(book):
    # regression test for the trader_id default. with a default of 0 instead of
    # None, every order in the suite shares an owner and STP kills all matching.
    book.submit(limit(1, Side.SELL, 42, 5))

    trades = book.submit(limit(2, Side.BUY, 42, 5))

    assert len(trades) == 1
    assert trades[0].quantity == 5


def test_stp_does_not_fire_across_different_owners(book):
    book.submit(limit(1, Side.SELL, 42, 5, trader_id=7))

    trades = book.submit(limit(2, Side.BUY, 42, 5, trader_id=8))

    assert len(trades) == 1
    assert trades[0].maker_id == 1


# ======================================================================
# FUZZ — the invariant hunt
# ======================================================================

# narrow tick range on purpose. drawn from 1..99 the book almost never crosses
# and the matching walk is never exercised. this is the single biggest
# determinant of whether fuzz finds anything.
TICK_LOW = 1
TICK_HIGH = 15

TRADER_IDS = (None, 1, 2, 3)

# these weights are TUNED, not guessed. cancels outnumber fills in real flow,
# but a fuzzer is a state-space explorer, not a realism simulator: at a 25%
# cancel weight the book drains to ~3 resting orders and the FIFO queues,
# interior-removal path and multi-level sweeps stop being exercised at all.
# at 6% the book holds ~22 orders across ~7 levels (3 per level), and over
# 100k operations this mix produces roughly:
#   58k trades, 11k multi-level sweeps, 10k STP firings,
#   5k landed cancels of which ~60% remove from the INTERIOR of a queue
#     (the O(n) deque path, and the case the PriceLevel refactor must preserve)
# re-measure if you change these — the numbers move a lot.
OPS = ("gtc", "cancel", "ioc", "market", "fok")
OP_WEIGHTS = (80, 6, 10, 8, 7)

# a safety rail on assert_invariants, which walks the whole book after every
# operation. with the weights above the book averages ~22 orders so this cap
# rarely binds; it exists so a future weight change can't silently turn the
# run quadratic.
MAX_RESTING = 80

# fraction of cancels aimed at an id that was never resting. cancels race fills
# in real flow, so the miss path is not an edge case and needs coverage too.
CANCEL_MISS_RATE = 0.08


def _random_order(rng, order_id, op):
    side = rng.choice((Side.BUY, Side.SELL))
    quantity = rng.randint(1, 10)
    trader_id = rng.choice(TRADER_IDS)

    if op == "market":
        return Order(
            id=order_id,
            side=side,
            quantity=quantity,
            type=OrderType.MARKET,
            tif=TimeInForce.IOC,
            trader_id=trader_id,
        )

    if op == "gtc":
        tif = TimeInForce.GTC
    elif op == "ioc":
        tif = TimeInForce.IOC
    else:
        tif = TimeInForce.FOK

    return Order(
        id=order_id,
        side=side,
        price=rng.randint(TICK_LOW, TICK_HIGH),
        quantity=quantity,
        type=OrderType.LIMIT,
        tif=tif,
        trader_id=trader_id,
    )


def run_fuzz(n_ops, seed, check_every=1):
    """Apply n_ops random operations, asserting invariants as it goes.

    A failure reports (seed, op_index). Because every draw comes from this one
    seeded rng in a fixed order, re-running run_fuzz(op_index + 1, seed)
    reproduces it exactly — the seed IS the operation log.
    """
    rng = random.Random(seed)
    fuzz_book = OrderBook(seq_source=count(1))
    ids = count(1)
    submitted = []                  # EVERY order, not just the resting ones

    for op_index in range(n_ops):
        if len(fuzz_book.resting) >= MAX_RESTING:
            op = "cancel"
        else:
            op = rng.choices(OPS, weights=OP_WEIGHTS, k=1)[0]

        if op == "cancel":
            # sampled from book.resting, not from the submitted history.
            # building this list is O(book), which is cheap ONLY because
            # MAX_RESTING caps it — sampling from a growing submitted[] instead
            # means ~94% of cancels miss and the interior-removal path is
            # barely touched.
            if len(fuzz_book.resting) > 0 and rng.random() > CANCEL_MISS_RATE:
                target_id = rng.choice(list(fuzz_book.resting.keys()))
                assert fuzz_book.cancel(target_id) is True, (
                    f"seed={seed} op={op_index}: cancel({target_id}) returned "
                    f"False for an order that was resting"
                )
            else:
                # negative ids can never collide with a real one
                assert fuzz_book.cancel(-op_index - 1) is False, (
                    f"seed={seed} op={op_index}: cancel of an unknown id "
                    f"returned True"
                )
        else:
            order = _random_order(rng, next(ids), op)
            submitted.append(order)

            # price improvement, checked structurally.
            #
            # the first fill of any submit happens at the best opposite price,
            # so trades[0].price must EQUAL the best opposite price recorded
            # just before. the one thing that breaks this is the STP branch,
            # which can consume a level without trading — but STP cannot fire
            # when the taker's trader_id is None (the guard requires the
            # RESTING id to be non-None and equal to it), so restricting the
            # check to those takers makes it exact. roughly a quarter of
            # submits qualify, which over 2M operations is ample.
            best_opposite = fuzz_book._best_of(fuzz_book._book_against(order.side))
            trades = fuzz_book.submit(order)

            if order.trader_id is None and len(trades) > 0:
                assert trades[0].price == best_opposite, (
                    f"seed={seed} op={op_index}: first fill printed at "
                    f"{trades[0].price} but the best opposite price was "
                    f"{best_opposite} — the taker's price was used instead "
                    f"of the maker's"
                )

        if op_index % check_every == 0 or op_index == n_ops - 1:
            try:
                fuzz_book.assert_invariants()
            except AssertionError as failure:
                raise AssertionError(
                    f"seed={seed} op_index={op_index} op={op}: {failure}"
                ) from failure

    # share conservation. every trade fills exactly one maker and one taker, so
    # each unit of traded quantity is counted twice on the order side. FOK
    # rejections and STP cancels contribute zero to both sides, so the identity
    # holds regardless of the op mix.
    #
    # this cannot live in assert_invariants: it spans the book AND every order
    # ever submitted, and the book only keeps the resting ones.
    total_filled = 0
    for order in submitted:
        total_filled += order.filled_quantity

    total_traded = 0
    for trade in fuzz_book.trades:
        total_traded += trade.quantity

    assert total_filled == 2 * total_traded, (
        f"seed={seed}: shares not conserved — orders report {total_filled} "
        f"filled, trades report {total_traded} x 2 = {2 * total_traded}"
    )


def test_fuzz_short():
    # runs on every `pytest` invocation
    run_fuzz(n_ops=5_000, seed=0)


@pytest.mark.slow
def test_fuzz_long():
    # 20 seeds x 100k = 2,000,000 operations. run with `pytest -m slow`.
    for seed in range(20):
        run_fuzz(n_ops=100_000, seed=seed)
