# the discrete-event loop. Mode A (synthetic flow) only; Mode B (replay + fill
# model) comes later and reuses everything below the event dispatch.

import heapq
from itertools import count

from src.orderbook.order import Side

ARRIVAL = "ARRIVAL"
MM_UPDATE = "MM_UPDATE"
RESOLUTION = "RESOLUTION"


class SimEngine:
    def __init__(self, book, value_process, traders, market_maker, portfolio, rng,
                 arrival_rate: float, mm_update_rate: float) -> None:
        # self.events = []            # heap of (time, tiebreak, kind, payload)
        # self.tiebreak = count()
        # self.order_ids = count(1)   # THE shared id source. every order in the
        #                             # whole sim comes from here, or book.submit
        #                             # raises on a duplicate.
        # self.log = []
        # self.time = 0.0
        ...

    def schedule(self, time: float, kind: str, payload=None) -> None:
        # heapq.heappush(self.events, (time, next(self.tiebreak), kind, payload))
        #
        # the tiebreak counter is NOT optional. tuples compare element-wise, so
        # two events at an identical float time fall through to comparing the
        # third element — and a str vs a str is fine, but the payload after it
        # is an Order, which isn't orderable. You get a TypeError at a random
        # point deep into a long run, which is a miserable thing to debug.
        ...

    # ------------------------------------------------------------------
    # the loop
    # ------------------------------------------------------------------

    def run(self, until: float) -> None:
        # seed the heap:
        #   one ARRIVAL per trader at rng.expovariate(arrival_rate)
        #   one MM_UPDATE
        #   one RESOLUTION at value_process.resolve_time
        #
        # while len(self.events) > 0:
        #     time, _, kind, payload = heapq.heappop(self.events)
        #     if time > until: break
        #     self.time = time
        #     true_p = self.value_process.advance_to(time)
        #
        #     if kind == ARRIVAL:
        #         self._handle_arrival(payload, true_p)
        #     elif kind == MM_UPDATE:
        #         self._handle_mm_update()
        #     elif kind == RESOLUTION:
        #         outcome = self.value_process.resolve()
        #         self.portfolio.settle(outcome)
        #         self._snapshot(true_p)
        #         break
        #
        #     self._snapshot(true_p)
        ...

    def _handle_arrival(self, trader, true_p: float) -> None:
        # ask the trader for an order — pass true_p ONLY to the informed one.
        # branch on isinstance, or give BaseTrader a `needs_true_p` flag; either
        # way the noise trader must never receive it.
        #
        # if order is not None:
        #     trades = self.book.submit(order)
        #     self._attribute(trades)
        #
        # Poisson arrivals self-schedule: reschedule THIS trader at
        # time + rng.expovariate(arrival_rate). Don't pre-generate the whole
        # arrival list — you then can't react to state.
        ...

    def _handle_mm_update(self) -> None:
        # 1. cancel every id in market_maker.resting_ids (ignore False returns —
        #    a quote that already filled is not an error)
        # 2. ask for new quotes; if None, just reschedule
        # 3. submit the bid and the ask, recording their ids on the maker
        # 4. attribute any trades the new quotes caused immediately — a quote
        #    that crosses on submission makes you the TAKER, not the maker,
        #    and _attribute must handle that (see below)
        # 5. reschedule the next MM_UPDATE
        ...

    def _attribute(self, trades) -> None:
        """Route fills that belong to us into the portfolio.

        This is the step that is easiest to get silently wrong, and it inverts
        the sign of every P&L number when you do.
        """
        # for trade in trades:
        #     if trade.maker_id in self.market_maker.resting_ids:
        #         our_side = trade.taker_side.opposite     # we were passive
        #     elif trade.taker_id in self.market_maker.recent_ids:
        #         our_side = trade.taker_side              # we crossed
        #     else:
        #         continue                                 # not our fill
        #     self.portfolio.on_fill(trade, our_side)
        #
        # the maker branch is the one that matters — a market maker is passive
        # almost always. if you use trade.taker_side there, your position is the
        # exact mirror image of reality and P&L flips sign.
        ...

    # ------------------------------------------------------------------
    # logging
    # ------------------------------------------------------------------

    def _snapshot(self, true_p: float) -> None:
        # append ONE plain dict. build the DataFrame once, at the end.
        # appending to a DataFrame inside the loop is quadratic and will
        # dominate the runtime of every experiment you run.
        #
        # fields that make the analysis layer possible without a second run:
        #   time, true_p, best_bid, best_ask, mid, micro_price,
        #   position, cash, realised_pnl, unrealised_pnl, n_trades
        #
        # micro_price is what markout and calibration are measured against, so
        # it must be here even though it looks redundant next to mid.
        ...

    def to_frame(self):
        # pandas.DataFrame(self.log) — once, after run() returns
        ...


class FixedSpreadMaker:
    """No fair-value model, no skew, no resolution awareness.

    Exists only so the engine can be validated end to end before the real
    market maker is written. Everything it lacks is a thing you will add in
    market_maker.py and measure the effect of — which is what turns each
    feature into a number on the CV instead of a claim.
    """

    def __init__(self, trader_id: int, half_spread: int, size: int) -> None:
        # self.resting_ids = set()
        # self.recent_ids = set()     # for taker attribution
        ...

    def quotes(self, book):
        """Return (bid_tick, ask_tick, size), or None if there's no anchor."""
        # reference = book.micro_price
        # if reference is None: return None
        #
        # bid = clamp(round(reference) - self.half_spread)
        # ask = clamp(round(reference) + self.half_spread)
        # if bid >= ask: return None     (can happen after clamping at 1 or 99)
        # return (bid, ask, self.size)
        ...


# ----------------------------------------------------------------------
# what a correct loop should show
# ----------------------------------------------------------------------
# With signal_noise large (informed flow is effectively noise):
#   - position oscillates around zero
#   - P&L is roughly half_spread * fill_count, minus inventory drift
#
# Turn signal_noise down toward 0:
#   - fill count stays roughly FLAT
#   - P&L collapses
#
# That gap is adverse selection, and it is the second CV bullet, measured.
#
# If turning the dial does nothing, check in this order:
#   1. is the informed trader aggressing (tif != GTC) or resting?
#   2. is true_p actually moving? (log it and look)
#   3. is _attribute using taker_side.opposite on the maker branch?
# It is almost always one of those three.
