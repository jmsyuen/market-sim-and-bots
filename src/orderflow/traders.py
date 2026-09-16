# the two flow sources.
#
# NoiseTrader is what a market maker profits from. InformedTrader is what it
# loses to. The ratio between them, and the quality of the informed signal, is
# the adverse-selection dial — the single independent variable behind the
# "informed flow rose, spread capture stayed flat, P&L collapsed" result.

from src.orderbook.order import Order, OrderType, Side, TimeInForce

TICK_MIN = 1
TICK_MAX = 99


class BaseTrader:
    def __init__(self, trader_id: int, rng) -> None:
        # trader_id must be DISTINCT per instance. share one and self-trade
        # prevention starts cancelling unrelated orders, and your fill counts
        # quietly collapse.
        #
        # rng is passed in, not created here, so the engine owns all randomness
        # and a run is reproducible from one seed.
        # self.trader_id = trader_id
        # self.rng = rng
        ...

    def generate_order(self, book, order_id: int) -> "Order | None":
        """Return an Order, or None to skip this arrival.

        order_id comes from THE engine's shared counter. Per-trader counters
        collide and book.submit raises ValueError on the duplicate.
        """
        raise NotImplementedError

    def _clamp(self, tick: int) -> int:
        # keep prices inside 1..99. Order rejects price <= 0 but has no upper
        # bound, so the ceiling is enforced here rather than at the book.
        ...


class NoiseTrader(BaseTrader):
    """Uninformed flow. Trades for reasons the model does not represent.

    Note the signature: no true_p argument, deliberately. If this class can
    reach the latent value even indirectly, your 'uninformed' flow is informed
    and the adverse-selection experiment measures nothing. Keeping it out of
    the signature makes that mistake impossible rather than merely unlikely.
    """

    def __init__(self, trader_id, rng, anchor_tick: int, spread_width: int, max_size: int) -> None:
        # anchor_tick: where to quote around when the book is empty or one-sided
        # spread_width: how far from the reference to place the price
        ...

    def generate_order(self, book, order_id):
        # reference = book.mid; if None, fall back to self.anchor_tick
        # side = rng.choice((BUY, SELL))
        # offset = rng.randint(-spread_width, spread_width)
        # price = clamp(round(reference) + offset)
        # quantity = rng.randint(1, max_size)
        #
        # mostly GTC (it provides liquidity), occasionally IOC (it takes).
        # a pure-GTC noise trader builds a book but never trades against the
        # maker, so the maker never earns spread and the P&L is all inventory.
        ...


class InformedTrader(BaseTrader):
    """Sees a noisy version of the latent probability and aggresses on edge."""

    def __init__(self, trader_id, rng, signal_noise: float, edge_threshold: float, max_size: int) -> None:
        # signal_noise: standard deviation of the observation error, in
        #   PROBABILITY units. 0.0 is a perfect insider; 0.3 is barely better
        #   than noise. THIS is the dial to sweep — one scalar, everything else
        #   held fixed, which is the cleanest counterfactual available.
        #
        # edge_threshold: minimum |edge| in ticks before it acts. without one it
        #   trades on every single arrival and swamps the book. Economically it
        #   is the trader's transaction-cost tolerance.
        ...

    def generate_order(self, book, order_id, true_p: float):
        # observed = true_p + rng.gauss(0, signal_noise), clamped to (0, 1)
        #
        # reference = book.micro_price   (NOT mid — micro already accounts for
        #   queue imbalance, so the informed trader isn't fooled by a thin side)
        # if reference is None: return None
        #
        # edge = observed * 100 - reference
        # if abs(edge) < edge_threshold: return None
        #
        # side = BUY if edge > 0 else SELL
        #
        # AGGRESS — IOC at the far touch, or MARKET. If this rests a GTC limit
        # it becomes a liquidity PROVIDER, and adverse selection (the maker
        # being picked off by someone crossing the spread) never appears at all.
        # This is the most common reason the experiment shows nothing.
        #
        # size scaling with abs(edge) is what makes it a "sweeper": more
        # confident -> larger -> walks through more levels -> visible impact.
        ...


# ----------------------------------------------------------------------
# tests worth writing (tests/test_traders.py)
# ----------------------------------------------------------------------
# 1. NoiseTrader.generate_order has no parameter that could carry true_p
#    (inspect.signature — a structural test, cheap and it never goes stale)
# 2. InformedTrader with signal_noise=0 and true_p far above micro_price always
#    returns a BUY; far below, always a SELL
# 3. InformedTrader returns None when the edge is inside the threshold
# 4. every order an InformedTrader produces has tif != GTC
# 5. prices are always within 1..99, over 10_000 draws from both traders
