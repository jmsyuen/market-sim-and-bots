'''
Portfolio tests.

Nothing here crashes when it is wrong - a sign error produces a perfectly
plausible number of the wrong sign, which is why these are written as exact
arithmetic rather than as properties.
'''

import pytest

from src.orderbook.order import Side
from src.orderbook.trade import Trade
from src.portfolio import Portfolio


def fill(price, quantity, taker_side, maker_id=1, taker_id=2):
    return Trade(
        price=price,
        quantity=quantity,
        maker_id=maker_id,
        taker_id=taker_id,
        seq=0,
        taker_side=taker_side,
    )


def buy(portfolio, price, quantity):
    portfolio.on_fill(fill(price, quantity, Side.BUY), Side.BUY)


def sell(portfolio, price, quantity):
    portfolio.on_fill(fill(price, quantity, Side.SELL), Side.SELL)


def test_round_trip_realises_the_difference():
    portfolio = Portfolio()
    buy(portfolio, 40, 10)
    sell(portfolio, 45, 10)

    assert portfolio.realised_pnl == pytest.approx(50)
    assert portfolio.position == 0
    assert portfolio.avg_cost == 0.0


def test_adding_averages_the_cost_and_realises_nothing():
    portfolio = Portfolio()
    buy(portfolio, 40, 10)
    buy(portfolio, 50, 10)

    assert portfolio.position == 20
    assert portfolio.avg_cost == pytest.approx(45)
    assert portfolio.realised_pnl == pytest.approx(0)


def test_partial_close_leaves_the_cost_basis_alone():
    '''Closing a position does not reprice the contracts that remain.'''
    portfolio = Portfolio()
    buy(portfolio, 40, 10)
    sell(portfolio, 45, 4)

    assert portfolio.realised_pnl == pytest.approx(20)
    assert portfolio.position == 6
    assert portfolio.avg_cost == pytest.approx(40)


def test_flipping_closes_then_reopens_at_the_new_price():
    '''
    The case that fails first in every implementation. Ten contracts close and
    realise, five open fresh in the other direction with a new basis.
    '''
    portfolio = Portfolio()
    buy(portfolio, 40, 10)
    sell(portfolio, 45, 15)

    assert portfolio.realised_pnl == pytest.approx(50)
    assert portfolio.position == -5
    assert portfolio.avg_cost == pytest.approx(45)


def test_short_round_trip():
    portfolio = Portfolio()
    sell(portfolio, 60, 10)
    buy(portfolio, 55, 10)

    assert portfolio.realised_pnl == pytest.approx(50)
    assert portfolio.position == 0


def test_our_side_is_not_read_off_the_trade():
    '''
    THE REGRESSION TEST. We are the maker, the taker bought, so we SOLD and our
    position must go negative.

    Reading trade.taker_side here instead of our_side gives +10 and every P&L
    number in the project comes out mirror-imaged, with nothing raising.
    '''
    portfolio = Portfolio()
    portfolio.on_fill(fill(40, 10, Side.BUY), Side.SELL)

    assert portfolio.position == -10


def test_settlement_pays_out_the_outcome():
    won = Portfolio()
    buy(won, 40, 10)
    won.settle(1)
    assert won.realised_pnl == pytest.approx(600)
    assert won.position == 0

    lost = Portfolio()
    buy(lost, 40, 10)
    lost.settle(0)
    assert lost.realised_pnl == pytest.approx(-400)


def test_short_settlement_is_the_negative_payout():
    portfolio = Portfolio()
    sell(portfolio, 60, 10)
    portfolio.settle(1)

    assert portfolio.realised_pnl == pytest.approx(-400)


def test_total_pnl_equals_cash_once_flat():
    '''
    If this fails, a sign convention disagrees between on_fill and the marking,
    and no other test in the file would notice.
    '''
    class EmptyBook:
        best_bid = None
        best_ask = None

    portfolio = Portfolio()
    buy(portfolio, 40, 10)
    sell(portfolio, 45, 10)

    assert portfolio.total_pnl(EmptyBook()) == pytest.approx(portfolio.cash)


def test_unrealised_marks_at_the_exit_side():
    '''Long marks at the bid, short at the ask - never the mid.'''
    class Book:
        best_bid = 44
        best_ask = 46

    long_book = Portfolio()
    buy(long_book, 40, 10)
    assert long_book.unrealised_pnl(Book()) == pytest.approx(40)

    short_book = Portfolio()
    sell(short_book, 50, 10)
    assert short_book.unrealised_pnl(Book()) == pytest.approx(40)


def test_unrealised_is_none_when_the_exit_side_is_empty():
    class OneSided:
        best_bid = None
        best_ask = 46

    portfolio = Portfolio()
    buy(portfolio, 40, 10)

    assert portfolio.unrealised_pnl(OneSided()) is None
    assert portfolio.total_pnl(OneSided()) is None
