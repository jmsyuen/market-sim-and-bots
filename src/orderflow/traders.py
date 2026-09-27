'''
The two flow sources.

NoiseTrader is what a market maker profits from: it trades for reasons the model
does not represent, so on average it pays the spread and goes away.

InformedTrader is what a market maker loses to: it sees a noisy version of the
latent probability and crosses the spread when the book disagrees with it.

The ratio between the two, and the quality of the informed signal, is the
adverse-selection dial - the independent variable behind the headline result.
'''

from src.orderbook.order import Order, OrderType, Side, TimeInForce

TICK_MIN = 1
TICK_MAX = 99


class BaseTrader:
    def __init__(self, trader_id: int, rng) -> None:
        '''
        trader_id must be DISTINCT per instance. Share one and the book's
        self-trade prevention starts cancelling unrelated orders, and fill
        counts quietly collapse.

        rng is passed in rather than created here so the engine owns all
        randomness and a whole run is reproducible from one seed.
        '''
        self.trader_id = trader_id
        self.rng = rng

    def generate_order(self, book, order_id: int) -> "Order | None":
        raise NotImplementedError

    def _clamp(self, tick: int) -> int:
        '''
        Order rejects a price <= 0 but has no upper bound, and a prediction
        market only has ticks 1..99, so the ceiling is enforced here.
        '''
        if tick < TICK_MIN:
            return TICK_MIN
        if tick > TICK_MAX:
            return TICK_MAX
        return tick


class NoiseTrader(BaseTrader):
    '''
    Uninformed flow.

    Note the signature of generate_order: no probability argument, deliberately.
    If this class could reach the latent value even indirectly then the
    "uninformed" flow is informed and the experiment measures nothing. Leaving
    it out of the signature makes that mistake impossible rather than merely
    unlikely.
    '''

    def __init__(self, trader_id, rng, anchor_tick=50, spread_width=3,
                 max_size=5, take_probability=0.3) -> None:
        '''
        anchor_tick     - where to quote around when the book has no mid yet
        spread_width    - how far from the reference the price may land
        max_size        - largest order this trader will send
        take_probability- how often it crosses instead of resting. A pure-GTC
                          noise trader builds a book but never trades against
                          the maker, so the maker earns no spread at all and
                          its P&L is pure inventory noise.
        '''
        super().__init__(trader_id, rng)
        self.anchor_tick = anchor_tick
        self.spread_width = spread_width
        self.max_size = max_size
        self.take_probability = take_probability

    def generate_order(self, book, order_id):
        reference = book.mid
        if reference is None:
            reference = self.anchor_tick

        side = self.rng.choice((Side.BUY, Side.SELL))
        offset = self.rng.randint(-self.spread_width, self.spread_width)
        price = self._clamp(round(reference) + offset)
        quantity = self.rng.randint(1, self.max_size)

        if self.rng.random() < self.take_probability:
            tif = TimeInForce.IOC
        else:
            tif = TimeInForce.GTC

        return Order(
            id=order_id,
            side=side,
            quantity=quantity,
            price=price,
            type=OrderType.LIMIT,
            tif=tif,
            trader_id=self.trader_id,
        )


class InformedTrader(BaseTrader):
    '''
    Sees a noisy probability and aggresses when the book disagrees with it.

    It never receives the true probability. The engine adds the observation
    noise and hands over only the result, so no argument in generate_order
    could leak the truth even by accident.
    '''

    def __init__(self, trader_id, rng, signal_noise, edge_threshold=2.0,
                 max_size=10) -> None:
        '''
        signal_noise   - standard deviation of the observation error, in
                         PROBABILITY units. 0.0 is a perfect insider, 0.3 is
                         barely better than guessing. THIS is the dial to
                         sweep: one scalar, everything else held fixed.

        edge_threshold - minimum edge in ticks before it acts. Without one it
                         trades on every arrival and swamps the book.
                         Economically it is a transaction-cost tolerance.

        max_size       - cap on the size scaling below.
        '''
        super().__init__(trader_id, rng)
        self.signal_noise = signal_noise
        self.edge_threshold = edge_threshold
        self.max_size = max_size

    def generate_order(self, book, order_id, observed_p):
        '''
        The reference is micro_price, not mid. Micro already accounts for queue
        imbalance, so a thin side does not fool the informed trader into seeing
        edge that is really just a one-sided book.

        The order is a marketable LIMIT with IOC, not a MARKET order: it
        crosses everything between the touch and its own estimate, and refuses
        to pay through its own fair value. A MARKET order would walk the whole
        book on a thin day and hand the maker a windfall.

        IOC matters more than the price. If this rested a GTC limit it would
        become a liquidity PROVIDER, and adverse selection - the maker being
        picked off by someone crossing the spread - would never appear at all.
        That is the most common reason this experiment shows nothing.
        '''
        reference = book.micro_price
        if reference is None:
            return None

        target_tick = observed_p * 100
        edge = target_tick - reference

        if abs(edge) < self.edge_threshold:
            return None

        if edge > 0:
            side = Side.BUY
        else:
            side = Side.SELL

        return Order(
            id=order_id,
            side=side,
            quantity=self._size_for(edge),
            price=self._clamp(round(target_tick)),
            type=OrderType.LIMIT,
            tif=TimeInForce.IOC,
            trader_id=self.trader_id,
        )

    def _size_for(self, edge: float) -> int:
        '''
        Size grows with conviction, which is what makes this a "sweeper":
        a bigger order walks through more levels and leaves visible impact.
        '''
        steps = int(abs(edge) / self.edge_threshold)
        if steps < 1:
            return 1
        if steps > self.max_size:
            return self.max_size
        return steps
