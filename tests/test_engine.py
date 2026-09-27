'''
Engine tests.

These are end-to-end: they check that the four components hold together, that a
run is reproducible, and that fills are attributed to the right side. They do
not check that the strategy is any good - that is what the experiments are for.
'''

import random
from itertools import count

import pytest

from src.market.value_process import ValueProcess
from src.orderbook.book import OrderBook
from src.orderbook.order import Side
from src.orderbook.trade import Trade
from src.orderflow.traders import InformedTrader, NoiseTrader
from src.portfolio import Portfolio
from src.sim.engine import FixedSpreadMaker, SimEngine


def build(seed=0, signal_noise=0.05, news=(), surprise_rate=0.0, jump_vol=0.0):
    book = OrderBook(seq_source=count(1))
    value_process = ValueProcess(
        p0=0.5, vol=1.0, resolve_time=1.0, seed=seed,
        news_times=news, jump_vol=jump_vol, surprise_rate=surprise_rate,
    )
    traders = [
        NoiseTrader(trader_id=1, rng=random.Random(seed + 100)),
        NoiseTrader(trader_id=2, rng=random.Random(seed + 200)),
        InformedTrader(trader_id=3, rng=random.Random(seed + 300),
                       signal_noise=signal_noise),
    ]
    maker = FixedSpreadMaker(trader_id=9, half_spread=2, size=5)
    portfolio = Portfolio()
    engine = SimEngine(
        book=book,
        value_process=value_process,
        traders=traders,
        market_maker=maker,
        portfolio=portfolio,
        rng=random.Random(seed),
        arrival_rate=200.0,
        mm_update_rate=100.0,
    )
    return engine


def test_a_run_completes_and_trades():
    engine = build()
    engine.run(until=1.0)

    assert len(engine.log) > 100
    assert len(engine.book.trades) > 0
    engine.book.assert_invariants()


def test_the_book_is_never_crossed_during_a_run():
    engine = build(seed=4)
    engine.run(until=1.0)

    for row in engine.log:
        if row["best_bid"] is not None and row["best_ask"] is not None:
            assert row["best_bid"] < row["best_ask"]


def test_every_order_id_is_unique():
    '''
    One shared counter for the whole sim. Per-trader counters collide and
    book.submit raises on the duplicate, usually thousands of events in.
    '''
    engine = build(seed=2)
    engine.run(until=1.0)

    ids = set()
    for trade in engine.book.trades:
        ids.add(trade.maker_id)
        ids.add(trade.taker_id)

    assert len(ids) > 10


def test_runs_are_reproducible():
    first = build(seed=7)
    first.run(until=1.0)

    second = build(seed=7)
    second.run(until=1.0)

    assert first.portfolio.position == second.portfolio.position
    assert first.portfolio.cash == pytest.approx(second.portfolio.cash)
    assert len(first.book.trades) == len(second.book.trades)


def test_different_seeds_diverge():
    first = build(seed=7)
    first.run(until=1.0)

    other = build(seed=8)
    other.run(until=1.0)

    assert first.portfolio.cash != other.portfolio.cash


def test_fills_are_timestamped():
    '''
    Trade.time is None unless the book has a clock. Markout needs it and cannot
    reconstruct it afterwards, so the engine lends the book its own clock.
    '''
    engine = build(seed=3)
    engine.run(until=1.0)

    for trade in engine.book.trades:
        assert trade.time is not None
        assert 0.0 <= trade.time <= 1.0


def test_passive_fills_are_attributed_to_the_opposite_side():
    '''
    We are the maker and the taker bought, so we sold. Using taker_side on the
    maker branch mirrors every position and flips the sign of all P&L without
    raising anything.
    '''
    engine = build()
    engine.market_maker.resting_ids.add(555)

    trade = Trade(price=50, quantity=4, maker_id=555, taker_id=777, seq=1,
                  taker_side=Side.BUY, time=0.1)
    engine._attribute([trade])

    assert engine.portfolio.position == -4


def test_aggressive_fills_are_attributed_to_our_own_side():
    engine = build()
    engine.market_maker.recent_ids.add(777)

    trade = Trade(price=50, quantity=4, maker_id=555, taker_id=777, seq=1,
                  taker_side=Side.BUY, time=0.1)
    engine._attribute([trade])

    assert engine.portfolio.position == 4


def test_other_peoples_fills_are_ignored():
    engine = build()

    trade = Trade(price=50, quantity=4, maker_id=111, taker_id=222, seq=1,
                  taker_side=Side.BUY, time=0.1)
    engine._attribute([trade])

    assert engine.portfolio.position == 0
    assert len(engine.portfolio.fills) == 0


def test_the_market_settles_and_ends_flat():
    engine = build(seed=6)
    engine.run(until=2.0)

    assert engine.value_process.outcome is not None
    assert engine.portfolio.position == 0


def test_news_events_reach_the_heap_and_fire():
    '''
    A jump that nobody trades on measures nothing. The engine schedules NEWS so
    an informed trader gets one immediate look before the maker requotes.
    '''
    engine = build(seed=1, news=(0.3, 0.6), jump_vol=2.0, signal_noise=0.01)
    engine.run(until=1.0)

    assert engine.value_process._news_index == 2
    assert len(engine.book.trades) > 0


def test_a_suppressed_quote_leg_is_allowed():
    '''
    A position limit pulls the side that grows the position and leaves the
    unwinding side live. Pulling both would trap the maker at its cap until
    resolution, which is the opposite of what a limit is for.

    The engine already supports this, so market_maker.py can return a None leg
    without any further engine change.
    '''
    class AskOnlyMaker:
        def __init__(self):
            self.trader_id = 9
            self.resting_ids = set()
            self.recent_ids = set()

        def quotes(self, book, portfolio, time):
            reference = book.micro_price
            if reference is None:
                return None
            return (None, min(99, round(reference) + 2), 5)

    engine = build(seed=1)
    engine.market_maker = AskOnlyMaker()
    engine.run(until=1.0)

    engine.book.assert_invariants()


def test_snapshot_carries_what_the_analysis_layer_needs():
    engine = build(seed=5)
    engine.run(until=0.2)

    required = {
        "time", "true_p", "best_bid", "best_ask", "mid", "micro_price",
        "position", "cash", "realised_pnl", "unrealised_pnl", "n_trades",
    }
    assert required.issubset(set(engine.log[-1].keys()))
