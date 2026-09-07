# central limit order book with price-time priority matching
#
# venue-agnostic: a CLOB is a CLOB. prediction-market specifics (complementary
# YES/NO tokens, resolution to 0/1) live in market/contract.py, NOT here.

from collections import deque
from itertools import count

from sortedcontainers import SortedDict

from .order import Order, OrderType, Side, TimeInForce
from .trade import Trade


# global sequence source. shared by default so that events across two books
# (the YES book and the NO book of one market) have a single total order —
# needed when the analysis layer interleaves their trade logs.
# tests pass their own count(1) to get a fresh, deterministic counter.
_GLOBAL_SEQ = count(1)


class OrderBook:
    """One side-paired book of resting orders. Owns the never-crossed invariant."""

    def __init__(self, seq_source=None) -> None:
        # tick -> deque[Order].
        #
        # SortedDict: needs cheap best-price access AND cheap cancel of an
        # arbitrary order. a heap gives the first but removing an interior
        # element is O(n) bookkeeping — and in real flow cancels vastly
        # outnumber fills, so cancel is the operation to optimise for.
        #
        # deque per level: a price level is FIFO. append newest at the back,
        # popleft the oldest as it fills — both O(1). weakness is O(n) removal
        # from the middle, which is what cancel does; documented upgrade path
        # is an intrusive doubly-linked list + {id -> node} for O(1) cancel.
        self.bids = SortedDict()  # best bid = LARGEST key  -> peekitem(-1)
        self.asks = SortedDict()  # best ask = SMALLEST key -> peekitem(0)

        # order_id -> (side, price). without this, cancel would scan every
        # level of both sides to find the order.
        self.locations: dict[int, tuple[Side, int]] = {}

        # order_id -> Order, for every order currently resting. used to reject
        # duplicate ids and to let the strategy layer inspect its own quotes.
        self.resting: dict[int, Order] = {}

        # every fill this book has produced, in sequence order. the analysis
        # layer (markout, decomposition, calibration) reads this.
        # ADDED NOW ON PURPOSE: retrofitting it later means backfilling every
        # construction site and every test that reads trades.
        self.trades: list[Trade] = []

        self._seq_source = seq_source if seq_source is not None else _GLOBAL_SEQ

    # ------------------------------------------------------------------
    # internals: sequence + side selection
    # ------------------------------------------------------------------

    def _next_seq(self) -> int:
        # next(self._seq_source)
        # a monotonic integer, NOT a timestamp. in a discrete-event sim many
        # events share one virtual time, so timestamps collide and FIFO order
        # goes ambiguous. physical time is a separate concept and arrives
        # stamped from outside, on Trade.time.
        ...

    def _book_for(self, side: Side) -> SortedDict:
        # the side an order of this `side` RESTS on: BUY -> self.bids
        ...

    def _book_against(self, side: Side) -> SortedDict:
        # the side an order of this `side` MATCHES against: BUY -> self.asks
        # implement as self._book_for(side.opposite) — one source of truth
        ...

    def _best_of(self, book: SortedDict) -> int | None:
        # peekitem(0)[0] for asks (lowest), peekitem(-1)[0] for bids (highest).
        # None if empty. decide by identity (`book is self.asks`) so this
        # helper works for either side without a Side argument.
        ...

    # ------------------------------------------------------------------
    # accessors — read-only views of book state
    # ------------------------------------------------------------------

    @property
    def best_bid(self) -> int | None:
        ...

    @property
    def best_ask(self) -> int | None:
        ...

    @property
    def mid(self) -> float | None:
        # (best_bid + best_ask) / 2, None if either side empty.
        # NOTE: a float, unlike every price in this file. it is a derived
        # statistic, never a matchable price, so it never enters the book.
        ...

    @property
    def spread(self) -> int | None:
        # best_ask - best_bid, None if either side empty
        ...

    @property
    def micro_price(self) -> float | None:
        # book-derived fair value using top-of-book imbalance:
        #   I     = Q_bid / (Q_bid + Q_ask)     Q_* = total size at best bid/ask
        #   micro = best_bid + I * spread       ( = I*ask + (1-I)*bid )
        # heavy bids -> I near 1 -> fair value sits near the ask.
        # None if either side empty.
        ...

    def size_at(self, side: Side, price: int) -> int:
        # sum of `remaining` over the deque at that price; 0 if no level.
        # feeds micro_price and depth, and lets tests assert on level size
        # without reaching into self.bids directly.
        ...

    def depth(self, levels: int = 5) -> dict[Side, list[tuple[int, int]]]:
        # [(price, total_remaining), ...] best-first, for each side.
        # analysis/plotting only — nothing in the matching path uses it.
        ...

    # ------------------------------------------------------------------
    # internals: resting and removing
    # ------------------------------------------------------------------

    def _rest(self, order: Order) -> None:
        # book = self._book_for(order.side)
        # create the deque if this price level does not exist yet
        # append to the BACK (newest = last in the FIFO queue)
        # record self.locations[order.id] and self.resting[order.id]
        ...

    def _remove(self, order: Order) -> None:
        # the single exit path for a resting order — both cancel() and a
        # complete fill route through here, so level cleanup can't diverge.
        # remove from the deque, DROP THE PRICE KEY IF THE LEVEL IS NOW EMPTY,
        # then drop from self.locations and self.resting.
        #
        # dropping the empty level is the step that gets forgotten: a stale
        # empty deque makes best_bid report a price with no size behind it,
        # which silently corrupts spread, micro_price, and every fill after.
        ...

    # ------------------------------------------------------------------
    # internals: the matching walk — the load-bearing 30 lines
    # ------------------------------------------------------------------

    def _crosses(self, order: Order, resting_price: int) -> bool:
        # does `order` want to trade at `resting_price`?
        #   BUY  crosses when order.price >= resting_price
        #   SELL crosses when order.price <= resting_price
        # MARKET orders (price is None) cross unconditionally -> True.
        #
        # named helper rather than the arithmetic form
        # `order.side.sign * (order.price - resting_price) >= 0` on purpose:
        # the sign trick is shorter but the reader has to derive it.
        ...

    def _available_quantity(self, order: Order) -> int:
        # total size the order could fill against right now, without mutating
        # anything. only FOK needs this: it must know the answer BEFORE any
        # fill happens, because a partial fill it then has to unwind is not
        # something this design supports.
        ...

    def _match(self, order: Order) -> list[Trade]:
        """Walk the opposite side, filling while the order crosses.

        POSTCONDITION: no crossed book — on return, either order.remaining == 0,
        or the best opposite price no longer crosses order.price.
        """
        # trades: list[Trade] = []
        # against = self._book_against(order.side)
        #
        # while order.remaining > 0 and against:
        #     best_price = self._best_of(against)
        #     if not self._crosses(order, best_price): break
        #
        #     level = against[best_price]
        #     resting = level[0]                  # FRONT = oldest = time priority
        #
        #     # self-trade prevention: same owner on both sides of the fill.
        #     # cancel the RESTING order and continue the walk (cancel-oldest),
        #     # rather than rejecting the incoming order. keeps the aggressor's
        #     # intent intact and matches how most venues default.
        #     if resting.trader_id is not None and resting.trader_id == order.trader_id:
        #         self._remove(resting)
        #         continue
        #
        #     quantity = min(order.remaining, resting.remaining)
        #
        #     # trade prints at the RESTING order's price, never the incoming
        #     # order's. the resting order set the terms; the aggressor accepted
        #     # them. this is where the maker earns the spread.
        #     trade = Trade(
        #         price=best_price,
        #         quantity=quantity,
        #         maker_id=resting.id,
        #         taker_id=order.id,
        #         seq=self._next_seq(),
        #         taker_side=order.side,
        #     )
        #
        #     order.fill(quantity)                # Order.fill owns the
        #     resting.fill(quantity)              # remaining >= 0 invariant
        #
        #     if resting.is_filled: self._remove(resting)
        #
        #     trades.append(trade)
        #     self.trades.append(trade)
        #
        # return trades
        ...

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def submit(self, order: Order) -> list[Trade]:
        """The single entry point. Match what crosses, then apply the TIF.

        One method rather than add_limit_order + add_market_order: the Order
        already carries `type` and `tif`, so letting the caller pick a method
        duplicates that information and lets the two disagree.
        """
        # reject a duplicate id (an id already in self.resting) — a silent
        # overwrite would orphan the old order inside its deque forever
        #
        # assign order.seq = self._next_seq()   # time priority, on arrival
        #
        # FOK: check self._available_quantity(order) >= order.quantity FIRST;
        #      if not, return [] having touched nothing
        #
        # trades = self._match(order)
        #
        # then decide the fate of any remainder:
        #   GTC + LIMIT and order.remaining > 0  -> self._rest(order)
        #   IOC, FOK, or MARKET                  -> discard the remainder
        #                                           (nothing to clean up — an
        #                                            unmatched order was never
        #                                            in the book)
        # return trades
        ...

    def cancel(self, order_id: int) -> bool:
        # look up self.resting, hand it to self._remove, return True.
        # return False (do not raise) if the id isn't resting: in a live
        # system a cancel racing a fill is normal, not an error.
        ...

    # ------------------------------------------------------------------
    # invariants — called by the fuzz suite after every operation
    # ------------------------------------------------------------------

    def assert_invariants(self) -> None:
        # lives on the book, not in tests, so the fuzz loop is a few lines and
        # every invariant has exactly one definition.
        #   1. not crossed:  best_bid < best_ask whenever both sides exist
        #   2. no empty levels on either side
        #   3. every resting order's remaining > 0
        #   4. self.locations and self.resting agree with the deques exactly
        #      (same id set, and each id's recorded price matches its level)
        #   5. bid levels only hold BUY orders, ask levels only SELL
        # share conservation is NOT here — it spans the book and the traders,
        # so it belongs in the fuzz test itself.
        ...
