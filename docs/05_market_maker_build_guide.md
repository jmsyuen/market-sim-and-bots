# `market_maker.py` — build guide

Target file: `src/strategy/market_maker.py` (skeleton already in place)
Test file: `tests/test_market_maker.py`

Format per section: **Write** (what it must do and why) → **Hints** (what's easy to get
wrong) → **Measure** (the number this layer produces).

That third beat is the difference between this file and every other one in the project.
`book.py` is either correct or not. A market maker is never correct — it's better or worse
than the version without the feature, and the only way to know which is to run both. Every
layer below ends with an experiment, and those experiments *are* CV bullets 2 and 3.

**Already done for you:** the engine's quoting interface is `quotes(book, portfolio, time)`,
`FixedSpreadMaker` already matches it, and the engine already handles a `None` quote leg.
No engine changes are needed for anything in this guide.

---

## 0. Interfaces you will call

Everything below already exists and is tested. Nothing here needs changing.

### `OrderBook` — what the strategy reads

| | returns | note |
|---|---|---|
| `book.best_bid` / `book.best_ask` | `int \| None` | `None` when that side is empty |
| `book.mid` | `float \| None` | `(bid + ask) / 2` |
| `book.spread` | `int \| None` | |
| `book.micro_price` | `float \| None` | `bid + imbalance * (ask - bid)`; heavy bids sit near the ask |
| `book.size_at(side, price)` | `int` | `0` if the level is empty |
| `book.depth(levels=5)` | `{Side.BUY: [(price, size)], Side.SELL: [...]}` | best-first; coherence needs this |
| `book.trades` | `list[Trade]` | every fill the book has produced |

**Every one of the first four can be `None`.** A one-sided or empty book is normal early in
a run, and the maker is called before flow has built anything.

The strategy never calls `submit` or `cancel` — the engine does that. You return ticks; it
handles orders.

### `Order`, `Side`, `Trade` — for tests

`Order` is keyword-only: `Order(id=, side=, quantity=, price=None, type=OrderType.LIMIT,
tif=TimeInForce.GTC, trader_id=None)`. `price` must be an `int` in 1–99 for limits and
`None` for markets.

`Side.BUY` / `Side.SELL`, with `.opposite` and `.sign` (`+1` / `-1`). `.sign` is what makes
P&L arithmetic side-agnostic.

`Trade` is frozen: `price`, `quantity`, `maker_id`, `taker_id`, `seq`, `taker_side`, `time`.
`taker_side` is the side of the *aggressor*, which for a passive fill is the opposite of
yours.

### `Portfolio` — what the maker reads, and what metrics consumes

| | |
|---|---|
| `portfolio.position` | `int`, positive long YES |
| `portfolio.avg_cost` | `float`, volume-weighted, in ticks |
| `portfolio.realised_pnl` | `float`, ticks × contracts |
| `portfolio.cash` | `float` |
| `portfolio.fills` | `list[(Trade, our_side)]` — the input to markout |
| `portfolio.unrealised_pnl(book)` | `float \| None` — `None` if the exit side is empty |
| `portfolio.total_pnl(book)` | `float \| None` |

The maker only needs `position`. Everything else is for the analysis layer.

### `ValueProcess` — what the maker may and may not touch

**May read:** `scheduled_news_times` (a tuple of floats), `decision_time`, `resolve_time`.

**Must never read:** `x`, `p`, `tick_price`, `outcome`, `_news_events`.

The maker is constructed with the *tuple*, never the object. If a `ValueProcess` is in
scope inside `market_maker.py`, that is the bug.

### `SimEngine` — the contract your maker must satisfy

The engine requires exactly three attributes and one method:

```python
maker.trader_id      # int, distinct from every trader
maker.resting_ids    # set, the engine adds to and clears it
maker.recent_ids     # set, the engine adds to and clears it
maker.quotes(book, portfolio, time)   # -> (bid, ask, size) or None
```

`bid` or `ask` may individually be `None`. Both `None` — return `None` for the whole thing.

For experiments: `engine.run(until)`, `engine.log` (one dict per event),
`engine.to_frame()` (pandas). Each log row has `time`, `true_p`, `best_bid`, `best_ask`,
`mid`, `micro_price`, `position`, `cash`, `realised_pnl`, `unrealised_pnl`, `n_trades`.

### `FairValue` — the contract the maker expects

`fair_value.py` is yours to write, but the maker consumes it, so fix the interface now:

```python
fair_value.value(book)                # -> float in TICKS (1..99), or None
fair_value.probability(book)          # -> float in (0,1); value(book) / 100
fair_value.observe(trade, our_side)   # optional: fold a fill into the posterior
```

**Units are the trap.** `micro_price` is in ticks, so `value()` must be in ticks for the
two to be swappable inside `_reference`. Calibration wants probabilities, hence the second
method. Convert at the boundary; do not let both float around the file.

Bayesian shape, for CV bullet 3: hold `Beta(a, b)` with the mean set from the micro-price
prior and `a + b` as prior strength. A buy that looks informed adds to `a`, a sell to `b`,
weighted by how informative the flow looks. Posterior mean `a / (a + b)` is the fair value.
That is a precision-weighted blend, not a simple average — which is the thing the bullet is
claiming and the thing you will be asked to explain.

---

## 1. Fair value, and the abstraction boundary

### Write

`_reference(book)` returns the centre of the quotes. If a `fair_value` object was injected,
ask it; otherwise fall back to `book.micro_price`. `None` when there's nothing to quote
around.

The injection is what lets you build layers 2 to 6 and measure them *before*
`fair_value.py` exists. Passing `None` gives a maker centred on the micro-price, which is
exactly the control's behaviour — so the two are comparable from day one.

### Hints

- **The clean abstraction test:** `_reference` should be the only method in the file that
  mentions `book`. Grep for `best_bid` and `micro_price` across the class afterwards and
  expect no other hits. If quoting logic reaches into the book directly, swapping in a
  different venue (or a fair-value model) means editing five methods instead of one.
- Don't branch on venue type inside `_reference`. Degrade gracefully instead.
- `micro_price` is a float. Everything downstream stays float until the single `round()` in
  `quotes()`. Rounding early compounds.

---

## 2. The cost floor

### Write

Never quote a half-spread below `fee_per_contract`. One comparison at the top of
`_half_spread`.

### Hints

- Looks trivial and is worth writing anyway, because when it's missing the symptom is "my
  strategy loses money" and you go looking in the skew. It's arithmetic, not strategy.
- Economically the floor is fees *plus* expected adverse selection *plus* an inventory
  premium. You're only modelling the first explicitly; the other two are what layers 3 and
  4 approximate. Say that in the README — it shows you know the floor is a simplification.

### Measure

Nothing yet. This is a guard, not a feature.

---

## 3. Inventory skew — the first real layer

### Write

`_reservation_price(reference, position, time)`:

```
r = reference - position * risk_aversion * vol² * (T - t)
```

Then both quotes go at `r ± half_spread`. Long inventory pushes `r` down, so the ask gets
easier to hit and the bid harder. That asymmetry is the entire mechanism.

Build it in two steps. First with `(T - t)` hard-coded to `1.0` and `vol_estimate` fixed at
a constant — just `r = reference - position * risk_aversion`. Get that working and measured.
Then add the time and volatility terms. Two moving parts at once and you won't be able to
attribute an effect to either.

### Hints

- **The bug that eats a week:** widening one side instead of shifting both. Widening changes
  your spread, not your inventory target — you trade less on the side you wanted to trade
  less on, but you haven't made the other side more attractive, so the position drifts just
  as far and you earn less getting there. Tests 3 and 4 are the pair.
- Sign check by hand before running anything: `position = +10`, `risk_aversion = 0.1`,
  everything else 1. Is `r` below `reference`? If it's above, your skew is *accelerating*
  inventory and the run will look spectacular right up until it doesn't.
- `(T - t)` must be floored at zero. Past `decision_time` it goes negative and the skew
  inverts.
- `risk_aversion = 0` must reproduce the control exactly. Assert it.

### Measure — DEFERRED, not needed today

The bullet claims inventory skew *exists*, not that a frontier was measured, so the sweep
below is not required for the CV. Tests 3, 4 and 5 are what make the claim true. Do this
when there is a free evening.

**The risk/return frontier.** Sweep `risk_aversion` across roughly `[0, 0.01, 0.05, 0.1,
0.5, 1.0]`, 40+ seeds each, holding everything else fixed. Record RMS inventory and edge per
share (realised P&L divided by contracts traded).

Expect: RMS inventory falls steeply, edge per share is flat then falls, and there's a
visible optimum before it turns negative. Plot both against `risk_aversion` on one chart.

The baseline peak inventory is around 50 with no skew, so there's plenty of room for this to
show a large effect.

---

## 4. Volatility scaling

### Write

`_update_volatility(reference, time)` maintains an EWMA of `|Δreference| / √Δt`, and
`_half_spread` adds `vol_sensitivity * vol_estimate`.

Sampled inside `quotes()` because that's already called on every requote — a regular
sampling point that needs no new engine hook.

### Hints

- **The `√Δt` normalisation is the whole thing.** Without it, requoting twice as often
  halves your measured volatility and the spread silently narrows precisely when you're
  paying most attention. Same `dt` versus `√dt` distinction as in `value_process`.
- Guard the first call — `_last_reference` is `None` and one observation measures nothing.
  Guard `dt <= 0` too; the engine can requote twice at one timestamp.
- The EWMA decay for an irregular gap is `0.5 ** (dt / vol_half_life)`, with the new
  observation taking `1 - decay`. A fixed weight would make the estimate depend on call
  frequency again, undoing the normalisation you just did.
- `abs(move)` rather than `move²` keeps the estimate in tick units so `vol_sensitivity`
  reads as "extra ticks per unit of volatility". Squaring is more standard; the units get
  harder to reason about. Either is defensible — say which you chose.

### Measure

Run with jumps on (`jump_vol = 2.0`, a couple of `news_times`) and compare
`vol_sensitivity = 0` against a tuned value. Expect P&L improvement concentrated *around*
the news times. Slice the fill log by time-since-news and show markout on fills inside and
outside a news window. If the improvement is uniform across time, the estimator isn't
reacting and the half-life is too long.

---

## 5. Event awareness — DEFERRED IN FULL

**Skipped for now, code and experiment both.** No CV bullet claims news awareness, so
building the widening logic without running the experiment is pure cost. Leave
`_near_scheduled_news` unimplemented and `news_buffer` / `resolution_sensitivity` at their
defaults of zero, which makes both terms vanish from `_half_spread`.

This is the most distinctive thing in the project and the first thing to add back. Nobody
else's order book project has it, because it needs a latent value with jumps, a
public/private information split, and a maker that can act on one but not the other. The
full design is below, unchanged, for when you return to it.

### Write

Two separate terms in `_half_spread`.

**Scheduled news.** `_near_scheduled_news(time)` loops over `scheduled_news_times` and
returns `True` if one is within `news_buffer` ahead. Widen by a flat amount, or pull quotes
entirely.

**Resolution.** Widen as `time` approaches `decision_time`.

### Hints

- The maker holds the *tuple* of times, never the `ValueProcess`. One autocomplete from
  `.x` and every number in the project is void.
- `news_buffer` is a *lead* time, not a window around the event. Widen before, not after;
  after the jump the information is public and the danger has passed.
- `resolution_sensitivity / time_left` blows up as `time_left → 0`. Arguably correct — gap
  risk really does go to infinity — but cap it or the clamp does something arbitrary for
  you. A linear ramp is easier to explain.

### Measure — DEFERRED

**The asymmetry experiment.** Three configurations, same seeds, same total news intensity:

| | news | maker knows timing |
|---|---|---|
| A | scheduled only | yes |
| B | unscheduled only | no — cannot |
| C | unscheduled only | widened permanently instead |

The story: against scheduled news the maker defends cheaply, because it knows when to step
aside and when to come back. Against surprises it either eats the gaps (B) or pays spread
all day for insurance it rarely needs (C). Report the P&L cost of that asymmetry.

Nobody else's order book project has this, because it needs a latent value with jumps, a
public/private information split, and a maker that can act on one but not the other.

---

## 6. Position limits — DEFERRED

**Skipped for now.** No bullet claims a position cap, and with skew working the cap should
rarely bind anyway. Leave `_may_quote` unimplemented and never suppress a leg; the engine
supports `None` legs whenever you come back to this.

Design, for later:

### Write

`_may_quote(side, position)`. At or beyond `+max_position`, suppress the bid. At or beyond
`-max_position`, suppress the ask.

### Hints

- **Suppress one side, never both.** Returning `None` from `quotes()` at the cap pulls the
  unwinding side too, and the position then sits at the limit until resolution — the
  opposite of what a limit is for. Return `None` for the suppressed *leg*; the engine
  already handles it.
- Skew and the cap do different jobs. Skew makes a large position *expensive*; the cap makes
  it *impossible*. With skew tuned well you should rarely hit the cap — if you're hitting it
  constantly, `risk_aversion` is too low and the cap is papering over it.

### Measure

Distribution of position across a run, with and without. Expect the tails to disappear and
the body roughly unchanged. If the body moves, the cap is binding too often.

---

## 7. Tests — `tests/test_market_maker.py`

Eight for today; tests 9, 10 and 11 go with the deferred sections.

**Reproducing the control**
1. All features off gives the same quotes as `FixedSpreadMaker` at the same
   `base_half_spread`. **Load-bearing** — separates a strategy difference from a plumbing
   bug.
2. `quotes()` returns `None` on an empty book.

**Skew**
3. Long inventory moves **both** bid and ask down; short moves both up. **Load-bearing.**
4. The spread is *unchanged* by inventory at fixed volatility. Companion to test 3: one
   asserts the shift, the other asserts it wasn't a widen.
5. `risk_aversion = 0` centres quotes exactly on the reference regardless of position.
6. Skew shrinks as `time` approaches `decision_time`.

**Volatility**
7. A fast-moving reference raises `vol_estimate`; a static one decays it toward zero.
8. **Estimate is invariant to sampling frequency.** Feed the same price path at two requote
   rates and assert the estimates agree within tolerance. **Load-bearing** — this is the
   `√Δt` bug, and it's silent.

**DEFERRED with their sections**
9. ~~Half-spread inside `news_buffer` exceeds the half-spread outside it.~~
10. ~~At `+max_position` the bid is `None` and the ask is not.~~
11. ~~`inspect.getsource` contains no `best_bid` outside `_reference`.~~ Worth adding
    eventually; the abstraction boundary is a thing an interviewer may probe.

---

## 8. Order of work — TODAY

The scope below is what CV bullet 3 actually claims: the features exist and are correct.

1. `fair_value.py` first — Beta posterior, micro-price prior. 40 min.
2. `_reference`, `quotes()` assembly with everything off → tests 1, 2
3. Skew, constant `vol`, `(T−t)` hard-coded to 1.0 → tests 3, 4, 5
4. Volatility estimator → tests 7, 8
5. Add `vol²` and `(T−t)` into the skew → test 6

Then leave this file and move to `metrics.py`. Deferred: the `risk_aversion` sweep, news
and resolution widening, position limits, and the asymmetry experiment.

If something has to give inside this list, give up step 5 — the skew works without the
time-decay term, and nothing in the bullet mentions it.

---

## 9. What to watch for in the results

If turning a dial does nothing, check these three before suspecting the strategy:

1. Is the informed trader aggressing (`tif != GTC`) or resting? A resting informed trader
   transfers no adverse selection at all.
2. Is `true_p` actually moving? Log it and look.
3. Is `_attribute` using `taker_side.opposite` on the maker branch? If not, every position
   is mirror-imaged and P&L has the wrong sign.

It is almost always one of those three.

One more, specific to this file: if P&L improves when you *increase* `risk_aversion` without
limit, your skew sign is inverted and you're accelerating inventory into a position that
happens to be profitable on the seeds you tried. Check test 3.
