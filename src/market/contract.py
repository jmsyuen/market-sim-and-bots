'''
Complementary YES/NO tokens on one event.

Deferred until now on purpose: everything before this ran on a single book,
and a single book was enough to build the engine, the flow and the maker.
Coherence arbitrage is the only thing that needs two.

THE ECONOMICS: one YES plus one NO always pays exactly 100 ticks, whatever
happens. So a complete set is worth 100, and any price at which you can buy the
set for less (or sell it for more) is an arbitrage.
'''


class BinaryMarket:
    '''
    Two books on one event, plus the resolution rule.

    Deliberately thin. It owns the PAIRING and the SETTLEMENT RULE, not any
    matching logic - the books already handle that, and a market that starts
    reaching into them will end up duplicating the never-crossed invariant.
    '''

    def __init__(self, market_id, yes_book, no_book, value_process) -> None:
        # books are injected, not constructed here, so tests can hand in books
        # with a deterministic seq_source.
        ...

    @staticmethod
    def complementary_price(tick: int) -> int:
        '''
        A NO price of p is economically a YES price of (100 - p).

        This one line is the whole merged-book idea: a resting NO bid at 30 is
        an offer to sell YES at 70, so a YES buyer can source liquidity from
        either book.
        '''
        ...

    @property
    def implied_yes_from_no(self):
        '''
        The YES price implied by the NO book's touch.

        NOTE THE SIDE FLIP: the best NO *ask* implies a YES *bid*, because
        buying NO cheaply is equivalent to selling YES dearly. Getting this
        backwards produces phantom arbitrage everywhere and is the single
        easiest mistake in this file. Write the test first.
        '''
        ...

    def resolve(self):
        '''
        Ask the value process for the outcome and record it. YES contracts pay
        outcome * 100, NO contracts pay (1 - outcome) * 100.

        Idempotent, like ValueProcess.resolve - the analysis layer may ask more
        than once.
        '''
        ...


# ----------------------------------------------------------------------
# DEFERRED - mint and merge. DO NOT BUILD TODAY.
# ----------------------------------------------------------------------
# On a real venue you can deposit 100 ticks of collateral and MINT one YES plus
# one NO, or MERGE a matched pair back into 100 ticks. That is what makes the
# arbitrage physically executable rather than just observable.
#
# Implementing it means collateral accounting in the portfolio and a new order
# path, and it changes nothing about the DETECTION in coherence.py. The CV
# bullet says "detected coherence arbitrage at executable prices" - detection
# is the whole claim, and executable refers to walking real depth net of fees,
# not to being able to mint.
#
# A genuine extension, not a missing piece.
