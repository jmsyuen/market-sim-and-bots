# central limit order book with price-time priority matching
#
# prediction-market specifics (complementary YES/NO tokens, resolution to 0/1) live in market/contract.py, not here

from itertools import count

from sortedcontainers import SortedDict

from .order import Order, OrderType, Side, TimeInForce
from .price_level import PriceLevel
from .trade import Trade


# global sequence source. shared by default so that events across two books
# (the YES book and the NO book of one market) have a single total order —
# needed when the analysis layer interleaves their trade logs.
# tests pass their own count(1) to get a fresh, deterministic counter.
_GLOBAL_SEQ = count(1)


class OrderBook:
    """One side-paired book of resting orders. Owns the never-crossed invariant."""

    def __init__(self, seq_source=None) -> None:
        # tick -> PriceLevel.
        #
        # SortedDict: needs cheap best-price access AND cheap cancel of an
        # arbitrary order. a heap gives the first but removing an interior
        # element is O(n) bookkeeping — and in real flow cancels vastly
        # outnumber fills, so cancel is the operation to optimise for.
        #
        # PriceLevel per level: a price level is FIFO, and a PriceLevel is an
        # intrusive doubly-linked list - append newest at the back, take the
        # oldest as it fills, and remove from ANYWHERE, all O(1). it replaced a
        # deque, which was O(1) at both ends but O(n) in the middle - and the
        # middle is what a cancel usually is, so it was the common case rather
        # than the edge case. see price_level.py for why the pointers live on
        # Order rather than in wrapper nodes.

        self.bids = SortedDict()  # best bid = LARGEST key  -> peekitem(-1)
        self.asks = SortedDict()  # best ask = SMALLEST key -> peekitem(0)
        # best_price, level

        # order_id -> Order, for every order currently resting. this is the
        # ONLY index: it rejects duplicate ids, gives cancel the object it needs
        # to splice out of the level, and carries .side and .price so the level
        # can be located without a second lookup table.
        #
        # a separate {id -> (side, price)} map was considered and dropped: it
        # stores nothing this doesn't already hold, doubles the writes on _rest
        # and _remove, and buys no asymptotic win (you still scan the deque).
        # the structure that DOES buy O(1) cancel is {id -> linked-list node},
        # and that replaces this dict rather than sitting alongside it.
        # reverse this only for an amend that changes price while KEEPING queue
        # position; standard amend semantics don't need it.
        self.resting: dict[int, Order] = {}

        # every fill this book has produced, in sequence order. the analysis
        # layer (markout, decomposition, calibration) reads this.
        # ADDED NOW ON PURPOSE: retrofitting it later means backfilling every
        # construction site and every test that reads trades.
        self.trades: list[Trade] = []

        if seq_source is not None:
            self._seq_source = seq_source
        else:
            self._seq_source = _GLOBAL_SEQ
        

    # ------------------------------------------------------------------
    # internals: sequence + side selection
    # ------------------------------------------------------------------

    def _next_seq(self) -> int:
        # a monotonic integer, not a timestamp.
        return next(self._seq_source)
        

    def _book_for(self, side: Side) -> SortedDict:
        if side is Side.BUY:
            return self.bids
        else:
            return self.asks
        
    def _book_against(self, side: Side) -> SortedDict:
        return self._book_for(side.opposite)
        

    def _best_of(self, book: SortedDict) -> int | None:
        # peekitem(0)[0] for asks (lowest), peekitem(-1)[0] for bids (highest).
        # None if empty. decide by identity (`book is self.asks`) so this
        # helper works for either side without a Side argument.
        if len(book) == 0:
            return None

        # book in ascending prices
        if book is self.asks:
            best_price = book.peekitem(0)[0]     # lowest ask
        else:
            best_price = book.peekitem(-1)[0]    # highest bid

        return best_price

        

    # ------------------------------------------------------------------
    # accessors — read-only views of book state
    # ------------------------------------------------------------------

    @property
    def best_bid(self) -> int | None:
        return self._best_of(self.bids)

    @property
    def best_ask(self) -> int | None:
        return self._best_of(self.asks)

    @property
    def mid(self) -> float | None:
        bid, ask = self.best_bid, self.best_ask

        if bid is None or ask is None:
            return None

        return (bid + ask) / 2  # float as derived stat, doesn't enter book

    @property
    def spread(self) -> int | None:
        # best_ask - best_bid, None if either side empty
        bid, ask = self.best_bid, self.best_ask

        if bid is None or ask is None:
            return None

        return ask - bid
        

    @property
    def micro_price(self) -> float | None:
        # book-derived fair value using top-of-book imbalance, ie. interpolation:
        #   I     = Q_bid / (Q_bid + Q_ask)     Q_* = total size at best bid/ask
        #   micro = best_bid + I * spread       ( = I*ask + (1-I)*bid )
        # heavy bids -> I near 1 -> fair value sits near the ask.
        
        bid, ask = self.best_bid, self.best_ask

        if bid is None or ask is None:
            return None
        
        bid_size = self.size_at(Side.BUY, bid)
        ask_size = self.size_at(Side.SELL, ask)

        imbalance = bid_size / (bid_size + ask_size)
        micro = bid + imbalance * (ask - bid)
        return micro
        

    def size_at(self, side: Side, price: int) -> int:
        # get quantity at price level without reaching into self.bids directly
        book = self._book_for(side)

        if price not in book:
            return 0
        
        level = book[price]
        total = 0

        for order in level:
            total += order.remaining
        return total
        

    def depth(self, levels: int = 5) -> dict[Side, list[tuple[int, int]]]:
        # for analysis/plotting only
        bid_levels, ask_levels = [], []
        taken = 0
        for price in reversed(self.bids):   #reversed as descending
            if taken >= levels:
                break
            bid_levels.append((price, self.size_at(Side.BUY, price)))
            taken += 1

        taken = 0
        for price in self.asks:
            if taken >= levels:
                break
            ask_levels.append((price, self.size_at(Side.SELL, price)))
            taken += 1

        return {Side.BUY: bid_levels, Side.SELL: ask_levels}

    # ------------------------------------------------------------------
    # internals: resting and removing
    # ------------------------------------------------------------------

    def _rest(self, order: Order) -> None:
        
        book = self._book_for(order.side)
        if order.price not in book:
            book[order.price] = PriceLevel() # create the level if this price is new

        book[order.price].append(order) # FIFO order
        self.resting[order.id] = order
        

    def _remove(self, order: Order) -> None:
        # remove resting order from price level, delete level if empty
        book = self._book_for(order.side)
        level = book[order.price]
        level.remove(order)

        if len(level) == 0:
            del book[order.price]
        del self.resting[order.id]

    # ------------------------------------------------------------------
    # internals: the matching walk — the load-bearing 30 lines
    # ------------------------------------------------------------------

    def _crosses(self, order: Order, resting_price: int) -> bool:
        # does the incoming order cross
        # MARKET orders (price is None) cross unconditionally -> True.
        # shorter form: order.side.sign * (order.price - resting_price) >= 0

        if order.price is None:
            return True

        if order.side is Side.BUY:
            return order.price >= resting_price
        else:
            return order.price <= resting_price


    def _available_quantity(self, order: Order) -> int:
        # total size the order could fill against right now, WITHOUT mutating
        # anything. only FOK needs this: it must know the answer BEFORE any
        # fill happens, because a partial fill it would then have to unwind is
        # not something this design supports.
        against = self._book_against(order.side)

        # best-first iteration differs by side: ascending keys for asks,
        # descending for bids. getting this backwards makes FOK reject fillable
        # orders, intermittently and silently.
        # a plain `for` is safe here only because nothing in this method mutates.
        if against is self.asks:
            prices = against.keys()
        else:
            prices = reversed(against)

        total = 0
        for price in prices:
            if not self._crosses(order, price):
                break

            for resting in against[price]:
                # same-owner orders are CANCELLED by the STP branch in _match,
                # not filled, so they are not available depth. counting them
                # would let an FOK pass this check and then under-fill, which
                # is exactly the outcome FOK exists to prevent.
                if resting.trader_id is not None and resting.trader_id == order.trader_id:
                    continue
                total += resting.remaining

            if total >= order.quantity:
                break       # enough found; the true total is never needed

        return total

    def _match(self, order: Order) -> list[Trade]:
        """Walk the opposite side, filling while the order crosses.

        POSTCONDITION: no crossed book — on return, either order.remaining == 0,
        or the best opposite price no longer crosses order.price.
        """
        trades: list[Trade] = []
        against = self._book_against(order.side)

        # exit conditions
        while order.remaining > 0 and len(against) > 0:
            best_price = self._best_of(against)

            if not self._crosses(order, best_price):
                break

            level = against[best_price]
            resting = level.front       # front is oldest

            # self-trade prevention: same owner on both sides of the fill.
            # cancel the RESTING order and continue the walk (cancel-oldest),
            # rather than reject the incoming order. the aggressive order is
            # a CURRENT intent; the resting one is stale, and killing the
            # current intent to protect the stale one is backwards.
            
            if resting.trader_id is not None and resting.trader_id == order.trader_id:
                self._remove(resting)
                continue

            # min of the two remainders, so at least one of the pair is fully
            # filled every iteration, guarantees termination.
            quantity = min(order.remaining, resting.remaining)

            trade = Trade(
                price=best_price,
                quantity=quantity,
                maker_id=resting.id,
                taker_id=order.id,
                seq=self._next_seq(),
                taker_side=order.side,
            )

            order.fill(quantity)        # Order.fill owns the
            resting.fill(quantity)      # remaining >= 0 invariant

            # _remove, not level.popleft(): one exit path for a resting order,
            # so the empty-level deletion can't diverge between here and cancel
            if resting.is_filled:
                self._remove(resting)

            trades.append(trade)        # this call's fills
            self.trades.append(trade)   # the book's whole history

        return trades

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def submit(self, order: Order) -> list[Trade]:
        """The single entry point. Match crossed orders then apply the TIF.

        One method rather than add_limit_order + add_market_order: the Order
        already carries `type` and `tif`, so letting the caller pick a method
        duplicates that information and lets the two disagree.
        """
        if order.id in self.resting:
            raise ValueError(f"duplicate order id {order.id} already resting")

        # time priority is set by ARRIVAL, so this is stamped before matching.
        # an order that sweeps two levels and then rests keeps the queue
        # position it earned on arrival, not a worse one earned afterwards.
        order.seq = self._next_seq()

        # FOK is all-or-nothing and _match has no undo — it fills orders,
        # deletes levels and appends trades as it goes. so the decision has to
        # be made before a single fill happens.
        if order.tif is TimeInForce.FOK:
            available = self._available_quantity(order)
            if available < order.quantity:
                return []       # touched nothing: no fills, no book changes

        trades = self._match(order)

        # only GTC rests a remainder. IOC and FOK discard it, and MARKET can
        # never be GTC because Order.__post_init__ rejects that combination —
        # so testing tif alone is sufficient here. nothing to clean up either:
        # an unmatched incoming order was never in the book.
        if order.remaining > 0 and order.tif is TimeInForce.GTC:
            self._rest(order)

        return trades

    def cancel(self, order_id: int) -> bool:
        # usually racing a fill, so no error if doesn't exist
        
        if order_id not in self.resting:
            return False

        order = self.resting[order_id]
        self._remove(order)

        return True

    # ------------------------------------------------------------------
    # invariants — called by the fuzz suite after every operation
    # ------------------------------------------------------------------

    def assert_invariants(self) -> None:
        # lives on the book, not in tests, so the fuzz loop is a few lines and
        # every invariant has exactly one definition.
        # share conservation is NOT here — it spans the book and every order
        # ever submitted, so it belongs in the fuzz test itself.

        # 1. never crossed. strict <, because an equal best bid and ask is a
        #    LOCKED book: _crosses uses >=, so a bid at 42 should already have
        #    traded with an ask at 42.
        bid = self.best_bid
        ask = self.best_ask
        if bid is not None and ask is not None:
            assert bid < ask, f"crossed book: best bid {bid} >= best ask {ask}"

        ids_found_in_levels = set()

        for side in (Side.BUY, Side.SELL):
            book = self._book_for(side)

            for price in book:
                level = book[price]

                # 2. no empty levels. a stale empty deque makes _best_of report
                #    a price with no size behind it, and _match then reaches
                #    for level[0] and raises IndexError.
                assert len(level) > 0, f"empty level at price {price} on {side}"

                previous_seq = -1
                for order in level:
                    # 3. every resting order still has something to trade
                    assert order.remaining > 0, (
                        f"order {order.id} rests with remaining {order.remaining}"
                    )

                    # 4. the index agrees with the deques
                    assert order.id in self.resting, (
                        f"order {order.id} is in a level but not in self.resting"
                    )
                    assert self.resting[order.id] is order, (
                        f"self.resting[{order.id}] is a different object"
                    )
                    assert order.price == price, (
                        f"order {order.id} has price {order.price} "
                        f"but sits in level {price}"
                    )

                    # 5. side purity
                    assert order.side is side, (
                        f"order {order.id} is {order.side} in the {side} book"
                    )

                    # 6. queue order: seq strictly increasing front to back.
                    #    cheap, and catches priority corruption that no example
                    #    test would.
                    assert order.seq > previous_seq, (
                        f"order {order.id} has seq {order.seq} behind {previous_seq}"
                    )
                    previous_seq = order.seq

                    ids_found_in_levels.add(order.id)

                # 7. the linked list is intact in BOTH directions.
                #    this is the only check that catches a remove() which
                #    updates `next` but forgets `prev`, or the reverse: forward
                #    iteration stays perfectly correct, so invariants 2-6 above
                #    and every example test still pass while the backward chain
                #    silently rots. O(1) cancel is only correct if the two
                #    directions agree.
                assert level.head.prev is None, (
                    f"level {price} on {side}: head {level.head.id} has a prev"
                )
                assert level.tail.next is None, (
                    f"level {price} on {side}: tail {level.tail.id} has a next"
                )

                forward_ids = []
                for order in level:
                    forward_ids.append(order.id)

                backward_ids = []
                node = level.tail
                while node is not None:
                    backward_ids.append(node.id)
                    node = node.prev
                backward_ids.reverse()

                assert forward_ids == backward_ids, (
                    f"level {price} on {side}: forward walk {forward_ids} "
                    f"is not the reverse of the backward walk"
                )

                # 8. the cached count matches the chain it claims to count.
                #    if it drifts, `if len(level) == 0` either deletes a live
                #    level or keeps a dead one - and a dead level is invariant
                #    2's IndexError waiting to happen.
                assert level.count == len(forward_ids), (
                    f"level {price} on {side}: count is {level.count} but "
                    f"{len(forward_ids)} orders are chained"
                )

        # the other direction of invariant 4: nothing orphaned in the index
        assert ids_found_in_levels == set(self.resting.keys()), (
            "self.resting and the price levels hold different id sets"
        )
