# Design decisions

One living log for the whole project, appended to as decisions are made.

**Why one document and not one per chat.** A per-chat record captures *when* you
decided something, which nobody will ever ask. A decision log captures *what* you
decided and why, which is the entire content of a design interview. Per-chat files
also fragment — the same decision gets revisited in three conversations and you end
up with three partial accounts and no way to tell which is current. This file is the
single source of truth; when a decision changes, edit the entry and note the
reversal rather than appending a contradiction.

Format per entry: **decision → alternative considered → deciding constraint → cost
accepted → what would flip it.** That is the same five-beat shape as a good spoken
answer, so this file doubles as interview prep. Large chunks of it belong in the
README more or less verbatim.

---

## Order book

### Integer tick prices, not floats
- **Alternative:** floats; `Decimal`.
- **Constraint:** the book compares and matches on price constantly, and float
  equality breaks silently (`0.1 + 0.2 != 0.3`). Prediction markets quote in integer
  cents anyway.
- **Cost:** none material. `Decimal` would be exact but slower and pointless once
  prices are integers.
- **Flips if:** the venue ever quotes sub-cent.

### Integer ticks enforced with `isinstance`, not `% 1`
- **Constraint:** `61.0 % 1 == 0` passes a modulo check, and `hash(61.0) == hash(61)`
  so it even indexes the same dict slot — the float propagates invisibly until
  something downstream formats it.
- **Cost:** rejects `61.0` from callers who meant `61`. That is the point.

### Time priority via a sequence number, not a timestamp
- **Alternative:** sim-clock or wall-clock timestamps.
- **Constraint:** in a discrete-event sim many events share an exact virtual time, so
  timestamps collide and FIFO order becomes non-deterministic.
- **Note:** `seq` and `time` are both kept on `Trade` and are not redundant. `seq` is
  a Lamport clock for total order; `time` is the physical clock markout needs.

### `PriceLevel` as an intrusive doubly-linked list, not a deque
- **Alternative:** `collections.deque`.
- **Constraint:** a deque is O(1) at both ends but O(n) in the middle, and the middle
  is what a cancel is. In real flow cancels vastly outnumber fills, so the middle is
  the common case.
- **Cost:** `Order` now carries `prev`/`next` and knows it lives in a list, so it
  cannot use `slots=True`. It already carried `seq`, so it was never a pure data
  holder.

### Self-trade prevention defaults `trader_id=None`, not `0`
- **Constraint:** with a default of `0`, every order in every test shares an owner and
  STP cancels all matching. The suite passes while the book never trades.

### `taker_side` on `Trade` has no default
- **Constraint:** a forgotten argument must raise `TypeError`, not silently invert
  P&L downstream.

### `OrderBook.clock` — optional callable, set by the engine
- **Alternative:** the engine passes `time` into `portfolio.on_fill`.
- **Constraint:** markout needs a wall-clock stamp per fill and cannot reconstruct it
  afterwards. Stamping at birth means every consumer of `book.trades` gets it, not
  just the portfolio.
- **Cost:** the book gains one piece of state it does not own. Defaults to `None`, so
  every existing test is unaffected.
- **Flips if:** more than one component wants to drive the clock.

---

## Value process

### State is `x`, the log-odds; `p` is a computed view
- **Alternative:** store `p` and transform when needed.
- **Constraint:** two concrete failures. `logit(sigmoid(x))` is not exactly `x`, so
  storing `p` round-trips every step and accumulates error; and `sigmoid(x)` returns
  *exactly* `1.0` once `x` passes about 37 in float64, after which `logit` divides by
  zero. A 100k-step run at high vol reaches that.
- **Cost:** every reader goes through a property.

### Logit-space random walk, no clipping
- **Alternative:** an arithmetic walk on `p` clipped to `[0.01, 0.99]`.
- **Constraint:** clipping piles probability mass on the boundaries, so a market that
  wanders to 0.99 stays there instead of diffusing back. Resolved outcomes then come
  disproportionately from clipped paths and the Brier score measures the clipping
  constant.
- **Bonus:** log-odds is the natural unit of evidence, the same currency
  `fair_value.py` uses for its Bayesian update.

### Martingale drift correction, `x += (p - 0.5) * vol**2 * dt`
- **Alternative:** document the bias and move on.
- **Constraint:** `x` is a martingale but `p = sigmoid(x)` is not, because sigmoid is
  curved — at `p = 0.9` a `+1.0` shock gains 0.06 while a `−1.0` shock loses 0.13, so
  the average slides toward 0.5. Price direction then becomes predictable with zero
  information, which contaminates the markout decomposition (SDE drift is
  indistinguishable from informed trading) and biases ground truth toward 50/50.
- **Size:** at `vol = 1.0`, `p = 0.9`, the uncorrected drift is ~0.4 log-odds over the
  market's life, roughly 3.6 ticks. The half-spread is 1–2 ticks and markout is
  measured in fractions of one. The artefact was *larger than the signal*.
- **Cost:** one line, plus an Euler discretisation error that shrinks with call
  frequency.
- **Flips if:** `0.5 * vol**2 * T` drops an order of magnitude below the half-spread —
  at `vol = 0.3` the bias is ~0.3 ticks and documenting it would be defensible.

### `advance_to(t)`, not `step()`
- **Constraint:** the engine is event-driven with irregular gaps. A fixed step would
  make realised volatility depend on how busy the market is, so changing the arrival
  rate would also change the price path.

### News jumps: single additive shocks, not volatility regime changes
- **Alternative:** raise `vol` for a window around the news.
- **Constraint:** a regime change makes the price wander faster but never gap. A gap
  moves straight through quotes that were already resting, so requoting speed cannot
  save a maker from it. Gap risk is the risk a market maker actually fears, and it is
  what makes volatility-scaled spreads worth building.
- **Implementation:** `x += gauss(0, jump_vol)` at the instant; `vol` identical either
  side. `jump_vol` should be several times `vol` or the jump is not a gap.
- **Naming wart:** `jump_vol` reads like "volatility during the jump" but means "the
  standard deviation of the jump's size". `jump_scale` would be clearer.

### News timing is public, news content is private
- `scheduled_news_times` is readable by the market maker; `x` and the unscheduled
  events never are. Earnings dates get announced, earnings do not.
- **Why it matters:** a maker can pull quotes cheaply before a known event because it
  knows when to come back. Against surprises it can only widen permanently, paying
  spread all day for insurance it rarely needs. Quantifying that asymmetry is the
  distinctive result.
- **Enforcement:** the maker is passed the *tuple* `scheduled_news_times`, never the
  `ValueProcess` object — one autocomplete away from reading `.x`.

### `decision_time` separate from `resolve_time`
- **Constraint:** the answer becomes known before the market settles. That window is
  the resolution hazard — stale quotes in a book whose outcome is already determined.
  Collapse the two and resolution-aware widening measures exactly zero.

### `p` returns exactly `1.0` / `0.0` after decision
- **Alternative:** `0.99` / `0.01`, which stays on the tick grid.
- **Cost accepted:** `tick_price` then returns `0.0` or `100.0`, off the legal 1–99
  grid. Every trader deriving a submit price from it must clamp. Handled in
  `InformedTrader._clamp`.

### Outcome is `Bernoulli(p)`, never `round(p)`
- **Constraint:** if the outcome were a deterministic function of the final price, a
  model that merely parrots the market scores a perfect Brier and the validation layer
  rewards overconfidence. A proper scoring rule is only proper against a genuinely
  stochastic outcome.

### KNOWN ISSUE — RNG consumption depends on call cadence
- `gauss()` draws from the stream whether or not `sigma` is zero, so a walk advanced
  in 99 calls lands on a different realised path than the same walk advanced in one,
  despite an identical seed.
- **Why it matters:** the market maker schedules requote events. Change its parameters
  and `advance_to` is called at different times, so the value path diverges — and a
  "same world, one knob changed" claim is no longer true.
- **Fix when it bites:** pre-draw increments on a fixed fine grid in `__init__` and
  have `advance_to` sum the cells it crosses. The path becomes a pure function of the
  seed. Reintroduces a grid for *path realisation* only; event timing stays
  continuous.
- **Status:** deferred until the market maker shows whether its event cadence actually
  varies with its parameters.

---

## Traders

### Informed observation in probability space, noise added by the engine
- **Alternative considered and rejected:** logit space, `observed_x = x + gauss(0, τ)`.
- **Constraint chosen for:** `signal_noise` reads directly as "how many probability
  points wrong this trader typically is", which is interpretable when sweeping it.
  Logit space would have needed no clamping and given a cleaner `vol/τ` ratio.
- **Cost accepted:** the observation must be clamped to `[0.01, 0.99]`, and at an
  extreme `true_p` the noise becomes effectively one-sided, biasing the signal toward
  the middle. Documented in `SimEngine._observe`.
- **Flips if:** the sweep is run at extreme starting probabilities, where the clamping
  bias would distort the result.

### The noise is added in the engine, not the trader
- **Constraint:** `InformedTrader.generate_order` takes `observed_p`. No argument in
  that method *could* carry the truth, so the leak is structurally impossible rather
  than merely against the rules. `NoiseTrader.generate_order` takes no probability at
  all, asserted against the signature in `test_traders.py`.

### Informed trader sends a marketable IOC limit, not a market order
- **Alternative:** `MARKET` + IOC.
- **Constraint:** a market order walks the entire book on a thin day and hands the
  maker a windfall. A limit at the trader's own estimate crosses everything between
  the touch and its fair value and refuses to pay through it.
- **Non-negotiable part:** the TIF. A GTC informed trader becomes a liquidity
  *provider* and no adverse selection is transferred at all. This is the single most
  common reason the experiment shows nothing.

### Informed trader references `micro_price`, not `mid`
- Micro already accounts for queue imbalance, so a thin side does not fool it into
  seeing edge that is really a one-sided book.

### Noise trader mixes GTC and IOC (`take_probability`)
- **Constraint:** a pure-GTC noise trader builds a book but never trades against the
  maker, so the maker earns no spread and its P&L is pure inventory noise.

---

## Portfolio

### `our_side` is passed into `on_fill`, never read off the trade
- **Constraint:** a market maker is passive almost always, so `trade.taker_side` is
  the *other* side of the fill. Reading it inverts the position on every passive fill
  and mirror-images all P&L, with nothing raising.
- **Regression test:** `test_our_side_is_not_read_off_the_trade`.

### Three explicit branches in `on_fill`, not one formula
- Opening/adding (no P&L, weighted-average cost), reducing (realise, cost basis
  *unchanged*), flipping (realise on the closed portion, reset basis to the fill
  price). Any single formula is wrong on at least one of the three. The flip case is
  the one that fails first.

### Mark at the exit side, not the mid
- Long marks at the best bid, short at the best ask. The mid flatters P&L by assuming
  you can close where nobody is trading, which for a maker holding unwanted inventory
  is precisely what you cannot do.
- Returns `None` when the exit side is empty rather than falling back to the mid.

### Everything in ticks × contracts
- One unit system, converted to dollars only for display. Mixed units corrupt every
  downstream number while the magnitudes still look plausible.

---

## Engine

### Hand-rolled event heap, not SimPy
- A heap of `(time, tiebreak, kind, payload)` is essentially what SimPy does
  internally, and writing it demonstrates understanding of discrete-event simulation.

### The tiebreak counter is mandatory
- Tuples compare element by element, so two events at an identical float time fall
  through to comparing the payload — a trader or an `Order`, neither orderable. The
  result is a `TypeError` at a random point deep into a long run.

### Routing by `isinstance`, not a `needs_signal` flag
- **Cost accepted:** adding a third trader type that needs a signal means editing the
  engine. With only two types the flag is indirection without payoff.

### News is its own event type on the heap
- **Constraint:** if the jump were only applied when the next trader happened to
  arrive, nobody would pick off the maker's stale quotes and the feature would measure
  zero. `_handle_news` gives every informed trader one immediate look, with
  `reschedule=False` so their own Poisson streams are untouched.

### One shared `order_ids` counter for the entire sim
- Per-trader counters collide and `book.submit` raises on the duplicate, typically
  thousands of events in.

### Quote ids recorded *before* submission
- A quote can cross and fill on submission, and `_attribute` must recognise it as ours
  within that same call. `recent_ids` distinguishes "we crossed" (our side = taker
  side) from "we rested" (our side = taker side *opposite*).

### One quoting interface: `quotes(book, portfolio, time)`
- `FixedSpreadMaker` accepts `portfolio` and `time` and ignores both. Keeping one
  signature means the control and the real maker are swappable and every comparison
  is like for like — which is what makes a measured difference attributable to the
  strategy rather than to a changed code path.

### Either quote leg may be `None`
- A position limit suppresses the side that would grow the position and leaves the
  unwinding side live. Pulling both would trap the maker at its cap until resolution.
- The engine already handles this, so `market_maker.py` needs no engine change.

### Snapshots are plain dicts; the DataFrame is built once at the end
- Appending to a DataFrame inside the loop is quadratic and would dominate the
  runtime of every experiment.

### `FixedSpreadMaker` exists as a control, not as a strategy
- Every feature in `market_maker.py` is measured as a delta against it. A feature with
  no measured effect is a claim, not a result.

---

## Measured baseline (FixedSpreadMaker, 40 seeds, 1.0 time units)

| half_spread | signal_noise | realised P&L | peak abs position |
|---|---|---|---|
| 10 | 0.5 | +82 | 30.6 |
| 10 | 0.02 | −950 | 47.6 |
| 2 | 0.5 | −170 | 27.0 |
| 2 | 0.02 | −1008 | 51.6 |

Profitable against uninformed flow, destroyed by informed flow. Widening does not
rescue it, because the informed trader only crosses when its edge beats the spread —
so a wider quote yields fewer but more toxic fills. Peak inventory near 50 with no
limits is what skew and position caps exist to fix.

---

## Known limitations, deliberately accepted

- **Noise traders never cancel.** Their GTC orders accumulate for the life of the run,
  so the book grows deeper and staler than a real one. Adding a cancel stream is a
  half-hour job if the depth profile starts distorting results.
- **Observation clamping bias** at extreme `true_p` — see the traders section.
- **Euler discretisation** in the martingale drift: it uses `p` at the interval start,
  exact only in the limit. Small at Poisson arrival rates.
- **Jumps carry their own Jensen bias**, uncorrected. `E[sigmoid(x + gaussian)]` has
  no closed form, so the fix is expensive and the effect is confined to one to three
  instants per run.
- **Tick granularity at the extremes:** a `true_p` of 0.997 has no expressible price
  on a 1–99 grid, which will generate apparent coherence violations that are really
  rounding.

---

## Open, not yet decided

- Whether to build complementary YES/NO mechanics (mint/merge, collateral) or drop the
  coherence-arbitrage CV bullet.
- Mode B fill model: strict queue-position modelling versus "fills if a trade prints
  through the price".
- Whether the RNG-cadence issue above needs fixing before the experiments run.
