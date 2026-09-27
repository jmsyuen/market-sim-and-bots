'''
The market maker.

Each layer sits on the previous one, and each is a separate experiment.

    0. fair value          where to centre the quotes
    1. cost floor          the minimum spread that is not a donation
    2. inventory skew      shift BOTH quotes to push position back to zero
    3. volatility scaling  wider when the price is moving
    4. event awareness     wider near scheduled news and near resolution
    5. position limits     stop quoting the side that grows the position
    6. clamp               keep ticks legal and the pair non-crossed

FixedSpreadMaker in sim/engine.py is layer 0 alone: the control every number is
measured against.

INTERFACE: quotes(book, portfolio, time) -> (bid, ask, size) or None. Either
leg may be None; the engine handles a suppressed side.
'''

import math

from src.orderbook.order import Side

TICK_MIN = 1
TICK_MAX = 99


def clamp_tick(tick: int) -> int:
    if tick < TICK_MIN:
        return TICK_MIN
    if tick > TICK_MAX:
        return TICK_MAX
    return tick


class MarketMaker:
    def __init__(self, trader_id: int, base_half_spread: float, size: int,
                 max_position: int, risk_aversion: float = 0.0,
                 vol_half_life: float = 0.05, vol_sensitivity: float = 0.0,
                 fee_per_contract: float = 0.0,
                 scheduled_news_times: tuple = (), news_buffer: float = 0.0,
                 news_widening: float = 0.0,
                 decision_time: float = 1.0, resolution_sensitivity: float = 0.0,
                 fair_value=None) -> None:
        '''
        EVERY FEATURE IS OFF AT ITS DEFAULT. With risk_aversion, vol_sensitivity,
        news_widening and resolution_sensitivity all zero and fair_value None,
        this reproduces FixedSpreadMaker exactly. That equivalence is asserted
        in the tests, and it is what makes any later difference attributable to
        the strategy rather than to a changed code path.

        trader_id        - distinct from every trader, or self-trade prevention
                           cancels your own quotes.
        base_half_spread - ticks either side of the reservation price.
        risk_aversion    - gamma in the Avellaneda-Stoikov skew.
        vol_half_life    - how fast the volatility estimate forgets.
        vol_sensitivity  - extra ticks of half-spread per unit of volatility.
        fee_per_contract - the cost floor.
        scheduled_news_times / news_buffer / news_widening - widen ahead of a
                           KNOWN event. Pass value_process.scheduled_news_times,
                           never the value process itself: that object is one
                           autocomplete away from .x, which would void every
                           number in the project.
        fair_value       - an object with .value(book, time), or None to use
                           the book's micro_price.
        '''
        self.trader_id = trader_id
        self.base_half_spread = base_half_spread
        self.size = size
        self.max_position = max_position
        self.risk_aversion = risk_aversion
        self.vol_half_life = vol_half_life
        self.vol_sensitivity = vol_sensitivity
        self.fee_per_contract = fee_per_contract
        self.scheduled_news_times = scheduled_news_times
        self.news_buffer = news_buffer
        self.news_widening = news_widening
        self.decision_time = decision_time
        self.resolution_sensitivity = resolution_sensitivity
        self.fair_value = fair_value

        # the engine owns these two; see engine._attribute
        self.resting_ids = set()
        self.recent_ids = set()

        # volatility estimator state
        self.vol_estimate = 0.0
        self._last_reference = None
        self._last_time = None

    # ------------------------------------------------------------------
    # layer 0 - fair value
    # ------------------------------------------------------------------

    def _reference(self, book, time):
        '''
        Where the quotes are centred.

        `time` is passed through because FairValue decays its evidence and
        needs a clock. Dropping it makes decay silently never fire, and the
        estimate then drifts away from the book with nothing raising.

        This is the ONLY method here that touches `book`. Everything below
        works on plain numbers, so swapping venue or fair-value model is a
        one-method change.
        '''
        if self.fair_value is not None:
            return self.fair_value.value(book, time)
        else:
            return book.micro_price

    # ------------------------------------------------------------------
    # layer 3 - volatility estimate
    # ------------------------------------------------------------------

    def _update_volatility(self, reference: float, time: float) -> None:
        '''
        EWMA of |move| / sqrt(dt), in ticks per sqrt(time).

        The sqrt(dt) normalisation is the whole point: without it, requoting
        twice as often halves the measured volatility, so the spread narrows
        precisely when you are paying most attention.

        The decay weight is 0.5 ** (dt / half_life) rather than a fixed
        constant, for the same reason - a fixed weight reintroduces the
        frequency dependence the normalisation just removed.

        NOTE this measures DIFFUSION, not drift. A price moving in a straight
        line registers as less volatile the more finely you sample it, because
        a trend's move scales with dt while a diffusion's scales with sqrt(dt).
        That is correct behaviour, not a bug.
        '''
        if self._last_reference is None or self._last_time is None:
            self._last_reference = reference
            self._last_time = time
            return

        dt = time - self._last_time
        if dt <= 0:
            return

        move = (reference - self._last_reference) / math.sqrt(dt)
        decay = 0.5 ** (dt / self.vol_half_life)
        self.vol_estimate = decay * self.vol_estimate + (1.0 - decay) * abs(move)

        self._last_reference = reference
        self._last_time = time

    # ------------------------------------------------------------------
    # layers 1, 3, 4 - the half-spread
    # ------------------------------------------------------------------

    def _half_spread(self, time: float) -> float:
        '''
        Base, then every widening term. They ADD; none replaces another.

        The resolution term is a LINEAR ramp, not resolution_sensitivity /
        time_left. The reciprocal is arguably more correct - gap risk really
        does go to infinity at the instant of resolution - but it blows up and
        the clamp then picks an arbitrary number for you. A ramp is bounded and
        far easier to explain.
        '''
        half_spread = self.base_half_spread

        # cost floor: quoting inside your own fees is paying to trade, and the
        # resulting P&L looks like a strategy problem rather than arithmetic.
        if half_spread < self.fee_per_contract:
            half_spread = self.fee_per_contract

        half_spread += self.vol_sensitivity * self.vol_estimate

        if self._near_scheduled_news(time):
            half_spread += self.news_widening

        time_left = self.decision_time - time
        if time_left < 0.0:
            time_left = 0.0
        if self.decision_time > 0.0:
            fraction_elapsed = 1.0 - (time_left / self.decision_time)
            half_spread += self.resolution_sensitivity * fraction_elapsed

        return half_spread

    def _near_scheduled_news(self, time: float) -> bool:
        '''
        A LEAD time, not a window either side. You widen before a known event;
        afterwards the information is public and the danger has passed.
        '''
        if self.news_buffer <= 0.0:
            return False

        for news_time in self.scheduled_news_times:
            if time <= news_time and news_time - time <= self.news_buffer:
                return True
        return False

    # ------------------------------------------------------------------
    # layer 2 - inventory skew
    # ------------------------------------------------------------------

    def _reservation_price(self, reference: float, position: int,
                           time: float) -> float:
        '''
        Avellaneda-Stoikov: the price at which the maker is INDIFFERENT to its
        current inventory.

            r = reference - position * risk_aversion * vol^2 * (T - t)

        Long inventory pushes r DOWN, so BOTH quotes move down - the ask gets
        easier to hit, the bid harder. Shifting both is the mechanism; widening
        one side instead would change the spread and leave the inventory target
        untouched.

        FALLBACK VOL. vol_estimate starts at 0.0, which would make the skew
        vanish on the first few requotes - exactly when the position is being
        established. A floor of 1.0 tick keeps the skew alive from the start.
        That floor is a modelling choice, not a fudge: it says "assume at least
        one tick of volatility until measured otherwise".
        '''
        time_left = self.decision_time - time
        if time_left < 0.0:
            time_left = 0.0

        vol = self.vol_estimate
        if vol < 1.0:
            vol = 1.0

        return reference - position * self.risk_aversion * (vol ** 2) * time_left

    # ------------------------------------------------------------------
    # layer 5 - position limits
    # ------------------------------------------------------------------

    def _may_quote(self, side, position: int) -> bool:
        '''
        Hard cap behind the soft skew. Suppress only the side that GROWS the
        position; the unwinding side stays live or the maker is trapped at its
        cap until resolution.
        '''
        if self.max_position is None:
            return True

        if side is Side.BUY and position >= self.max_position:
            return False
        if side is Side.SELL and position <= -self.max_position:
            return False
        return True

    # ------------------------------------------------------------------
    # assembly
    # ------------------------------------------------------------------

    def quotes(self, book, portfolio, time: float):
        '''
        Order matters, because each step feeds the next: reference, then
        volatility (needs the reference), then the reservation price (needs
        volatility), then the half-spread, then limits, then the clamp LAST.
        Clamping mid-calculation would silently change a later input.
        '''
        reference = self._reference(book, time)
        if reference is None:
            return None

        self._update_volatility(reference, time)

        centre = self._reservation_price(reference, portfolio.position, time)
        half = self._half_spread(time)

        bid = clamp_tick(round(centre - half))
        ask = clamp_tick(round(centre + half))

        if bid >= ask:
            return None       # clamping at 1 or 99 can collapse the pair

        if not self._may_quote(Side.BUY, portfolio.position):
            bid = None
        if not self._may_quote(Side.SELL, portfolio.position):
            ask = None
        if bid is None and ask is None:
            return None

        return (bid, ask, self.size)
