'''
Inventory, cash, P&L and terminal settlement for one market.

UNITS: everything here is TICKS x CONTRACTS, i.e. cents. One unit system
throughout, converted to dollars only for display. Mixing units corrupts every
number downstream and is nearly invisible, because the magnitudes still look
plausible.

SIGN CONVENTION: position is positive when long YES and negative when short
YES. A short YES position is economically long NO.
'''

from src.orderbook.order import Side


class Portfolio:
    def __init__(self) -> None:
        self.position = 0
        self.cash = 0.0
        self.avg_cost = 0.0
        self.realised_pnl = 0.0
        self.fills = []

    def on_fill(self, trade, our_side: Side) -> None:
        '''
        Book one execution.

        our_side is PASSED IN and must never be read off the trade. A market
        maker is usually the MAKER, so trade.taker_side is the OTHER side of
        the fill - using it would invert the position on every passive fill and
        flip the sign of all P&L. That is exactly why Trade carries taker_side
        rather than a bare side: the name makes the mistake visible.

        Three cases, and the branch is not optional. A single formula that does
        not distinguish them is wrong on at least one.
        '''
        signed = trade.quantity * our_side.sign

        if self.position == 0:
            same_direction = True
        elif self.position > 0 and signed > 0:
            same_direction = True
        elif self.position < 0 and signed < 0:
            same_direction = True
        else:
            same_direction = False

        if same_direction:
            self._open_or_add(trade)
        elif abs(signed) <= abs(self.position):
            self._reduce(trade, trade.quantity)
        else:
            self._flip(trade)

        self.cash -= trade.price * signed
        self.position += signed

        if self.position == 0:
            self.avg_cost = 0.0

        self.fills.append((trade, our_side))

    def _open_or_add(self, trade) -> None:
        '''
        No P&L is realised. avg_cost becomes the quantity-weighted average of
        the existing basis and this fill.
        '''
        old_quantity = abs(self.position)
        new_quantity = old_quantity + trade.quantity
        total_cost = self.avg_cost * old_quantity + trade.price * trade.quantity
        self.avg_cost = total_cost / new_quantity

    def _reduce(self, trade, closed_quantity: int) -> None:
        '''
        Realise on the contracts that close, signed by the direction of the OLD
        position: a long closed above cost is a gain, a short closed above cost
        is a loss.

        avg_cost is deliberately UNCHANGED. Closing a position does not reprice
        the contracts that remain.
        '''
        if self.position > 0:
            direction = 1
        else:
            direction = -1

        self.realised_pnl += (trade.price - self.avg_cost) * closed_quantity * direction

    def _flip(self, trade) -> None:
        '''
        The fill is larger than the position, so it closes everything and opens
        a fresh position on the other side. The new position's basis is this
        fill's price - the old basis is gone.

        This is the case everyone gets wrong. Write the test first.
        '''
        self._reduce(trade, abs(self.position))
        self.avg_cost = float(trade.price)

    def unrealised_pnl(self, book) -> float | None:
        '''
        Mark open inventory at the EXIT side, never the mid. Long marks at the
        best bid, short at the best ask.

        The mid flatters P&L by assuming you can close where nobody is trading,
        and for a market maker sitting on unwanted inventory that is precisely
        what you cannot do.

        Returns None when the exit side is empty. Say so rather than silently
        falling back to the mid.
        '''
        if self.position == 0:
            return 0.0

        if self.position > 0:
            mark = book.best_bid
        else:
            mark = book.best_ask

        if mark is None:
            return None

        return (mark - self.avg_cost) * self.position

    def total_pnl(self, book) -> float | None:
        unrealised = self.unrealised_pnl(book)
        if unrealised is None:
            return None
        return self.realised_pnl + unrealised

    def settle(self, outcome: int) -> None:
        '''
        Terminal cash flow. A YES contract pays 100 ticks if the event happened
        and 0 if it did not; a short YES pays the negative of that.

        Settlement is just a fill at a price of 0 or 100 that closes everything,
        so it realises P&L the same way a closing trade does.
        '''
        payoff_per_contract = outcome * 100

        self.realised_pnl += (payoff_per_contract - self.avg_cost) * self.position
        self.cash += payoff_per_contract * self.position
        self.position = 0
        self.avg_cost = 0.0
