'''
MarketMaker tests.

A market maker is never "correct" - it is better or worse than the version
without a feature. So these assert MECHANISMS, not outcomes.
'''

import math

import pytest

from src.orderbook.book import OrderBook
from src.orderbook.order import Order, Side
from src.portfolio import Portfolio
from src.sim.engine import FixedSpreadMaker
from src.strategy.market_maker import MarketMaker


def book_with_quotes(bid=40, ask=60, size=10):
    book = OrderBook(seq_source=iter(range(1, 1_000_000)))
    book.submit(Order(id=1, side=Side.BUY, quantity=size, price=bid, trader_id=99))
    book.submit(Order(id=2, side=Side.SELL, quantity=size, price=ask, trader_id=99))
    return book


def portfolio_at(position):
    portfolio = Portfolio()
    portfolio.position = position
    return portfolio


def plain_maker(**kwargs):
    defaults = dict(trader_id=9, base_half_spread=3, size=5, max_position=None)
    defaults.update(kwargs)
    return MarketMaker(**defaults)


def test_all_features_off_reproduces_the_control():
    '''
    LOAD-BEARING. Without this, a later difference could be a changed code path
    rather than the strategy, and every comparison inherits the doubt.
    '''
    book = book_with_quotes()
    flat = portfolio_at(0)

    control = FixedSpreadMaker(trader_id=9, half_spread=3, size=5)

    assert plain_maker().quotes(book, flat, 0.0) == control.quotes(book, flat, 0.0)


def test_no_quotes_without_a_reference():
    empty = OrderBook(seq_source=iter(range(1, 1000)))
    assert plain_maker().quotes(empty, portfolio_at(0), 0.0) is None


def test_long_inventory_moves_both_quotes_down():
    '''
    THE MECHANISM. Skew shifts the pair; it does not widen one side. Widening
    would change the spread and leave the inventory target untouched.
    '''
    book = book_with_quotes()
    maker = plain_maker(risk_aversion=0.05)

    flat_bid, flat_ask, _ = maker.quotes(book, portfolio_at(0), 0.0)
    long_bid, long_ask, _ = plain_maker(risk_aversion=0.05).quotes(
        book, portfolio_at(20), 0.0)

    assert long_bid < flat_bid
    assert long_ask < flat_ask


def test_short_inventory_moves_both_quotes_up():
    book = book_with_quotes()

    flat_bid, flat_ask, _ = plain_maker(risk_aversion=0.05).quotes(
        book, portfolio_at(0), 0.0)
    short_bid, short_ask, _ = plain_maker(risk_aversion=0.05).quotes(
        book, portfolio_at(-20), 0.0)

    assert short_bid > flat_bid
    assert short_ask > flat_ask


def test_inventory_does_not_change_the_spread():
    '''The companion to the two above: a shift, not a widen.'''
    book = book_with_quotes()

    flat_bid, flat_ask, _ = plain_maker(risk_aversion=0.05).quotes(
        book, portfolio_at(0), 0.0)
    long_bid, long_ask, _ = plain_maker(risk_aversion=0.05).quotes(
        book, portfolio_at(20), 0.0)

    assert (flat_ask - flat_bid) == (long_ask - long_bid)


def test_zero_risk_aversion_ignores_inventory():
    book = book_with_quotes()

    flat = plain_maker(risk_aversion=0.0).quotes(book, portfolio_at(0), 0.0)
    loaded = plain_maker(risk_aversion=0.0).quotes(book, portfolio_at(50), 0.0)

    assert flat == loaded


def test_skew_fades_towards_resolution():
    '''The (T - t) term: less time left means less time for inventory to hurt.'''
    book = book_with_quotes()

    early = plain_maker(risk_aversion=0.05, decision_time=1.0)
    late = plain_maker(risk_aversion=0.05, decision_time=1.0)

    early_bid, _, _ = early.quotes(book, portfolio_at(20), 0.0)
    late_bid, _, _ = late.quotes(book, portfolio_at(20), 0.95)

    assert late_bid > early_bid


def test_volatility_estimate_rises_on_movement_and_decays_when_still():
    maker = plain_maker(vol_half_life=0.05)

    maker._update_volatility(50.0, 0.0)
    maker._update_volatility(60.0, 0.01)
    moved = maker.vol_estimate
    assert moved > 0.0

    for step in range(1, 40):
        maker._update_volatility(60.0, 0.01 + 0.01 * step)

    assert maker.vol_estimate < moved


def test_volatility_estimate_is_independent_of_sampling_rate():
    '''
    LOAD-BEARING and silent when broken. Without the sqrt(dt) normalisation,
    requoting twice as often halves the measured volatility, so the spread
    narrows exactly when you are watching most closely.

    NOTE HOW THE TWO PATHS ARE CONSTRUCTED. The fine path's step is the coarse
    step times sqrt(1/2), not half of it. The normalisation is calibrated to
    DIFFUSIVE scaling, where a move grows as sqrt(time), so that is the path
    shape it must be invariant to.

    Feeding it a straight line instead - equal moves per unit time - gives
    estimates that differ by exactly sqrt(2), because a deterministic trend has
    move proportional to dt, not sqrt(dt). That is not a bug: it is the
    estimator correctly reporting that a trending price is less VOLATILE than a
    diffusing one covering the same distance. Worth knowing, because it means
    this measures diffusion, not drift.
    '''
    coarse_step = 1.0
    fine_step = coarse_step * math.sqrt(0.5)

    coarse = plain_maker(vol_half_life=0.5)
    fine = plain_maker(vol_half_life=0.5)

    for step in range(21):
        coarse._update_volatility(50.0 + coarse_step * step, step * 0.02)

    for step in range(41):
        fine._update_volatility(50.0 + fine_step * step, step * 0.01)

    assert fine.vol_estimate == pytest.approx(coarse.vol_estimate, rel=0.1)


def test_volatility_widens_the_spread():
    book = book_with_quotes()
    maker = plain_maker(vol_sensitivity=2.0)

    calm_bid, calm_ask, _ = maker.quotes(book, portfolio_at(0), 0.0)

    maker._update_volatility(50.0, 0.001)
    maker._update_volatility(90.0, 0.002)
    wild_bid, wild_ask, _ = maker.quotes(book, portfolio_at(0), 0.003)

    assert (wild_ask - wild_bid) > (calm_ask - calm_bid)


def test_cost_floor_binds():
    book = book_with_quotes()
    maker = plain_maker(base_half_spread=1, fee_per_contract=6)

    bid, ask, _ = maker.quotes(book, portfolio_at(0), 0.0)

    assert (ask - bid) >= 12


def test_position_limit_suppresses_only_the_growing_side():
    '''
    Pulling both legs at the cap traps the maker there until resolution, which
    is the opposite of what a limit is for.
    '''
    book = book_with_quotes()

    long_bid, long_ask, _ = plain_maker(max_position=10).quotes(
        book, portfolio_at(10), 0.0)
    assert long_bid is None
    assert long_ask is not None

    short_bid, short_ask, _ = plain_maker(max_position=10).quotes(
        book, portfolio_at(-10), 0.0)
    assert short_bid is not None
    assert short_ask is None


def test_scheduled_news_widens_only_ahead_of_the_event():
    '''A lead time, not a window: after the jump the information is public.'''
    maker = plain_maker(scheduled_news_times=(0.5,), news_buffer=0.1,
                        news_widening=5.0)

    assert maker._half_spread(0.30) == 3.0     # too early
    assert maker._half_spread(0.45) == 8.0     # inside the lead
    assert maker._half_spread(0.55) == 3.0     # already happened


def test_quotes_never_leave_the_tick_grid():
    for bid, ask in [(1, 3), (97, 99), (1, 99)]:
        book = book_with_quotes(bid=bid, ask=ask)
        for position in [-50, 0, 50]:
            quote = plain_maker(risk_aversion=0.1).quotes(
                book, portfolio_at(position), 0.0)
            if quote is None:
                continue
            for tick in (quote[0], quote[1]):
                if tick is not None:
                    assert 1 <= tick <= 99
