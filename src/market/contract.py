'''
Complementary YES/NO tokens on one event.

THE ECONOMICS: one YES plus one NO always pays exactly 100 ticks, whatever
happens. So a complete set is worth 100, and any price at which you can buy the
set for less (or sell it for more) is an arbitrage.

Deliberately thin. This owns the PAIRING and the SETTLEMENT RULE, nothing else.
The books already handle matching, and a market that starts reaching into them
ends up duplicating the never-crossed invariant.
'''

FULL_SET_TICKS = 100


class BinaryMarket:
    def __init__(self, market_id, yes_book, no_book, value_process) -> None:
        # books are injected rather than constructed here, so tests can hand in
        # books with a deterministic seq_source.
        self.market_id = market_id
        self.yes_book = yes_book
        self.no_book = no_book
        self.value_process = value_process
        self.outcome = None

    @staticmethod
    def complementary_price(tick: int) -> int:
        '''
        A NO price of p is economically a YES price of (100 - p).

        This one line is the whole merged-book idea: a resting NO bid at 30 is
        an offer to sell YES at 70, so a YES buyer can source liquidity from
        either book.
        '''
        return FULL_SET_TICKS - tick

    @property
    def implied_yes_bid(self):
        '''
        The YES bid implied by the NO book.

        NOTE THE SIDE FLIP. The best NO **ask** implies a YES **bid**: buying
        NO cheaply is the same trade as selling YES dearly, so the cheapest
        offer of NO is the highest implied willingness to be short YES.

        Getting this backwards manufactures arbitrage everywhere, and the
        numbers look exciting rather than wrong. Test it before trusting it.
        '''
        best_ask = self.no_book.best_ask
        if best_ask is None:
            return None
        return self.complementary_price(best_ask)

    @property
    def implied_yes_ask(self):
        '''The mirror: the best NO bid implies a YES ask.'''
        best_bid = self.no_book.best_bid
        if best_bid is None:
            return None
        return self.complementary_price(best_bid)

    def resolve(self) -> int:
        '''
        Idempotent, like ValueProcess.resolve - the analysis layer may ask more
        than once, and re-drawing would give a different answer each time.
        '''
        if self.outcome is not None:
            return self.outcome
        self.outcome = self.value_process.resolve()
        return self.outcome

    def payoff(self, token: str) -> int:
        '''YES pays 100 * outcome; NO pays 100 * (1 - outcome).'''
        if self.outcome is None:
            raise ValueError("market has not resolved")
        if token == "YES":
            return self.outcome * FULL_SET_TICKS
        else:
            return (1 - self.outcome) * FULL_SET_TICKS


# ----------------------------------------------------------------------
# NOT BUILT: mint and merge
# ----------------------------------------------------------------------
# On a real venue you deposit 100 ticks of collateral and MINT one YES plus one
# NO, or MERGE a matched pair back into 100. That is what makes the arbitrage
# physically executable rather than merely observable.
#
# It needs collateral accounting in the portfolio and a new order path, and it
# changes nothing about DETECTION, which is what this project measures. A
# genuine extension, not a missing piece.
