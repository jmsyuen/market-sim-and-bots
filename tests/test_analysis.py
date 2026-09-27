'''
Tests for metrics, calibration, coherence and contract.

Built on hand-made inputs rather than engine runs: a run has too many moving
parts to assert an exact number against, and these files are pure arithmetic.
'''

import math

import pytest

from src.analysis import calibration, coherence, metrics
from src.market.contract import BinaryMarket
from src.orderbook.book import OrderBook
from src.orderbook.order import Order, Side
from src.orderbook.trade import Trade


def fill(price, quantity, our_side, time, taker_side=None):
    if taker_side is None:
        taker_side = our_side.opposite
    trade = Trade(price=price, quantity=quantity, maker_id=1, taker_id=2,
                  seq=0, taker_side=taker_side, time=time)
    return (trade, our_side)


# ----------------------------------------------------------------------
# metrics
# ----------------------------------------------------------------------


def test_reference_lookup_is_a_step_function():
    series = [(0.0, 50.0), (1.0, 60.0), (2.0, 70.0)]
    times = [0.0, 1.0, 2.0]

    assert metrics.reference_at(series, times, 1.5) == 60.0
    assert metrics.reference_at(series, times, 2.0) == 70.0
    assert metrics.reference_at(series, times, -1.0) is None


def test_strict_lookup_excludes_the_snapshot_at_the_fill():
    '''
    The engine snapshots AFTER the event, so the row stamped at a fill's own
    time already contains that fill's impact. Spread capture measured against
    it would credit the maker with the price move caused by the trade that hurt
    it, and would hide the same move from the adverse-selection term.
    '''
    series = [(0.0, 50.0), (1.0, 60.0)]
    times = [0.0, 1.0]

    assert metrics.reference_at(series, times, 1.0) == 60.0
    assert metrics.reference_at(series, times, 1.0, strict=True) == 50.0


def test_markout_is_positive_when_the_price_moves_your_way():
    series = [(0.0, 50.0), (1.0, 55.0)]
    fills = [fill(price=48, quantity=1, our_side=Side.BUY, time=0.0)]

    curve = metrics.markout(fills, series, horizons=(1.0,))

    assert curve[1.0] == pytest.approx(7.0)


def test_markout_is_negative_when_you_are_picked_off():
    '''We sold at 52, the price then rose to 60: we were run over.'''
    series = [(0.0, 50.0), (1.0, 60.0)]
    fills = [fill(price=52, quantity=1, our_side=Side.SELL, time=0.0)]

    curve = metrics.markout(fills, series, horizons=(1.0,))

    assert curve[1.0] == pytest.approx(-8.0)


def test_markout_is_quantity_weighted():
    series = [(0.0, 50.0), (1.0, 55.0)]
    small = [fill(price=50, quantity=1, our_side=Side.BUY, time=0.0)]
    large = [fill(price=50, quantity=100, our_side=Side.BUY, time=0.0)]

    assert (metrics.markout(small, series, horizons=(1.0,))[1.0]
            == metrics.markout(large, series, horizons=(1.0,))[1.0])


def test_decomposition_sums_to_the_total():
    '''
    THE TEST THAT MATTERS. Inventory is computed as the residual precisely so
    this holds by construction - a decomposition that can disagree with the
    P&L it explains is worse than no decomposition.
    '''
    series = [(0.0, 50.0), (0.5, 53.0), (1.0, 58.0)]
    fills = [
        fill(price=48, quantity=5, our_side=Side.BUY, time=0.5),
        fill(price=56, quantity=3, our_side=Side.SELL, time=0.5),
    ]

    parts = metrics.decompose_pnl(fills, series, total_pnl=123.0, horizon=0.5,
                                  fee_per_contract=0.25)

    rebuilt = (parts["spread_capture"] + parts["adverse_selection"]
               + parts["fees"] + parts["inventory"])
    assert rebuilt == pytest.approx(123.0)


def test_settlement_markout_sees_what_short_horizons_miss():
    '''
    A maker that sold at 52 into a market that resolves YES lost 48 ticks per
    contract, however calm the mid looked an instant later.
    '''
    fills = [fill(price=52, quantity=1, our_side=Side.SELL, time=0.0)]

    assert metrics.settlement_markout(fills, outcome=1) == pytest.approx(-48.0)
    assert metrics.settlement_markout(fills, outcome=0) == pytest.approx(52.0)


def test_rms_inventory_penalises_swings_a_mean_would_hide():
    swinging = [{"position": 50}, {"position": -50}]
    flat = [{"position": 0}, {"position": 0}]

    assert metrics.rms_inventory(swinging) == pytest.approx(50.0)
    assert metrics.rms_inventory(flat) == 0.0


# ----------------------------------------------------------------------
# calibration
# ----------------------------------------------------------------------


def test_brier_rewards_being_right_and_confident():
    assert calibration.brier([1.0, 0.0], [1, 0]) == pytest.approx(0.0)
    assert calibration.brier([0.0, 1.0], [1, 0]) == pytest.approx(1.0)
    assert calibration.brier([0.5, 0.5], [1, 0]) == pytest.approx(0.25)


def test_the_base_rate_benchmark_is_what_you_must_beat():
    outcomes = [1, 1, 0, 0]
    assert calibration.base_rate_benchmark(outcomes) == pytest.approx(0.25)


def test_log_loss_punishes_confident_wrongness_harder_than_brier():
    '''
    For a trader, the difference between being a bit wrong often and being
    catastrophically wrong occasionally is the more important fact.
    '''
    cautious = calibration.log_loss([0.4], [1])
    reckless = calibration.log_loss([0.01], [1])

    assert reckless > cautious * 3


def test_log_loss_clips_rather_than_diverging():
    '''A maker quoting 1 tick produces p = 0.01; quoting 0 would be infinite.'''
    assert calibration.log_loss([0.0], [1]) < math.inf


def test_reliability_drops_empty_bins():
    rows = calibration.reliability([0.05, 0.95], [0, 1], bins=10)
    assert len(rows) == 2


# ----------------------------------------------------------------------
# coherence
# ----------------------------------------------------------------------


def two_books(yes_bid, yes_ask, no_bid, no_ask, size=10):
    yes = OrderBook(seq_source=iter(range(1, 100_000)))
    no = OrderBook(seq_source=iter(range(100_000, 200_000)))
    yes.submit(Order(id=1, side=Side.BUY, quantity=size, price=yes_bid, trader_id=1))
    yes.submit(Order(id=2, side=Side.SELL, quantity=size, price=yes_ask, trader_id=1))
    no.submit(Order(id=3, side=Side.BUY, quantity=size, price=no_bid, trader_id=2))
    no.submit(Order(id=4, side=Side.SELL, quantity=size, price=no_ask, trader_id=2))
    return [yes, no]


def test_a_planted_buy_side_arbitrage_is_found():
    '''YES ask 40 + NO ask 50 = 90 for something worth 100.'''
    books = two_books(yes_bid=38, yes_ask=40, no_bid=48, no_ask=50)

    found = coherence.find_arbitrage(books)

    assert found is not None
    assert found["direction"] == "buy"
    assert found["profit_per_set"] == pytest.approx(10.0)


def test_a_planted_sell_side_arbitrage_is_found():
    '''YES bid 60 + NO bid 55 = 115 for something worth 100.'''
    books = two_books(yes_bid=60, yes_ask=62, no_bid=55, no_ask=57)

    found = coherence.find_arbitrage(books)

    assert found is not None
    assert found["direction"] == "sell"


def test_a_coherent_market_shows_nothing():
    books = two_books(yes_bid=48, yes_ask=52, no_bid=48, no_ask=52)
    assert coherence.find_arbitrage(books) is None


def test_fees_kill_a_marginal_arbitrage():
    '''
    THE POINT OF THE FILE. One tick of edge, two legs, one tick of fee each -
    the violation is real on headline prices and worthless in practice.
    '''
    books = two_books(yes_bid=38, yes_ask=49, no_bid=48, no_ask=50)

    assert coherence.find_arbitrage(books, fee_per_leg=0.0) is not None
    assert coherence.find_arbitrage(books, fee_per_leg=1.0) is None


def test_size_is_capped_by_the_thinnest_leg():
    books = two_books(yes_bid=38, yes_ask=40, no_bid=48, no_ask=50, size=3)
    found = coherence.find_arbitrage(books)

    assert found["size"] <= 3


def test_depth_is_walked_rather_than_assumed():
    '''
    Not best_ask * quantity. The second set costs more than the first once the
    touch is exhausted, which is why an arb that exists in size one often does
    not exist in size ten.
    '''
    books = two_books(yes_bid=38, yes_ask=40, no_bid=48, no_ask=50, size=2)
    # a second, much worse level on each leg
    books[0].submit(Order(id=98, side=Side.SELL, quantity=10, price=55, trader_id=7))
    books[1].submit(Order(id=99, side=Side.SELL, quantity=10, price=65, trader_id=8))

    cost_small = coherence.executable_cost_to_buy_set(books, 2)
    cost_large = coherence.executable_cost_to_buy_set(books, 4)

    assert cost_large > cost_small * 2


def test_a_lopsided_set_is_rejected():
    with pytest.raises(ValueError):
        coherence.find_arbitrage([OrderBook(seq_source=iter(range(1, 100)))])


# ----------------------------------------------------------------------
# contract
# ----------------------------------------------------------------------


def test_the_complementary_price_is_the_mirror():
    assert BinaryMarket.complementary_price(30) == 70
    assert BinaryMarket.complementary_price(70) == 30


def test_the_no_ask_implies_a_yes_bid():
    '''
    THE SIDE FLIP, and the easiest thing in the project to get backwards.
    Buying NO cheaply is the same trade as selling YES dearly, so the cheapest
    NO offer implies the highest willingness to be short YES.
    '''
    yes, no = two_books(yes_bid=48, yes_ask=52, no_bid=45, no_ask=49)
    market = BinaryMarket("m", yes, no, value_process=None)

    assert market.implied_yes_bid == 51      # 100 - 49
    assert market.implied_yes_ask == 55      # 100 - 45
