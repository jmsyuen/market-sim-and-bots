'''
Trader tests.

The most important one is structural: NoiseTrader must have no way to receive a
probability. That is asserted against the signature rather than the behaviour,
so it cannot go stale.
'''

import inspect
import random

import pytest

from src.orderbook.book import OrderBook
from src.orderbook.order import Order, OrderType, Side, TimeInForce
from src.orderflow.traders import InformedTrader, NoiseTrader


def book_with_quotes(bid=40, ask=60, size=10):
    book = OrderBook(seq_source=iter(range(1, 10_000_000)))
    book.submit(Order(id=1, side=Side.BUY, quantity=size, price=bid, trader_id=99))
    book.submit(Order(id=2, side=Side.SELL, quantity=size, price=ask, trader_id=99))
    return book


def test_noise_trader_cannot_receive_a_probability():
    '''
    A structural test. If someone later adds a true_p argument "just for
    debugging", the uninformed flow stops being uninformed and the whole
    adverse-selection result becomes meaningless.
    '''
    parameters = inspect.signature(NoiseTrader.generate_order).parameters
    assert list(parameters) == ["self", "book", "order_id"]


def test_informed_buys_when_its_view_is_above_the_book():
    trader = InformedTrader(trader_id=1, rng=random.Random(0), signal_noise=0.0)
    order = trader.generate_order(book_with_quotes(), order_id=10, observed_p=0.9)

    assert order.side is Side.BUY


def test_informed_sells_when_its_view_is_below_the_book():
    trader = InformedTrader(trader_id=1, rng=random.Random(0), signal_noise=0.0)
    order = trader.generate_order(book_with_quotes(), order_id=10, observed_p=0.1)

    assert order.side is Side.SELL


def test_informed_stands_down_inside_the_threshold():
    trader = InformedTrader(trader_id=1, rng=random.Random(0), signal_noise=0.0,
                            edge_threshold=5.0)
    book = book_with_quotes(bid=49, ask=51)
    order = trader.generate_order(book, order_id=10, observed_p=0.50)

    assert order is None


def test_informed_always_aggresses():
    '''
    If the informed trader ever rests, it becomes a liquidity provider and no
    adverse selection is transferred to the maker at all. This is the single
    most common reason the experiment shows nothing.
    '''
    trader = InformedTrader(trader_id=1, rng=random.Random(0), signal_noise=0.2)

    for step in range(500):
        probability = (step % 99 + 1) / 100
        order = trader.generate_order(book_with_quotes(), order_id=step + 10,
                                      observed_p=probability)
        if order is not None:
            assert order.tif is not TimeInForce.GTC


def test_informed_size_grows_with_conviction():
    trader = InformedTrader(trader_id=1, rng=random.Random(0), signal_noise=0.0,
                            edge_threshold=2.0, max_size=10)
    book = book_with_quotes(bid=49, ask=51)

    small = trader.generate_order(book, order_id=10, observed_p=0.55)
    large = trader.generate_order(book, order_id=11, observed_p=0.95)

    assert large.quantity > small.quantity
    assert large.quantity <= 10


def test_informed_returns_none_without_a_reference():
    trader = InformedTrader(trader_id=1, rng=random.Random(0), signal_noise=0.0)
    empty = OrderBook(seq_source=iter(range(1, 1000)))

    assert trader.generate_order(empty, order_id=10, observed_p=0.9) is None


def test_every_price_stays_on_the_tick_grid():
    '''
    Both traders, 10k draws, including extreme observations that would push an
    unclamped price off the 1..99 grid and be rejected by the book.
    '''
    rng = random.Random(1)
    noise = NoiseTrader(trader_id=1, rng=rng, spread_width=60)
    informed = InformedTrader(trader_id=2, rng=rng, signal_noise=0.0)
    book = book_with_quotes(bid=1, ask=99)

    for step in range(5000):
        order = noise.generate_order(book, order_id=step + 100)
        assert 1 <= order.price <= 99

    for step in range(5000):
        probability = (step % 1000) / 1000
        order = informed.generate_order(book, order_id=step + 100_000,
                                        observed_p=probability)
        if order is not None:
            assert 1 <= order.price <= 99


def test_noise_trader_uses_the_anchor_when_the_book_is_empty():
    rng = random.Random(3)
    trader = NoiseTrader(trader_id=1, rng=rng, anchor_tick=50, spread_width=2)
    empty = OrderBook(seq_source=iter(range(1, 1000)))

    order = trader.generate_order(empty, order_id=1)

    assert 48 <= order.price <= 52


def test_noise_trader_both_rests_and_takes():
    '''
    A pure-GTC noise trader builds a book but never trades against the maker,
    so the maker earns no spread and its P&L is pure inventory noise.
    '''
    rng = random.Random(5)
    trader = NoiseTrader(trader_id=1, rng=rng, take_probability=0.3)
    book = book_with_quotes()

    kinds = set()
    for step in range(200):
        kinds.add(trader.generate_order(book, order_id=step + 1000).tif)

    assert kinds == {TimeInForce.GTC, TimeInForce.IOC}
