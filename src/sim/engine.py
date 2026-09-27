'''
The discrete-event loop. Mode A (synthetic flow) only.

Mode B (historical replay plus a fill model) comes later and reuses everything
below the event dispatch.

The engine is the only component allowed to see everything: the latent value,
every trader, the book and the portfolio. That privilege is why the noise it
adds to the informed trader's view is added HERE - the trader receives only the
result, so nothing true ever crosses into strategy code.
'''

import heapq
from itertools import count

from src.orderbook.order import Order, OrderType, Side, TimeInForce
from src.orderflow.traders import InformedTrader

ARRIVAL = "ARRIVAL"
MM_UPDATE = "MM_UPDATE"
NEWS = "NEWS"
RESOLUTION = "RESOLUTION"

TICK_MIN = 1
TICK_MAX = 99

# probabilities are clamped off the boundary before becoming a tick, so an
# observation can never round to 0 or 100 and produce an illegal order price.
P_MIN = 0.01
P_MAX = 0.99


def clamp_tick(tick: int) -> int:
    if tick < TICK_MIN:
        return TICK_MIN
    if tick > TICK_MAX:
        return TICK_MAX
    return tick


class SimEngine:
    def __init__(self, book, value_process, traders, market_maker, portfolio,
                 rng, arrival_rate: float, mm_update_rate: float,
                 no_book=None) -> None:
        # `book` is the YES book. `no_book` is optional: pass one and the same
        # flow trades BOTH tokens, which is what coherence analysis needs.
        # Without it everything behaves exactly as before.
        self.book = book
        self.no_book = no_book
        self.value_process = value_process
        self.traders = traders
        self.market_maker = market_maker
        self.portfolio = portfolio
        self.rng = rng
        self.arrival_rate = arrival_rate
        self.mm_update_rate = mm_update_rate

        self.events = []
        self.tiebreak = count()
        self.order_ids = count(1)
        self.log = []
        self.time = 0.0

        # the book has no clock of its own, so the engine lends it one. every
        # Trade is then stamped with sim time at birth, which markout needs and
        # cannot reconstruct afterwards.
        self.book.clock = self._now
        if self.no_book is not None:
            self.no_book.clock = self._now

    def _now(self) -> float:
        return self.time

    def schedule(self, time: float, kind: str, payload=None) -> None:
        '''
        The tiebreak counter is NOT optional. Tuples compare element by
        element, so two events at an identical float time fall through to
        comparing the next field - and eventually the payload, which is a
        trader or an Order and is not orderable. The result is a TypeError at a
        random point deep into a long run, which is a miserable thing to debug.
        '''
        heapq.heappush(self.events, (time, next(self.tiebreak), kind, payload))

    def run(self, until: float) -> None:
        '''
        Seed the heap, then pop events in time order until the clock runs past
        `until` or the market resolves.

        News goes on the heap as its own event type so that a trader acts
        IMMEDIATELY after the jump. If the jump were only applied whenever the
        next trader happened to turn up, nobody would pick off the maker's
        stale quotes and the whole news feature would measure zero.
        '''
        for trader in self.traders:
            self.schedule(self.rng.expovariate(self.arrival_rate), ARRIVAL, trader)

        self.schedule(self.rng.expovariate(self.mm_update_rate), MM_UPDATE)

        for event_time, is_scheduled in self.value_process._news_events:
            self.schedule(event_time, NEWS)

        self.schedule(self.value_process.resolve_time, RESOLUTION)

        while len(self.events) > 0:
            event_time, _, kind, payload = heapq.heappop(self.events)
            if event_time > until:
                break

            self.time = event_time
            true_p = self.value_process.advance_to(event_time)

            if kind == ARRIVAL:
                self._handle_arrival(payload, true_p)
            elif kind == MM_UPDATE:
                self._handle_mm_update()
            elif kind == NEWS:
                self._handle_news(true_p)
            elif kind == RESOLUTION:
                outcome = self.value_process.resolve()
                self.portfolio.settle(outcome)
                self._snapshot(true_p)
                break

            self._snapshot(true_p)

    def _observe(self, true_p: float, signal_noise: float) -> float:
        '''
        The informed trader's view: the truth plus gaussian noise, in
        probability units, clamped off the boundary.

        Clamping is needed because probability space is bounded and the noise
        is not. It is a known wart: at an extreme true_p the noise is
        effectively one-sided, which slightly biases the signal toward the
        middle. Adding the noise in logit space would avoid it, at the cost of
        signal_noise no longer reading directly as "how many probability points
        wrong this trader typically is".
        '''
        observed = true_p + self.rng.gauss(0, signal_noise)
        if observed < P_MIN:
            return P_MIN
        if observed > P_MAX:
            return P_MAX
        return observed

    def _handle_arrival(self, trader, true_p: float, reschedule: bool = True) -> None:
        '''
        Routing is by trader type. The noise trader's generate_order has no
        parameter that could carry a probability, so the two calls cannot be
        confused for one another.

        Arrivals self-schedule rather than being pre-generated, so flow can
        react to state later without restructuring the loop.
        '''
        order_id = next(self.order_ids)

        # pick a token. a NO contract is worth (1 - p), so the informed
        # trader's view has to be complemented for that book - otherwise it
        # would trade NO as though it were YES and manufacture arbitrage.
        target_book = self.book
        is_no_book = False
        if self.no_book is not None and self.rng.random() < 0.5:
            target_book = self.no_book
            is_no_book = True

        if isinstance(trader, InformedTrader):
            observed_p = self._observe(true_p, trader.signal_noise)
            if is_no_book:
                observed_p = 1.0 - observed_p
            order = trader.generate_order(target_book, order_id, observed_p)
        else:
            order = trader.generate_order(target_book, order_id)

        if order is not None:
            trades = target_book.submit(order)
            # the maker quotes the YES book only, so NO-book trades can never
            # carry one of its ids and fall through _attribute harmlessly.
            self._attribute(trades)

        if reschedule:
            next_arrival = self.time + self.rng.expovariate(self.arrival_rate)
            self.schedule(next_arrival, ARRIVAL, trader)

    def _handle_news(self, true_p: float) -> None:
        '''
        advance_to has already applied the jump. What this adds is the race:
        every informed trader gets one immediate look at the new value, before
        the maker's next scheduled requote. That race IS the gap risk the
        strategy layer exists to price.

        reschedule=False because these arrivals are extra - each trader's own
        Poisson stream is untouched.
        '''
        for trader in self.traders:
            if isinstance(trader, InformedTrader):
                self._handle_arrival(trader, true_p, reschedule=False)

    def _handle_mm_update(self) -> None:
        for order_id in list(self.market_maker.resting_ids):
            # a False return just means that quote already filled, which is not
            # an error.
            self.book.cancel(order_id)
        self.market_maker.resting_ids.clear()
        self.market_maker.recent_ids.clear()

        quotes = self.market_maker.quotes(self.book, self.portfolio, self.time)
        if quotes is not None:
            bid_tick, ask_tick, size = quotes
            # either leg may be None: a position limit suppresses the side that
            # would grow the position, while leaving the unwinding side live.
            # pulling both would trap the maker at its cap until resolution.
            if bid_tick is not None:
                self._submit_quote(Side.BUY, bid_tick, size)
            if ask_tick is not None:
                self._submit_quote(Side.SELL, ask_tick, size)

        next_update = self.time + self.rng.expovariate(self.mm_update_rate)
        self.schedule(next_update, MM_UPDATE)

    def _submit_quote(self, side: Side, price: int, size: int) -> None:
        '''
        The id is recorded BEFORE submit, because a quote can cross and fill on
        submission - and _attribute has to be able to recognise it as ours in
        that same call.
        '''
        order_id = next(self.order_ids)
        order = Order(
            id=order_id,
            side=side,
            quantity=size,
            price=price,
            type=OrderType.LIMIT,
            tif=TimeInForce.GTC,
            trader_id=self.market_maker.trader_id,
        )

        self.market_maker.recent_ids.add(order_id)
        trades = self.book.submit(order)
        self._attribute(trades)

        if order.remaining > 0:
            self.market_maker.resting_ids.add(order_id)

    def _attribute(self, trades) -> None:
        '''
        Route the fills that belong to us into the portfolio.

        This is the step that is easiest to get silently wrong, and getting it
        wrong inverts the sign of every P&L number in the project.

        The maker branch is the one that matters, because a market maker is
        passive almost always. Our side of a passive fill is the OPPOSITE of
        the taker's side. Using taker_side there makes the position an exact
        mirror image of reality, and nothing crashes.
        '''
        for trade in trades:
            if trade.maker_id in self.market_maker.resting_ids or trade.maker_id in self.market_maker.recent_ids:
                our_side = trade.taker_side.opposite
            elif trade.taker_id in self.market_maker.recent_ids:
                our_side = trade.taker_side
            else:
                continue
            self.portfolio.on_fill(trade, our_side)

    def _snapshot(self, true_p: float) -> None:
        '''
        One plain dict per event. The DataFrame is built once, at the end:
        appending to a DataFrame inside the loop is quadratic and would
        dominate the runtime of every experiment.

        micro_price looks redundant next to mid but is not - it is what markout
        and calibration are measured against, and it cannot be recovered from
        the other fields afterwards.
        '''
        self.log.append({
            "time": self.time,
            "true_p": true_p,
            "best_bid": self.book.best_bid,
            "best_ask": self.book.best_ask,
            "mid": self.book.mid,
            "micro_price": self.book.micro_price,
            "position": self.portfolio.position,
            "cash": self.portfolio.cash,
            "realised_pnl": self.portfolio.realised_pnl,
            "unrealised_pnl": self.portfolio.unrealised_pnl(self.book),
            "n_trades": len(self.book.trades),
            "no_best_bid": self._no_book_field("best_bid"),
            "no_best_ask": self._no_book_field("best_ask"),
        })

    def _no_book_field(self, name):
        if self.no_book is None:
            return None
        return getattr(self.no_book, name)

    def to_frame(self):
        import pandas
        return pandas.DataFrame(self.log)


class FixedSpreadMaker:
    '''
    The control. No fair-value model, no inventory skew, no resolution
    awareness.

    It exists so the engine can be validated end to end before the real market
    maker is written, and so every feature added later has a baseline to be
    measured against. A feature with no measured effect is a claim, not a
    result.
    '''

    def __init__(self, trader_id: int, half_spread: int, size: int) -> None:
        self.trader_id = trader_id
        self.half_spread = half_spread
        self.size = size
        self.resting_ids = set()
        self.recent_ids = set()

    def quotes(self, book, portfolio, time):
        '''
        Returns (bid_tick, ask_tick, size), or None when there is nothing to
        quote around.

        portfolio and time are accepted and ignored. The real MarketMaker needs
        both, and keeping one interface means the two are swappable and every
        comparison against this control is like for like.
        '''
        reference = book.micro_price
        if reference is None:
            return None

        bid = clamp_tick(round(reference) - self.half_spread)
        ask = clamp_tick(round(reference) + self.half_spread)

        # clamping at 1 or 99 can collapse or invert the quote pair
        if bid >= ask:
            return None

        return (bid, ask, self.size)
