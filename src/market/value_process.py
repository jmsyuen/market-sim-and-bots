# the latent true probability of the event, and the terminal resolution.
#
# this is GROUND TRUTH. only InformedTrader (through a noisy lens) and the
# analysis layer may read it. if the market maker can see true_p, every result
# in the project is void.

import math
import random


class ValueProcess:
    """P(event) in (0,1), drifting in logit space, resolving to 0 or 1."""

    def __init__(self, p0: float, vol: float, resolve_time: float, seed: int | None = None) -> None:
        # vol is in LOGIT units per sqrt(unit time), NOT probability units.
        # near p=0.5 the sigmoid slope is 0.25, so a logit shock of 0.1 moves p
        # by about 0.025; near p=0.95 the slope is 0.0475 and the same shock
        # moves p by 0.005. that asymmetry is the point, not a defect.

        # self.p = p0
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
    # the transform
    # ------------------------------------------------------------------

    def _logit(self, p: float) -> float:
        # ln(p / (1 - p)). maps (0,1) -> (-inf, +inf): the log-odds.
        ...

    def _sigmoid(self, x: float) -> float:
        # 1 / (1 + exp(-x)). the inverse.
        #
        # math.exp(-x) overflows for x around -745. that needs a very long run
        # at high vol to reach, but if it bites, the standard guard is to
        # branch on the sign of x and use exp(x) / (1 + exp(x)) when x < 0.
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
        # x = self._logit(self.p)
        # x += self.rng.gauss(0, self.vol * math.sqrt(dt))
        #      ^^^^^^^^^^^^^ sqrt(dt), NOT dt. variance accumulates linearly in
        #      time, so standard deviation goes as the square root. scaling by
        #      dt makes vol a function of the event rate.
        # self.p = self._sigmoid(x)
        # self.last_time = time
        # return self.p
        #
        # OPTIONAL, and worth understanding before deciding:
        #   x is a martingale but p = sigmoid(x) is NOT, because sigmoid is
        #   nonlinear (Jensen's inequality). the probability gets a slight pull
        #   toward 0.5, which means an informed trader could earn a little from
        #   the drift alone with no information at all.
        #   the effect is second-order and small at sane vol, and it does not
        #   break calibration — the outcome is still drawn from the final p, so
        #   the model stays internally consistent.
        #   to remove it exactly, add a compensating drift BEFORE the shock:
        #       x += (self.p - 0.5) * self.vol ** 2 * dt
        #   derivation: E[dp] = 0 needs mu = -0.5 * (sigmoid''/sigmoid') * vol^2,
        #   and sigmoid''/sigmoid' = (1 - 2p), giving mu = (p - 0.5) * vol^2.
        ...

    def resolve(self) -> int:
        """Draw the terminal outcome. Idempotent — resolving twice gives the
        same answer, because the analysis layer may ask more than once."""
        # if self.outcome is not None: return self.outcome
        #
        # Bernoulli(self.p), NOT round(self.p). rounding makes the market
        # perfectly predictable at the end and destroys the calibration
        # analysis — a model that just reports p would score a perfect Brier.
        # self.outcome = 1 if self.rng.random() < self.p else 0
        # return self.outcome
        ...

    # ------------------------------------------------------------------
    # convenience for the engine and traders
    # ------------------------------------------------------------------

    @property
    def tick_price(self) -> float:
        """The latent value expressed in the book's units (1..99 ticks).
        Traders compare against micro_price, which is in ticks."""
        # return self.p * 100
        ...


# ----------------------------------------------------------------------
# tests worth writing (tests/test_value_process.py)
# ----------------------------------------------------------------------
# 1. p stays strictly inside (0,1) over 100_000 steps at vol=2.0
#    — this is the whole reason for the logit transform; assert it directly
# 2. the same seed produces the same path twice, and two different seeds do not
# 3. advance_to with a time that has already passed is a no-op
# 4. resolve() twice returns the same value
# 5. over many seeds, the mean outcome at p0=0.5 is near 0.5 (a clipping bug
#    in probability space would bias this away from 0.5 — this is the test
#    that catches the mistake the logit transform exists to prevent)
