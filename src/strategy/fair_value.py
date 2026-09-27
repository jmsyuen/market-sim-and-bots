'''
Bayesian fair value: P(event), starting from the book and updated by flow.

micro_price (with no parameters) derived from the book. 
Fair value is what we believe after using our own evidence the book has not priced yet.
this file bridges the two.

THE SHAPE
    Beta(a, b) is a distribution over a probability. Its mean is a / (a + b),
    and a + b is how strongly you hold that mean - Beta(8, 2) and Beta(80, 20)
    both say 0.8, but the second says it far more firmly.

    Beta is CONJUGATE for yes/no evidence, which is the only reason to pick it:
    the posterior after an observation is just a += w or b += w. No integration,
    no numerics.

    The prior comes from the micro-price:
        a0 = micro_p * prior_strength
        b0 = (1 - micro_p) * prior_strength

    and the posterior mean is
        (a0 + evidence_a) / (prior_strength + evidence_a + evidence_b)

    which is a PRECISION-WEIGHTED blend, not a simple average. With thin
    evidence it sits almost exactly on the micro-price; as evidence accumulates
    it pulls away, and how far depends on the evidence relative to
    prior_strength. That distinction is what an interviewer will ask about.

UNITS - the bug you will actually hit.
    micro_price is in TICKS (1..99). Beta works in PROBABILITY (0,1). The
    conversion happens twice, in opposite directions, and getting one wrong
    gives a fair value of 0.5 where you expected 50. Convert at the boundary
    and keep the middle of this file unit-free.

file outputs:
fair_value.value(book)                  # float in ticks (1..99), or None
fair_value.probability(book)            # float in (0,1), value(book) / 100
fair_value.observe(trade)               # fold one trade's taker_side into the posterior
'''

from src.orderbook.order import Side
TICK_MIN = 1
TICK_MAX = 99


class FairValue:
    def __init__(self, prior_strength: float = 20.0,
                 evidence_weight: float = 0.05,
                 half_life: float = 0.05) -> None:
        '''
        prior_strength  - how many pseudo-observations the micro-price is worth. Low means flow moves you fast and you chase
                          noise; high means you barely move, 
                          default 20 for a few hundred trades in book.

        evidence_weight - pseudo-observations per contract of aggressive flow.
                          "how informative do I think the tape is".

        half_life       - how fast evidence decays, in sim time units.
                          
        '''
        self.prior_strength = prior_strength
        self.evidence_weight = evidence_weight
        self.half_life = half_life

        # accumulated pseudo-observations. these are the ONLY state.
        self.evidence_a = 0.0
        self.evidence_b = 0.0

        # how far through book.trades we have already read. see value().
        self._last_trade_index = 0
        self._last_time = None

    # ------------------------------------------------------------------
    # evidence
    # ------------------------------------------------------------------

    def observe(self, trade) -> None:
        '''
        Fold one trade into the posterior.

            taker bought  -> evidence for YES  -> evidence_a
            taker sold    -> evidence for NO   -> evidence_b

        '''
        if trade.taker_side is Side.BUY:
            self.evidence_a += self.evidence_weight * trade.quantity
        else:
            self.evidence_b += self.evidence_weight * trade.quantity
        

    def _decay(self, time: float) -> None:
        '''
        Halve the accumulated evidence every half_life.

        Same irregular-gap EWMA shape as the volatility estimator in
        market_maker.py: decay = 0.5 ** (dt / half_life), applied to BOTH
        counters.
        Decaying only one silently skews fair value one way.

        Guard the first call (self._last_time is None) and dt <= 0.
        '''
        if self._last_time is None:     # nothing to decay from
            self._last_time = time
            return
        
        dt = time - self._last_time
        if dt <= 0:
            return
        
        factor = 0.5 ** (dt / self.half_life)
        
        self.evidence_a *= factor
        self.evidence_b *= factor
        self._last_time = time

    # ------------------------------------------------------------------
    # the estimate
    # ------------------------------------------------------------------

    def value(self, book, time: float = 0.0) -> float | None:
        '''
        The posterior mean, in TICKS. None when the book has no micro-price.

        Three steps, in order:

        1. DECAY FIRST, using `time`. Decay then drain, not the other way
           round: draining first and decaying afterwards would age the trades
           you just read by the whole interval, including the part of it that
           elapsed before they happened.

        2. DRAIN THE TAPE. Read book.trades[self._last_trade_index:], call
           observe on each, then advance the pointer to len(book.trades).

           Doing it here rather than through an engine hook is deliberate: the
           model learns from ALL flow, not just the maker's own fills, and it
           needs no change to the engine. It also reads honestly - a fair-value
           model watches the tape.

        3. Re-derive the prior from the CURRENT micro-price and return the
           posterior mean.

           Re-deriving every call is the part people get wrong. Fix the prior
           once in __init__ and the posterior wanders off and never comes back
           when the market moves - the prior is supposed to be the market's
           current view, not its view at t=0.
        '''
        micro_tick = book.micro_price
        if micro_tick is None: 
            return None
        
        # decay evidence and observe trades in whole tape
        self._decay(time)
        for trade in book.trades[self._last_trade_index:]:
            self.observe(trade)
        self._last_trade_index = len(book.trades)


        micro_p = micro_tick / 100.0
        a = micro_p * self.prior_strength + self.evidence_a
        b = (1.0 - micro_p) * self.prior_strength + self.evidence_b
        
        posterior_mean = a / (a + b)          # probability (beta dist)

        # convert back to ticks and clamp to keep within 1-99
        # but stays float to keep sub-tick precision for the maker's calculations
        fair_tick = posterior_mean * 100.0
        if fair_tick < TICK_MIN:
            return float(TICK_MIN)
        if fair_tick > TICK_MAX:
            return float(TICK_MAX)
        return fair_tick
        

    def probability(self, book, time: float = 0.0) -> float | None:
        '''In (0,1), for calibration.py. Just value() / 100.'''
        fair_tick = self.value(book, time)
        if fair_tick is None:
            return None
        return fair_tick / 100.0
