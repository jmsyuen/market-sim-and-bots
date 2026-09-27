'''
FairValue tests.

The whole file is arithmetic on two counters, so nothing here crashes when it
is wrong - it returns a plausible number that is quietly not the posterior
mean. These assert the properties that pin it down.

NOTE: value() MUTATES. It drains the tape and decays the counters, so calling
it twice at different times gives different answers for reasons invisible at
the call site. Tests below that care about that call it deliberately.
'''

import pytest

from src.orderbook.book import OrderBook
from src.orderbook.order import Order, Side
from src.orderbook.trade import Trade
from src.strategy.fair_value import FairValue


def book_with_quotes(bid=40, ask=60, size=10):
    '''micro_price is None unless BOTH sides are populated.'''
    book = OrderBook(seq_source=iter(range(1, 10_000_000)))
    book.submit(Order(id=1, side=Side.BUY, quantity=size, price=bid, trader_id=99))
    book.submit(Order(id=2, side=Side.SELL, quantity=size, price=ask, trader_id=99))
    return book


def tape(book, taker_side, count, quantity=1):
    '''
    Append trades straight onto book.trades.

    Deliberately NOT routed through book.submit: real fills would move the
    touch, which changes micro_price, and then a test asserting "evidence moved
    the value" could not tell evidence from a moved prior. Here the prior is
    held fixed and only the evidence varies.
    '''
    for index in range(count):
        book.trades.append(Trade(
            price=50,
            quantity=quantity,
            maker_id=1000 + index,
            taker_id=2000 + index,
            seq=index,
            taker_side=taker_side,
            time=0.0,
        ))


# ----------------------------------------------------------------------
# the prior
# ----------------------------------------------------------------------


def test_no_evidence_returns_the_micro_price_exactly():
    '''
    THE LOAD-BEARING TEST. With no evidence the Beta collapses to the prior, so
    the posterior mean IS micro_p and the answer must equal micro_price on the
    nose.

    Any difference here is a units error - the /100 and *100 happen in opposite
    directions and one of them is wrong. That bug shows as a fair value of 0.5
    where you expected 50, or 5000 where you expected 50.
    '''
    book = book_with_quotes(bid=40, ask=60)
    fair = FairValue()

    assert fair.value(book) == pytest.approx(book.micro_price)


def test_the_prior_tracks_the_book():
    '''
    The prior is re-derived from the CURRENT micro-price on every call, not
    fixed at construction. Move the book and the estimate must follow.
    '''
    fair = FairValue()

    low = book_with_quotes(bid=20, ask=30)
    high = book_with_quotes(bid=70, ask=80)

    assert fair.value(low) < fair.value(high)


def test_none_micro_price_gives_none():
    empty = OrderBook(seq_source=iter(range(1, 1000)))
    one_sided = OrderBook(seq_source=iter(range(1, 1000)))
    one_sided.submit(Order(id=1, side=Side.BUY, quantity=5, price=40, trader_id=99))

    fair = FairValue()

    assert fair.value(empty) is None
    assert fair.value(one_sided) is None
    assert fair.probability(empty) is None


# ----------------------------------------------------------------------
# the evidence
# ----------------------------------------------------------------------


def test_buy_flow_moves_the_estimate_up():
    book = book_with_quotes()
    baseline = book.micro_price

    fair = FairValue(evidence_weight=0.5)
    tape(book, Side.BUY, count=20)

    assert fair.value(book) > baseline


def test_sell_flow_moves_the_estimate_down():
    book = book_with_quotes()
    baseline = book.micro_price

    fair = FairValue(evidence_weight=0.5)
    tape(book, Side.SELL, count=20)

    assert fair.value(book) < baseline


def test_balanced_flow_leaves_the_estimate_alone():
    '''
    Equal buying and selling is not evidence about the outcome, only about
    activity. If this fails, one branch of observe is weighted differently from
    the other.
    '''
    book = book_with_quotes(bid=40, ask=60)
    baseline = book.micro_price

    fair = FairValue(evidence_weight=0.5)
    tape(book, Side.BUY, count=20)
    tape(book, Side.SELL, count=20)

    assert fair.value(book) == pytest.approx(baseline, abs=0.5)


def test_size_carries_more_weight_than_count():
    '''One 10-lot sweep is more informative than one 1-lot.'''
    small_book = book_with_quotes()
    large_book = book_with_quotes()

    tape(small_book, Side.BUY, count=1, quantity=1)
    tape(large_book, Side.BUY, count=1, quantity=10)

    small = FairValue(evidence_weight=0.5).value(small_book)
    large = FairValue(evidence_weight=0.5).value(large_book)

    assert large > small


def test_a_stronger_prior_moves_less():
    '''
    The precision weighting, asserted directly. Same evidence, two prior
    strengths: the confident prior must move less.

    This is the property that makes it BAYESIAN rather than a weighted blend -
    how far you move depends on evidence relative to prior confidence, and that
    falls out of the arithmetic rather than being a rule you wrote.
    '''
    weak_book = book_with_quotes()
    strong_book = book_with_quotes()
    baseline = weak_book.micro_price

    tape(weak_book, Side.BUY, count=20)
    tape(strong_book, Side.BUY, count=20)

    weak = FairValue(prior_strength=5.0, evidence_weight=0.5).value(weak_book)
    strong = FairValue(prior_strength=200.0, evidence_weight=0.5).value(strong_book)

    assert weak - baseline > strong - baseline


# ----------------------------------------------------------------------
# the tape pointer
# ----------------------------------------------------------------------


def test_the_same_trade_is_never_counted_twice():
    '''
    REGRESSION TEST. Without advancing _last_trade_index, every call re-reads
    the whole tape and evidence grows quadratically in the number of calls -
    the prior is swamped within a few requotes.

    Nothing crashes and nothing goes out of range when this breaks. You would
    see the estimate drifting away from the book and conclude evidence_weight
    was too high.
    '''
    book = book_with_quotes()
    fair = FairValue(evidence_weight=0.5)

    tape(book, Side.BUY, count=10)

    first = fair.value(book, time=0.0)
    evidence_after_first = fair.evidence_a

    second = fair.value(book, time=0.0)

    assert fair.evidence_a == pytest.approx(evidence_after_first)
    assert second == pytest.approx(first)
    assert fair._last_trade_index == len(book.trades)


def test_only_new_trades_are_read():
    book = book_with_quotes()
    fair = FairValue(evidence_weight=0.5)

    tape(book, Side.BUY, count=5)
    fair.value(book, time=0.0)
    after_five = fair.evidence_a

    tape(book, Side.BUY, count=5)
    fair.value(book, time=0.0)

    assert fair.evidence_a == pytest.approx(after_five * 2)


# ----------------------------------------------------------------------
# decay
# ----------------------------------------------------------------------


def test_evidence_halves_every_half_life():
    book = book_with_quotes()
    fair = FairValue(evidence_weight=0.5, half_life=0.1)

    tape(book, Side.BUY, count=10)
    fair.value(book, time=0.0)
    before = fair.evidence_a

    fair.value(book, time=0.1)

    assert fair.evidence_a == pytest.approx(before * 0.5)


def test_decay_is_independent_of_call_frequency():
    '''
    Exponents add, so decaying once over dt equals decaying twice over dt/2.
    The estimate must not depend on how often the maker happens to requote -
    the same cadence-invariance property as the sqrt(dt) scaling elsewhere.
    '''
    coarse_book = book_with_quotes()
    fine_book = book_with_quotes()

    coarse = FairValue(evidence_weight=0.5, half_life=0.1)
    fine = FairValue(evidence_weight=0.5, half_life=0.1)

    tape(coarse_book, Side.BUY, count=10)
    tape(fine_book, Side.BUY, count=10)

    coarse.value(coarse_book, time=0.0)
    fine.value(fine_book, time=0.0)

    coarse.value(coarse_book, time=0.4)

    for step in range(1, 5):
        fine.value(fine_book, time=0.1 * step)

    assert fine.evidence_a == pytest.approx(coarse.evidence_a)


def test_decay_touches_both_counters_equally():
    '''
    Decaying only one counter skews the estimate one way, permanently and
    invisibly.
    '''
    book = book_with_quotes()
    fair = FairValue(evidence_weight=0.5, half_life=0.1)

    tape(book, Side.BUY, count=10)
    tape(book, Side.SELL, count=10)
    fair.value(book, time=0.0)

    fair.value(book, time=0.3)

    assert fair.evidence_a == pytest.approx(fair.evidence_b)


def test_time_going_backwards_is_a_no_op():
    book = book_with_quotes()
    fair = FairValue(evidence_weight=0.5, half_life=0.1)

    tape(book, Side.BUY, count=10)
    fair.value(book, time=0.5)
    before = fair.evidence_a

    fair.value(book, time=0.2)

    assert fair.evidence_a == pytest.approx(before)


# ----------------------------------------------------------------------
# range and units
# ----------------------------------------------------------------------


def test_the_estimate_stays_on_the_tick_grid():
    '''Lopsided evidence can push the posterior past 1..99.'''
    for side in (Side.BUY, Side.SELL):
        book = book_with_quotes(bid=1, ask=99)
        fair = FairValue(prior_strength=1.0, evidence_weight=50.0)
        tape(book, side, count=200, quantity=10)

        estimate = fair.value(book)
        assert 1 <= estimate <= 99


def test_probability_is_value_over_one_hundred():
    book = book_with_quotes()
    fair = FairValue(evidence_weight=0.5)
    tape(book, Side.BUY, count=10)

    probability = fair.probability(book, time=0.0)

    fresh = FairValue(evidence_weight=0.5)
    fresh_book = book_with_quotes()
    tape(fresh_book, Side.BUY, count=10)
    ticks = fresh.value(fresh_book, time=0.0)

    assert probability == pytest.approx(ticks / 100.0)
    assert 0.0 < probability < 1.0


def test_value_returns_a_float_not_a_rounded_tick():
    '''
    The maker rounds once, in quotes(). Rounding here too would lose sub-tick
    precision in the skew and half-spread arithmetic.
    '''
    book = book_with_quotes(bid=40, ask=61)
    fair = FairValue()

    estimate = fair.value(book)

    assert isinstance(estimate, float)
    assert estimate != round(estimate)
