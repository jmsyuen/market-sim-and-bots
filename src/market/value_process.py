'''
Mode A simulation, value_process:

x is a hidden underlying value on the real line, log-odds so we don't have to clip to make it fit within (0,1),
p = sigmoid(x), converting x to a probability in (0,1),
then every step x is affected by a volatility scaled random walk pulled from a gaussian distribution,
and x is also affected by a state-dependent drift, (p - 0.5) * vol**2 * dt, to make p a martingale
and correct for the pull towards 0.5 that sigmoid's curvature would otherwise create,
this value process is also affected by jumps (simulated news events), both scheduled and unscheduled.
a jump is a single volatility spike which scales the walk action.
informed traders see this x with noise added to it in logit space,
they trade towards it to simulate a more accurate estimate of the market.
the outcome is drawn from a Bernoulli at DECISION_TIME, which comes at or before
resolve_time. between the two, the answer is known and stale quotes sit in the book -
that window is the resolution hazard that resolution-aware quoting exists to defend against.

'''

import math
import random


class ValueProcess:
    """P(event) in (0,1), drifting in logit space, resolving to 0 or 1."""

    def __init__(
        self,
        p0: float,
        vol: float,
        resolve_time: float,
        seed: int | None = None,
        decision_time: float | None = None,
        news_times: tuple[float, ...] = (),
        jump_vol: float = 0.0,
        surprise_rate: float = 0.0,
    ) -> None:

        '''
        units: t in [0, 1] with resolve_time = 1.0.
        so vol reads as "total logit wander over the market's life" instead of an arbitrary parameter
        vol = 1.0 puts 95% of terminal probabilities inside [12, 88] ticks - a healthy market.
        '''

        self.x = self._logit(p0)      # THE STATE. log-odds, unbounded.
        self.vol = vol
        self.jump_vol = jump_vol
        self.resolve_time = resolve_time
        self.last_time = 0.0
        self.outcome = None
        self.rng = random.Random(seed)

        if decision_time is None:
            self.decision_time = resolve_time
        else:
            self.decision_time = decision_time


        # news schedule, one sorted list of (time, is_scheduled) pairs
        #   - every entry in news_times, marked True  (scheduled)
        #   - Poisson arrivals at rate surprise_rate, marked False (unscheduled)
        events = []                       

        for news_time in news_times:
            if news_time < self.decision_time:
                events.append((news_time, True))

        if surprise_rate > 0.0:
            surprise_time = 0.0
            while True:
                surprise_time += self.rng.expovariate(surprise_rate)
                if surprise_time >= self.decision_time:
                    break
                events.append((surprise_time, False))

        events.sort()
        self._news_events = events
        self._news_index = 0              # forward pointer, see advance_to


        # public news events, anyone is allowed to read this
        scheduled_only = []
        for event_time, is_scheduled in self._news_events:
            if is_scheduled:
                scheduled_only.append(event_time)
        self.scheduled_news_times = tuple(scheduled_only)


    def _logit(self, p: float) -> float:
        # called only to initialise
        return math.log(p / (1.0 - p))

    def _sigmoid(self, x: float) -> float:
        """ Maps (-inf, +inf) -> (0,1), Real to probability.
        math.exp(-x) overflows for x around -745, but the walk will not reach that
        """
        return 1.0 / (1.0 + math.exp(-x))

    # ------------------------------------------------------------------
    # reading the value
    # ------------------------------------------------------------------

    @property
    def p(self) -> float:
        if self.outcome is not None:
            return float(self.outcome)

        return self._sigmoid(self.x)


    @property
    def tick_price(self) -> float:
        # convert to ticks.
        # NOTE: returns 0.0 or 100.0 once decided, outside book's legal 1..99, 
        # any trader deriving a price from this must clamp, or the book rejects order
        return self.p * 100


    # ------------------------------------------------------------------
    # evolution
    # ------------------------------------------------------------------

    def advance_to(self, time: float) -> float:
        """Step the walk forward to `time`. Returns the new p.

        advance_to, not step() as engine is event-driven, so the gap between
        events varies. A fixed-size step would make realised volatility depend
        on how busy the market happens to be.

        Order: freeze check -> clamp -> drift -> diffusion -> jumps.
        """
        # walk frozen once market resolves
        if self.outcome is not None:
            return self.p

        # clamp the target to decision_time. a call that overshoots must only diffuse as
        # far as the freeze point, or the last interval gets more volatility than it should.
        if time < self.decision_time:
            target = time
        else:
            target = self.decision_time

        dt = target - self.last_time
        if dt <= 0:
            return self.p          # events can share a timestamp


        
        # add volatility scaled shock with martingale drift correction
        self.x += (self.p - 0.5) * self.vol ** 2 * dt
        self.x += self.rng.gauss(0, self.vol * math.sqrt(dt))      
        # x has no drift, but p = sigmoid(x) does, because sigmoid is curved: 
        # a shock closer to the boundary has less effect than near midpoint.


        
        # walk forward from self._news_index rather than rescanning the whole schedule
        while self._news_index < len(self._news_events):
            event_time, is_scheduled = self._news_events[self._news_index]
            if event_time > target:
                break
            self.x += self.rng.gauss(0, self.jump_vol)
            self._news_index += 1

        self.last_time = target

        # call resolve after decision_time
        if target >= self.decision_time:
            self.resolve()

        return self.p


    def resolve(self) -> int:
        # draw the terminal outcome from Bernoulli dist.
        if self.outcome is not None:
            return self.outcome

        if self.rng.random() < self.p:
            self.outcome = 1
        else:
            self.outcome = 0

        return self.outcome
