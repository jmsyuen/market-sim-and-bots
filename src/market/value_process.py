# the latent true probability of the event, and the terminal resolution.
#
# this is GROUND TRUTH. only InformedTrader (through a noisy lens) and the
# analysis layer may read it. if the market maker can see true_p, every result
# in the project is void.
#
# STATE IS x, THE LOG-ODDS. p is a read-only view of it. two reasons, both of
# which bite if you store p instead:
#   1. logit(sigmoid(x)) does not return exactly x. storing p means a round trip
#      every step, and over 100k steps the error accumulates. storing x means
#      the state is never transformed, so it never degrades.
#   2. sigmoid(x) returns EXACTLY 1.0 once x passes about 37, because
#      1 + exp(-37) rounds to 1.0 in float64. logit(1.0) then divides by zero.
#      a 100k-step run at high vol reaches x = 37 easily. storing x makes the
#      crash structurally impossible rather than merely unlikely.

import math
import random


class ValueProcess:
    """P(event) in (0,1), drifting in logit space, resolving to 0 or 1."""

    def __init__(self, p0: float, vol: float, resolve_time: float, seed: int | None = None) -> None:
        # vol is in LOGIT units per sqrt(unit time), NOT probability units.
        # near p=0.5 the sigmoid slope is 0.25, so a logit shock of 0.1 moves p
        # by about 0.025; near p=0.95 the slope is 0.0475 and the same shock
        # moves p by 0.005. that asymmetry is the point, not a defect.
        #
        # suggested units: t in [0, 1] with resolve_time = 1.0. then vol reads
        # directly as "total logit wander over the market's life", which makes
        # the parameter interpretable instead of arbitrary. vol = 1.0 puts 95%
        # of terminal probabilities inside [12, 88] ticks - a healthy market.

        # self.x = self._logit(p0)      # THE STATE. log-odds, unbounded.
        # self.vol = vol
        # self.resolve_time = resolve_time
        # self.last_time = 0.0
        # self.outcome = None

        # an OWN generator, not the `random` module. sharing the global means a
        # change to the trader mix shifts the value path, and the controlled
        # counterfactual stops being controlled.
        # self.rng = random.Random(seed)
        ...

    # ------------------------------------------------------------------
    # the transform. write these FIRST and test them as an inverse pair
    # before anything else touches them.
    # ------------------------------------------------------------------

    def _logit(self, p: float) -> float:
        # ln(p / (1 - p)). maps (0,1) -> (-inf, +inf): the log-odds.
        # called ONCE, in __init__. never on the hot path.
        ...

    def _sigmoid(self, x: float) -> float:
        # 1 / (1 + exp(-x)). the inverse.
        #
        # math.exp(-x) overflows for x around -745. if that ever bites, branch
        # on the sign of x and use exp(x) / (1 + exp(x)) when x < 0.
        ...

    # ------------------------------------------------------------------
    # reading the value
    # ------------------------------------------------------------------

    @property
    def p(self) -> float:
        """The latent probability. A VIEW of self.x, never stored.

        Nothing writes to this. If you find yourself wanting a setter, the
        thing you actually want is to change self.x.
        """
        # return self._sigmoid(self.x)
        ...

    @property
    def tick_price(self) -> float:
        """The latent value in the book's units (1..99 ticks).
        Traders compare against micro_price, which is in ticks."""
        # return self.p * 100
        ...

    # ------------------------------------------------------------------
    # evolution
    # ------------------------------------------------------------------

    def advance_to(self, time: float) -> float:
        """Step the walk forward to `time`. Returns the new p.

        advance_to, not step(): the engine is event-driven, so the gap between
        events varies. A fixed-size step would make realised volatility depend
        on how busy the market happens to be.
        """
        # dt = time - self.last_time
        # if dt <= 0: return self.p          (events can share a timestamp)
        #
        # self.x += self.rng.gauss(0, self.vol * math.sqrt(dt))
        #                                     ^^^^^^^^ sqrt(dt), NOT dt.
        #      variance accumulates linearly in time, so standard deviation
        #      goes as the square root. scaling by dt makes vol a function of
        #      the event rate, which silently confounds every experiment.
        #
        # self.last_time = time
        # return self.p
        #
        # note there is no transform in this method at all. that is the payoff
        # from storing x.
        #
        # OPTIONAL, and worth understanding before deciding:
        #   x is a martingale but p = sigmoid(x) is NOT, because sigmoid is
        #   nonlinear (Jensen's inequality). p gets a pull toward 0.5, which
        #   means a trader could earn from the drift alone with no information.
        #   at vol = 1 and p = 0.9 that is about 0.4 logit units over the run,
        #   roughly 3.6 ticks - not negligible.
        #   to remove it exactly, add a compensating drift BEFORE the shock:
        #       self.x += (self.p - 0.5) * self.vol ** 2 * dt
        #   derivation: E[dp] = 0 needs mu = -0.5 * (sigmoid''/sigmoid') * vol^2,
        #   and sigmoid''/sigmoid' = (1 - 2p), giving mu = (p - 0.5) * vol^2.
        ...

    def resolve(self) -> int:
        """Draw the terminal outcome. Idempotent - resolving twice gives the
        same answer, because the analysis layer may ask more than once."""
        # if self.outcome is not None: return self.outcome
        #
        # Bernoulli(self.p), NOT round(self.p). rounding makes the market
        # perfectly predictable at the end and destroys the calibration
        # analysis - a model that just reported p would score a perfect Brier.
        # self.outcome = 1 if self.rng.random() < self.p else 0
        # return self.outcome
        ...


# ----------------------------------------------------------------------
# tests worth writing (tests/test_value_process.py)
# ----------------------------------------------------------------------
# 0. sigmoid(logit(p)) is close to p across 0.01..0.99, and logit(0.5) == 0.
#    two minutes, and it catches a sign error before it can hide inside the
#    walk where it would look like "volatility is behaving oddly"
# 1. p stays strictly inside (0,1) over 100_000 steps at vol=2.0
#    - this is the whole reason for the logit transform; assert it directly
# 2. the same seed produces the same path twice, and two different seeds do not
# 3. advance_to with a time that has already passed is a no-op
# 4. resolve() twice returns the same value
# 5. over many seeds, the mean outcome at p0=0.5 is near 0.5. a clipping bug in
#    probability space would bias this away from 0.5 - this is the test that
#    catches the mistake the logit transform exists to prevent
# 6. realised terminal spread scales with sqrt(T), not T. run to T=1 and T=4
#    over many seeds; the standard deviation of terminal x should roughly
#    double, not quadruple. catches a dt-instead-of-sqrt(dt) bug


# ----------------------------------------------------------------------
# IF YOU TAKE THE GAP / NEWS FEATURE (not implemented above)
# ----------------------------------------------------------------------
# what changes here, and nothing else in this file:
#
#   __init__ gains, all defaulting to off so the simple case is unchanged:
#       decision_time = None    -> defaults to resolve_time
#       news_times    = ()      -> SCHEDULED news, public knowledge
#       jump_vol      = 0.0     -> jump size, several x vol
#       surprise_rate = 0.0     -> Poisson rate for UNSCHEDULED news
#
#   build one sorted list of (time, is_scheduled) in __init__: the given
#   news_times marked scheduled, plus Poisson draws up to decision_time marked
#   unscheduled. expose the scheduled times as a public read-only attribute -
#   news TIMING is public (earnings dates get announced) even though news
#   CONTENT is not. that asymmetry is what the whole experiment rests on.
#
#   advance_to applies any events falling inside (last_time, time]:
#       self.x += rng.gauss(0, jump_vol)     once per event
#   everything in log-odds space is additive, so you do NOT need to split dt
#   and diffuse between events - one diffusion draw for the whole dt plus one
#   draw per event gives the identical endpoint. the intermediate path is never
#   observed, because the engine only reads x at event times.
#
#   decision_time splits "the answer becomes known" from "the market settles".
#   draw the outcome at decision_time and stop walking; p returns the outcome
#   from then on. this is what creates the resolution hazard that
#   resolution-aware widening exists to defend against - without it, that
#   feature measures exactly zero and looks useless.
#
# the engine must schedule NEWS on its own heap and let a trader arrive
# immediately after. if the jump is only applied whenever the next trader
# happens to show up, nobody picks off the stale quotes and you measure
# nothing.
