# inventory, cash, P&L and terminal settlement for one market.
#
# UNITS: everything here is in TICKS x CONTRACTS (i.e. cents). one unit system
# throughout, converted to dollars only for display. mixing units corrupts every
# number downstream and is nearly invisible, because the magnitudes still look
# plausible.

from src.orderbook.order import Side


class Portfolio:
    def __init__(self) -> None:
        # self.position = 0          # +ve long YES, -ve short YES, in contracts
        # self.cash = 0              # ticks
        # self.avg_cost = 0.0        # ticks per contract, of the CURRENT position
        # self.realised_pnl = 0      # ticks
        # self.fills = []            # list[(Trade, Side)] — metrics.py reads this
        ...

    # ------------------------------------------------------------------
    # fills
    # ------------------------------------------------------------------

    def on_fill(self, trade, our_side: Side) -> None:
        """Book one execution.

        our_side is PASSED IN and must not be read off the trade. You are
        usually the MAKER, so trade.taker_side is the other side of the fill —
        reading it inverts your position on every passive fill. This is exactly
        why Trade carries taker_side rather than a bare `side`.
        """
        # signed = trade.quantity * our_side.sign
        #
        # three cases, and the branch is not optional — a single formula that
        # doesn't distinguish them will be wrong on at least one:
        #
        #   OPENING or ADDING (position is 0, or signed has the same sign as
        #     position):  no P&L realised. avg_cost becomes the quantity-weighted
        #     average of the old cost basis and this fill price.
        #
        #   REDUCING (signed opposes position, |signed| <= |position|):
        #     realise (trade.price - avg_cost) * closed_quantity, signed by the
        #     direction of the OLD position — a long closed above cost is a
        #     gain, a short closed above cost is a loss.
        #     avg_cost is UNCHANGED. You are closing, not repricing.
        #
        #   FLIPPING (signed opposes position, |signed| > |position|):
        #     realise on the |position| contracts that close, then the remaining
        #     |signed| - |position| OPENS a fresh position in the new direction
        #     with avg_cost reset to trade.price. This is the case everyone gets
        #     wrong; write the test first.
        #
        # then, unconditionally:
        #   cash -= trade.price * signed       (buy spends cash, sell receives)
        #   position += signed
        #   if position == 0: avg_cost = 0.0   (no basis without a position)
        #   self.fills.append((trade, our_side))
        ...

    # ------------------------------------------------------------------
    # marking
    # ------------------------------------------------------------------

    def unrealised_pnl(self, book) -> int | None:
        """Mark open inventory at the EXIT side, not the mid.

        Long marks at best_bid, short at best_ask. The mid flatters P&L by
        assuming you can close where nobody is trading — and for a market maker
        sitting on inventory, that is precisely what you cannot do.

        Returns None when the exit side is empty. Say so; do not silently fall
        back to the mid.
        """
        # if position == 0: return 0
        # mark = book.best_bid if long else book.best_ask
        # if mark is None: return None
        # return round((mark - self.avg_cost) * self.position)
        ...

    def total_pnl(self, book) -> int | None:
        # realised + unrealised, None if unrealised is None.
        #
        # sanity check worth asserting in a test: once flat, total_pnl should
        # equal self.cash exactly. if it doesn't, a sign convention is
        # inconsistent between on_fill and the marking.
        ...

    # ------------------------------------------------------------------
    # resolution
    # ------------------------------------------------------------------

    def settle(self, outcome: int) -> None:
        """Terminal cash flow. A YES contract pays 100 ticks if the event
        happened and 0 if it didn't; a short YES pays the negative of that."""
        # payoff_per_contract = outcome * 100
        # realise (payoff_per_contract - avg_cost) * position
        # cash += payoff_per_contract * position
        # position = 0; avg_cost = 0.0
        ...


# ----------------------------------------------------------------------
# tests worth writing (tests/test_portfolio.py)
# ----------------------------------------------------------------------
# 1. buy 10 @ 40, sell 10 @ 45  -> realised 50, position 0, avg_cost 0
# 2. buy 10 @ 40, buy 10 @ 50   -> position 20, avg_cost 45, realised 0
# 3. buy 10 @ 40, sell 4 @ 45   -> realised 20, position 6, avg_cost STILL 40
# 4. buy 10 @ 40, sell 15 @ 45  -> realised 50, position -5, avg_cost 45
#    (the flip case — this is the one that will fail first)
# 5. short: sell 10 @ 60, buy 10 @ 55 -> realised 50
# 6. maker-side attribution: build a Trade with taker_side=BUY, call
#    on_fill(trade, Side.SELL), assert position went NEGATIVE. this is the
#    regression test for reading taker_side instead of our_side.
# 7. long 10 @ 40, settle(1) -> realised 600. settle(0) -> realised -400.
# 8. once flat, total_pnl(book) == cash
