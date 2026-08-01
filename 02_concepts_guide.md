# Concepts guide — everything you need to know to build this

Read this before and during the build (it's Phase 0). Roughly ordered from market
foundations to the specifics, the measurement toolkit, the data structures, the simulation
ideas, and the Python building blocks. If you can explain adverse selection, the micro-price,
why a binary contract is a digital option, and Bayesian updating in your own words, you're
ready.

---

## 1. Market microstructure basics

**Limit order book (LOB).** The central object. It holds resting buy orders (bids) and sell
orders (asks), organised by price. The best bid is the highest price a buyer will pay; the
best ask is the lowest price a seller will accept. The gap between them is the spread.

**Price-time priority.** The rule for who trades first. Best price wins; among orders at the
same price, the earliest to arrive fills first (FIFO). This is why you need both a price
ordering *and* a time tiebreak.

**Order types.**
- *Limit order:* "buy/sell up to N at price P or better." A buy fills at P or lower, a sell
  at P or higher. You control the price, not whether you get filled — unfilled remainder
  rests and waits.
- *Market order:* "buy/sell N right now at whatever's available." No price limit, fills
  immediately, walks through levels until done, never rests. You control timing, not price
  (sweeping levels causes slippage).
- One line: limit = price certainty, no fill certainty; market = fill certainty, no price
  certainty. Limit orders *add* liquidity; market orders *consume* it.

**Resting orders.** A limit order sitting in the book, waiting — "passive," "booked,"
"resting" all mean the same. It provides liquidity until matched or cancelled.

**Makers and takers.** A maker posts resting orders (provides liquidity, shows on the book).
A taker crosses the spread to hit resting orders (removes liquidity). A market maker is a
maker by design.

**Mid-price and spread.** Mid = (best bid + best ask) / 2, a rough "fair" reference. Spread
= best ask − best bid. The spread exists because liquidity providers must be compensated for
a service and protected against risk (see §2–3).

---

## 2. Market making and the two "edges"

A market maker quotes both sides — a bid below fair value, an ask above — and profits from
the difference on round-trips. The core loop: estimate fair value, quote around it, manage
inventory, requote as things move.

Crucially, "edge" means two different things, and you can have one without the other:

1. **Informational edge** — knowing the true value (here, the true probability) better than
   the market. This is alpha. Not every market maker has it.
2. **Liquidity-provision compensation** — the spread is a *fee paid for a service*:
   providing immediacy to people who want to trade now, and bearing the inventory and
   adverse-selection risk of holding the other side. This is not alpha; it's a structural
   payment.

You can profit with only the second — quote around a book-derived fair value, buy at bid,
sell at ask, and collect the spread from uninformed traders. But it is **not free money**
(see §3): your real P&L is `spread captured from uninformed flow − adverse-selection losses
to informed flow − fees`. You net a profit only if the first term wins, which needs enough
uninformed flow and a spread wide enough to cover expected adverse selection.

---

## 3. The risks: adverse selection and inventory

**Adverse selection** — the single most important idea. When you post a two-sided quote,
you don't choose who trades with you. If a trader knows something you don't, they take the
side that's about to be right: you buy, then the price falls; you got "picked off." Informed
flow systematically costs you, and the threat of it is *why makers widen spreads*. Your whole
simulation exists to reproduce and measure this — which is why you need informed traders and
a latent value for them to be informed about.

**Inventory and inventory risk.** Every fill moves your position. Holding a large long or
short exposes you to the price moving against that position before you can unwind it. So
makers *skew* their quotes against inventory (long → shade quotes down to encourage selling)
and cap position size. Inventory management is a core skill a trading desk checks for.

**What the spread must cover.** A survivable quoted spread ≥ fees + expected adverse
selection + an inventory-risk premium. Quote tighter than that and you lose by construction.

---

## 4. Prediction markets specifically

**Binary contracts = cash-or-nothing digital options.** A YES contract pays \$1 if the event
happens, \$0 otherwise. That is exactly a cash-or-nothing digital option, and its fair price
equals the **risk-neutral probability** of the event. For these small, short-dated bets, risk
premia and discounting are negligible, so the price ≈ the market's implied probability.

**Implied probability.** The price *is* the probability. YES at \$0.63 means the market says
63%. Because there's a spread, the implied probability is really a band (bid-implied vs
ask-implied); use the mid/micro for a point estimate, executable prices for trading. This is
why fair value in your bot literally *is* a probability in [0,1].

**Complementary tokens.** YES + NO must equal \$1, because exactly one pays \$1. A resting NO
order at price *p* is economically a YES order at *1 − p*. This linkage is the source of
coherence constraints and arbitrage.

**Coherence and arbitrage.** Logically related contracts must obey constraints:
- Complementary: YES + NO = \$1.
- A complete set of mutually exclusive, exhaustive outcomes must sum to \$1.
- Implication: if A implies B, price(A) ≤ price(B).
A *violation* is when executable prices break the rule — e.g. buy the whole set for \$0.97,
be guaranteed \$1, lock in \$0.03. You detect and trade these (you're not the exchange;
trading them is what pushes prices back to coherence). But **use executable prices, net of
fees and gas, sized by depth** — most headline violations vanish once frictions are counted,
and the skill is telling real arbs from illusory ones. Always verify the outcome set is
genuinely exhaustive and mutually exclusive first.

**Resolution and resolution jump risk.** At the terminal date the market resolves and the
price snaps discontinuously to 0 or 1. Near resolution (or when news breaks) whoever knows
the outcome first picks off stale quotes — a sharp, prediction-market-specific form of
adverse selection. The defence is to widen spreads or pull quotes near resolution/news. This
is the analogue of volatility-widening in equities.

**Why it's the same engine (CLOB).** A limit order book is a *data structure*; a
central-limit-order-book market is a *design choice*. Alternatives exist (dealer/OTC, RFQ,
dark pools, AMMs), which is what makes running a CLOB a deliberate decision worth
articulating. Polymarket and Kalshi both run CLOBs, so the matching engine you build is
venue-agnostic — the prediction-market part is a specialisation of the pricing/analysis
layers, not a different engine.

**Ground truth — the payoff.** Unlike equities, prediction markets *resolve*, so you observe
the true outcome. That lets you ask the one question equity markets never allow — *were the
prices right?* — and answer it with calibration scoring (§6). This is the project's
differentiator.

---

## 5. The fair-value toolkit

**Book imbalance.** Which side has more resting size, i.e. short-term directional pressure.
At the top of book, `I = Q_bid / (Q_bid + Q_ask)` in [0,1]; `I > 0.5` means more bids queued,
which tends to predict an upward move (that demand will consume the ask).

**Micro-price.** The imbalance-weighted mid — a better fair-value estimate than the raw mid
because it uses the information in relative sizes:

`micro = I·P_ask + (1 − I)·P_bid = P_bid + I·spread`

Heavy bid (`I` near 1) pulls fair value toward the ask; heavy ask toward the bid; balanced
sits at the mid. (The full Avellaneda–Stoikov micro-price also models how imbalance predicts
the *future* mid; the size-weighted form here is the practical baseline.) In your bot the
micro-price is the *baseline* fair value — book-derived, no edge — that lets it quote sensibly
before you add any independent view.

**Bayesian updating.** How you move fair value off the baseline toward a real view as
evidence arrives. Bayes: posterior ∝ prior × likelihood. You hold a prior belief, observe
evidence (news, informed-looking flow), and the likelihood scores how probable that evidence
is under each hypothesis; multiply and renormalise to get the posterior. The posterior *mean*
is your fair value.

Two things to get right (both were easy to misread):
- It is **not a simple average** of the prior and the evidence. It's a *precision-weighted*
  blend — weighted by how confident/informative each is (precision = inverse variance).
  Conjugate-normal case:
  `posterior_mean = (μ_prior/σ²_prior + μ_evi/σ²_evi) / (1/σ²_prior + 1/σ²_evi)`.
  A very confident prior barely moves on weak evidence; strong evidence dominates a vague one.
- Order flow isn't a number you average in — it's *evidence* that updates the belief via the
  likelihood, and its influence scales with how *informative* you judge it to be (noisy flow
  → weak update; informed-looking flow → strong update).

For yes/no events the natural conjugate prior is a **Beta distribution**: start Beta(a, b)
with mean a/(a+b); informed-looking buys nudge `a` up, sells nudge `b` up (by a weight
reflecting how informative the flow looks); the posterior mean a/(a+b) is the fair value.

---

## 6. Measuring performance

**Fill rate.** How much of your posted quoting actually trades (fills per quote, or filled
volume / quoted volume, over a window). High = trading a lot (more spread capture but more
inventory and adverse-selection exposure); low = quotes too far out or too passive. It's the
control you hold fixed when comparing strategy configs, so "traded less" isn't mistaken for
"managed risk better."

**Markout.** The standard way to measure adverse selection on a single fill. After a fill at
price P, look at the fair price (mid) a horizon Δ later — 1s, 10s, 1min — and compute the
signed move: bought at P and mid rose → markout +x (good); bought at P and mid fell → markout
−x (picked off). Persistent negative short-horizon markout means you're being adversely
selected. Plotting markout across horizons is the *markout curve*, and it shows how informed
the flow hitting you is.

**P&L decomposition.** Splitting total P&L into sources so you know where money comes and
goes: `+ spread captured (the half-spread earned per fill) − adverse-selection losses (the
negative markout) ± inventory P&L (mark-to-market as the mid drifts) − fees`. Markout is the
component that *quantifies* the adverse-selection term; decomposition tells you what to fix
and lets you measure claims like "vol-widening cut adverse-selection losses by Y%."

**Calibration.** A forecaster (or market) is *calibrated* if, among all the times it says
"p", the event happens a fraction ≈ p of the time. Test by binning predictions and plotting
predicted vs realised (a reliability curve): on the diagonal = calibrated; flatter than the
diagonal = overconfident (says 90% when it happens ~78%); steeper = underconfident.
Calibration ≠ usefulness — always predicting the base rate is perfectly calibrated and
useless; you want calibration *plus sharpness* (confident and still calibrated).

**Brier score.** A proper scoring rule = mean squared error of probability vs outcome:
`mean((p − o)²)`, range 0 (perfect) to 1. Simple and bounded; more forgiving of confident
errors.

**Log loss (cross-entropy).** `−mean(o·ln p + (1−o)·ln(1−p))`, range 0 to ∞. Punishes
confident wrongness far more brutally (a confident wrong forecast blows up; exactly 0 or 1
that's wrong is infinite). Report it alongside Brier — they weight the tails differently.
Neither is a hypothesis test; they're *scoring rules*. The metric is just a ruler — the
signal is the *application*: score the market's implied probabilities against realised
outcomes, score your fair-value model the same way, and a lower Brier/log loss than the
market is **measured edge**.

**Sharpe ratio.** Mean return over its standard deviation — a risk-adjusted performance
measure. Use it as a *relative* comparison across strategy configs, never as an absolute
claim about synthetic P&L (an interviewer will note your Sharpe is a function of how you
tuned your noise traders).

---

## 7. Data structures and CS concepts

**Integer tick pricing (why not floats).** The book compares/matches on price constantly,
and floats break exact equality and ordering (`0.1 + 0.2 != 0.3`), silently corrupting
matching. Store price as an integer number of ticks (cents, 1–99 for a prediction market);
convert to a decimal only for display. Exact, fast, matches real exchanges.

**Sequence numbers (why not timestamps).** Time priority needs an unambiguous tiebreak among
orders at the same price. In a simulation, multiple events can share the exact same virtual
time, so timestamps collide. A global incrementing integer gives a strict, reproducible order
— rank by `(price, seq)`.

**Mapping / hashmap / dict.** A structure that associates keys with values and looks up the
value for a key in ~O(1). In Python `dict` *is* the hashmap — hashing happens automatically
inside it; you never write a hash function, you just `d[key] = value` and `d[key]`. In the
book, `locations = {order_id → (side, price)}` finds an order's level instantly instead of
scanning. Keys must be hashable (≈ immutable): ints, strings, tuples, enum members, frozen
dataclasses are fine; lists and dicts are not.

**SortedDict (why for price levels).** Keeps keys in sorted order, so best-price access is
cheap (O(1) at the ends via `peekitem`) and inserts are O(log n) — and, unlike a heap, you
can still cancel an arbitrary order. Since most orders are cancelled not filled, cancel
performance matters, which is why SortedDict beats a heap here.

**deque (why both ends).** A double-ended queue with O(1) add/remove at *both* ends. A price
level is FIFO: append the newest order to the back, `popleft` the oldest to fill first — both
O(1). A plain list is O(1) at the back but O(n) at the front (everything shifts), so fills
would be slow. The deque's one weakness is O(n) removal of a *middle* element — which is what
a cancel does.

**Doubly-linked list for O(1) cancel.** The upgrade that fixes the deque's slow cancel. Store
each level's orders as nodes, each with `prev` and `next` pointers, and point the map straight
at the node: `{order_id → node}`. Cancel then = look up the node (O(1)) + splice it out by
rewiring its neighbours (`node.prev.next = node.next`, `node.next.prev = node.prev`, O(1)). It
must be *doubly* linked because removing a node requires fixing the previous node's forward
pointer, and a singly-linked list would have to scan from the head to find it (back to O(n)).
Time priority is preserved (append at tail, match from head). This is the "intrusive linked
list + hashmap" pattern real engines use and the natural target for the C++ port.

**Big-O intuition.** O(1) = constant (a dict lookup); O(log n) = grows slowly (SortedDict
access); O(n) = grows linearly with size (scanning a deque). The design goal is to keep the
hot operations (best-price access, insert, cancel, match-step) at O(1) or O(log n).

---

## 8. Simulation concepts

**Discrete-event simulation.** Instead of stepping a fixed clock, you keep a queue of
`(time, event)` and always process the earliest next event, jumping the clock to it. A heap
of `(time, seq, event)` popped in order is exactly this — and essentially what SimPy does
internally. The `seq` tiebreak keeps equal-time events deterministic.

**Poisson arrivals.** The standard model for orders arriving at random over time: the gap to
the next arrival is drawn from an exponential distribution (`rng.exponential(1/rate)`).
Undergraduate-level and realistic enough.

**Random walk / latent value.** The "true" value evolves as a stochastic process the informed
traders react to. For a prediction market, keep it in (0,1) by walking in logit space:
`x = logit(p); x += gauss(0, vol); p = sigmoid(x)`. At the terminal date it *resolves* to 0
or 1 (draw ~ Bernoulli(p)), giving ground truth.

**Informed vs noise traders.** Noise traders trade randomly (they're the uninformed flow you
earn spread from). Informed traders trade toward the latent value (they're the adverse
selection you lose to). The informed signal must be *noisy/lagged* — perfect information makes
them always win and the maker's problem degenerate. That noise level is the "insider dial" you
sweep in experiments.

**Mode A (synthetic) vs Mode B (real replay).** Two evaluation modes, both kept:
- *Mode A:* you generate all the flow, so you can re-run the identical world with one knob
  changed (informed fraction, your spread) — a controlled counterfactual, the only way to
  make causal claims. The resolving latent value gives ground truth.
- *Mode B:* real historical messages reconstruct the actual book; synthetic agents off. It
  grounds the project in reality but can't be re-run counterfactually.

**The fill model (why Mode B is subtle).** In Mode B your bot's quotes were never in the
historical book, so its fills *cannot* come from the matching engine — there's nothing there
to match against. You need a rule for when a quote *would have* filled: a passive bid fills
when a real trade prints at or below its price *and* the size that was queued ahead of you at
that price has cleared (price-time priority puts you at the back). Getting this right shows
you understand why backtesting a passive strategy is genuinely hard; assuming quotes fill "for
free" is the common error.

**Seeding / reproducibility.** Seed every RNG so a run reproduces exactly. This is what makes
controlled experiments valid (same world, one knob changed) and underpins the differential
test against the C++ port (identical order streams → identical output).

---

## 9. Python building blocks

**Enums (why not bools).** An enum is a small class with a fixed set of named members
(`Side.BUY`, `Side.SELL`). A bool has two unnamed states and can't grow — the moment you add
a third order type a bool is stuck. Enums read clearly at call sites, close the set of valid
values (a typo like `Side.BYU` fails instantly; the string `"byu"` wouldn't), and extend
cleanly. A bool would technically work for `Side`; enums are right for `OrderType` and keep
things consistent.

**Dataclasses (what they are, why not SQL).** A dataclass is an ordinary class where the
`@dataclass` decorator auto-writes the boilerplate (`__init__`, `__repr__`, `__eq__`) from the
fields you declare — the annotation `name: type` is what *makes* something a field. An instance
is an in-memory object (RAM, gone when the program exits), which is exactly right for a hot
structure mutated millions of times per run. A database is persistent disk storage for data
that must outlive the process or be queried/shared — a round-trip is milliseconds, so routing
matching through SQL would be thousands of times slower for no benefit. Rule: in-memory
objects for the live book; write only the *event log* to disk (CSV/Parquet) for analysis.
Gotchas: fields with defaults come last; never use a bare mutable default (`orders: list = []`
is shared across instances — use `field(default_factory=list)`); compute derived fields in
`__post_init__`.

**Decorators (the `@` syntax).** `@name` above a definition is shorthand for passing that
definition through a function: `@dataclass class Order: ...` is exactly `Order =
dataclass(Order)`. No magic — `dataclass` is a function that returns an upgraded class. You
use `@` when applying a named decorator a library provides (`@dataclass`, `@property`,
`@staticmethod`); it sits immediately above the `def`/`class`. Some take options in
parentheses (`@dataclass(frozen=True)`). You never need to *write* your own decorators for
this project.

**frozen dataclasses / hashability.** `@dataclass(frozen=True)` makes instances immutable and
hashable (usable as dict keys / set members). Use it for `Trade` — a completed fact that
should never change, and being hashable is convenient when you serialise trades. `Order` stays
mutable because its `remaining` quantity changes as it fills. This is the same immutability
principle as hashmap keys: only immutable things are hashable.

---

## Where each concept lands in the build

- Microstructure + order types + priority → `order.py`, `book.py`
- Data structures (ticks, seq, dict, SortedDict, deque, linked list) → `book.py`
- Prediction-market instrument (complementary, resolution) → `contract.py`
- Latent value + informed/noise + Poisson → `value_process.py`, `traders.py`, `engine.py`
- Two edges + inventory + adverse selection → `market_maker.py`, `portfolio.py`
- Micro-price + Bayesian updating → `fair_value.py`
- Markout + decomposition + fill rate → `analysis/metrics.py`
- Calibration + Brier + log loss → `analysis/calibration.py`
- Coherence + arbitrage → `analysis/coherence.py`
- Mode A/B + fill model + seeding → `engine.py`
- Enums, dataclasses, decorators → throughout `src/`
