# Prediction Market Exchange Simulator & Market-Making Strategy

A limit order book, a simulated prediction market, a market-making strategy, and a
validation layer that scores forecasts against **resolved outcomes**.

Built in Python from scratch. 108 tests, plus a 2M-operation fuzz suite on the book.

```bash
python -m pytest -q        # the suite
python -m pytest -m slow   # fuzz and the statistical tests
python experiments.py      # reproduces every number below
```

---

## Why a prediction market

The choice is methodological, not cosmetic. An equity simulator cannot answer *"was the
price right?"* — there is no terminal truth to compare against, so a strategy can only be
evaluated on its own P&L. A binary prediction market resolves to 0 or 1, which means:

- forecasts can be scored with **proper scoring rules** (Brier, log loss) against ground truth
- adverse selection can be measured **all the way to settlement**, not just to the next mid
- complementary YES/NO tokens must price to exactly 100 ticks, which makes **coherence
  arbitrage** a well-defined, checkable property

Everything below depends on that.

---

## The four layers

```
[order book + matching]  →  [simulated flow]  →  [MM strategy]  →  [validation]
  price-time priority        noise + informed     fair value        Brier / log loss
  O(1) cancel                over a resolving     inventory skew    vs resolved truth
  never-crossed invariant    latent probability   vol-scaled        coherence arbitrage
```

| Layer | Files |
|---|---|
| Book | `src/orderbook/` — `order`, `trade`, `price_level`, `book` |
| Market model | `src/market/` — `value_process`, `contract` |
| Flow | `src/orderflow/traders.py` |
| Strategy | `src/strategy/` — `fair_value`, `market_maker` |
| Accounting | `src/portfolio.py` |
| Engine | `src/sim/engine.py` |
| Validation | `src/analysis/` — `metrics`, `calibration`, `coherence` |

Design decisions, with the alternatives and what would reverse each one, are in
[`docs/design_decisions.md`](docs/design_decisions.md).

---

## Results

60 seeds per configuration unless stated. P&L in ticks × contracts.

### 1. Adverse selection rises as the informed signal sharpens

`signal_noise` is the standard deviation of the informed trader's observation error, in
probability units. 0.5 is barely better than guessing; 0.02 is near-perfect information.
Everything else is held fixed, including the value path.

| signal_noise | P&L | contracts | spread capture | markout @0.005 | markout @0.05 | **markout @settlement** |
|---|---|---|---|---|---|---|
| 0.50 | −4 | 96.1 | 269 | 2.64 | 3.06 | **−0.07** |
| 0.20 | −374 | 93.1 | 255 | 2.54 | 2.92 | **−4.57** |
| 0.10 | −680 | 95.4 | 253 | 2.37 | 2.81 | **−8.12** |
| 0.05 | −863 | 94.0 | 240 | 2.24 | 2.75 | **−9.54** |
| 0.02 | −701 | 88.9 | 223 | 2.23 | 2.70 | **−8.72** |

**The maker keeps trading just as much and keeps earning the spread — and still loses.**
Contracts traded fall 7%, spread capture falls 17%, but P&L goes from roughly flat to
−863. The loss is not less trading; it is *worse* trading.

### 2. The damage is invisible at short horizons

The most useful thing the analysis layer surfaced. Markout against the micro-price at one
event (0.005) and ten events (0.05) barely moves across the whole sweep — and is *positive*,
because a passive fill starts a half-spread ahead. Markout to **settlement** collapses from
−0.07 to −9.54 ticks per contract.

The reason is structural: an aggressive sweep displaces the touch, and noise traders refill
the level, so short-horizon impact **mean-reverts**. The information the informed trader
acted on is only fully revealed when the market resolves. A conventional markout curve
would have reported almost nothing here.

This is only measurable because the market resolves. It is the clearest single argument for
the prediction-market choice.

### 3. Each strategy layer, measured against the control

At `signal_noise = 0.05`, same seeds throughout.

| configuration | P&L | RMS inventory | contracts | spread capture | adverse selection |
|---|---|---|---|---|---|
| control (fixed spread) | −863 | 29.4 | 94.0 | 240 | +13.5 |
| + inventory skew | **−117** | **8.4** | 124.4 | 160 | +19.8 |
| + volatility-scaled spread | −220 | 7.5 | 35.3 | 216 | −11.0 |
| + Bayesian fair value | **−118** | **6.3** | 34.0 | 230 | −20.6 |

**Inventory skew is the single largest effect in the project:** RMS inventory falls 71%
(29.4 → 8.4) and P&L improves by 746 ticks. It also *increases* trading — 94 → 124
contracts — because shifting the quote pair makes the unwinding side more attractive
rather than simply quoting less.

Volatility scaling cuts traded volume by 72% (124 → 35). It is a genuine trade-off: it
avoids toxic fills but forgoes benign ones, and on its own it costs P&L. Adding Bayesian
fair value on top recovers that loss and reaches the lowest inventory of any configuration,
at a third of the control's trading volume.

### 4. Calibration against resolved outcomes

400 markets with `p0` varied across seeds; 242 produced a usable pre-resolution quote.

| forecaster | Brier | log loss |
|---|---|---|
| base rate (benchmark) | 0.2494 | — |
| market (micro-price) | 0.2168 | 0.6210 |
| **Bayesian fair value** | **0.2129** | **0.6139** |

The market beats the base rate, which is the sanity check — prices in this simulation carry
real information. The fair-value model beats the market on **both** scores, by 1.8% on
Brier and 1.1% on log loss. Winning on log loss as well as Brier matters: a model can beat
Brier while making a few catastrophic calls, and log loss is what catches that.

The edge is small, and it should be. The model's only private input is order flow the market
can also see.

### 5. Coherence arbitrage, at executable prices

200 independent YES/NO markets. "Headline" counts violations on touch prices; "executable"
walks real depth; "net" subtracts fees.

| fee per leg | snapshots | headline | executable | net | **survival** |
|---|---|---|---|---|---|
| 0 ticks | 200 | 21 | 21 | 21 | 100% |
| 0.5 ticks | 200 | 21 | 21 | 20 | 95.2% |
| 1 tick | 200 | 21 | 21 | 15 | **71.4%** |

Violations appear in 10.5% of markets. All of them survive walking real depth — the books
here are thin enough that the touch is representative. Costs are what bite: **at one tick
per leg, 29% of apparent arbitrage is worthless**, because a two-leg set pays the fee twice.

Not modelled, and stated rather than hidden: **leg risk**. The arithmetic assumes both legs
fill simultaneously. In reality you lift one and the other moves — which is a large part of
why such violations persist in real venues.

---

## Selected design decisions

Fuller treatment, with alternatives and reversal conditions, in `docs/design_decisions.md`.

**Latent value stored as log-odds, not probability.** A random walk needs an unbounded
state. Clipping a probability at [0.01, 0.99] piles mass on the boundaries, so a market that
wanders to 0.99 stays there and resolved outcomes come disproportionately from clipped
paths. Log-odds needs no clipping. It also avoids a concrete float64 failure: `sigmoid(x)`
returns exactly 1.0 past x ≈ 37, after which `logit` divides by zero.

**A martingale correction, because `sigmoid` is curved.** A driftless walk in log-odds is
*not* a martingale in probability space — at p = 0.9 a +1 shock gains 0.06 while a −1 shock
loses 0.13, so the average slides toward 0.5. Price direction then becomes predictable with
zero information, which contaminates exactly the markout measurement above. The correction
is one line, `x += (p − 0.5)·σ²·dt`, and at σ = 1 the uncorrected bias was ~3.6 ticks —
larger than the half-spread it would have been measured against.

**`decision_time` separate from `resolve_time`.** The answer becomes known before the market
settles, and that window is where stale quotes get picked off. Collapse the two and
resolution-aware quoting measures exactly zero.

**Outcome drawn as Bernoulli(p), never round(p).** If the outcome were a deterministic
function of the final price, a model that merely parrots the market would score a perfect
Brier. A proper scoring rule is only proper against a genuinely stochastic outcome.

**News timing is public; news content is not.** The maker can read `scheduled_news_times`
but never the latent value. Earnings dates get announced; earnings do not.

**Spread capture measured against the *pre-trade* reference.** The engine snapshots after
each event, so the row stamped at a fill already contains that fill's impact. Measuring
against it would credit the maker with the price move caused by the trade that hurt it.

**Inventory P&L computed as the residual.** The four components of the decomposition sum to
total P&L by construction, so the decomposition can never quietly disagree with the number
it explains.

---

## Known limitations

Stated deliberately rather than omitted.

- **RNG consumption depends on call cadence.** `gauss()` draws from the stream regardless of
  σ, so a value path advanced in 99 calls differs from the same path advanced in one. If a
  strategy change alters requote timing, the value path shifts too. The fix — pre-drawing
  increments on a fixed grid — is specified in the decision log but not implemented.
- **Observation noise is clamped** to [0.01, 0.99]. At extreme probabilities the noise
  becomes one-sided, biasing the informed signal toward the middle.
- **Jumps carry an uncorrected Jensen bias.** `E[sigmoid(x + gaussian)]` has no closed form;
  the effect is confined to one to three instants per run.
- **Noise traders never cancel,** so the book is deeper and staler than a real one.
- **Leg risk is not modelled** in the coherence analysis.
- **Euler discretisation** in the martingale drift, using p at the interval start.

## Not built

Scoped out deliberately, not abandoned mid-way:

- The **scheduled vs unscheduled news asymmetry experiment** — the code paths exist and are
  tested; the experiment is not run. This is the most distinctive idea here and the first
  thing to add.
- Mint/merge mechanics for physically executing coherence arbitrage (detection is unaffected)
- Mode B: replay against real Polymarket/Kalshi data with a fill model
- A C++ port of the book core, differential-tested against this reference
