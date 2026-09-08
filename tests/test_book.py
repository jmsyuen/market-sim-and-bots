import random
from itertools import count

import pytest
from src.orderbook.book import OrderBook
from src.orderbook.order import Order, OrderType, Side, TimeInForce

'''
Useful tests in bash
python -m pytest -v                 # one line per test (what you ran)
python -m pytest -q                 # compact, good once the suite is large
python -m pytest --lf                           # rerun only last session's failures
'''

# PASS 1

def limit(order_id, side, price, quantity, trader_id=None):
    """testing GTC limit order
    IDs passed explicitly for order assertion tests"""

    return Order(
        id=order_id,
        side=side,
        price=price,
        quantity=quantity,
        type=OrderType.LIMIT,
        tif=TimeInForce.GTC,
        trader_id=trader_id,
    )



@pytest.fixture
def book():
    # a fresh counter per test, so seq values are deterministic and a failing
    # test reports the same numbers every run
    return OrderBook(seq_source=count(1))


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
    first = limit(1, Side.BUY, 40, 10)
    second = limit(2, Side.BUY, 40, 10)
    book.submit(first)
    book.submit(second)

    level = book.bids[40]
    assert len(level) == 2
    assert level[0] is first     # front = oldest = first to fill
    assert level[1] is second


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

# PASS 2

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


# PASS 3