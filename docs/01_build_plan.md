# Prediction-market market-making simulator — build plan & framework

One project, four layers: a matching engine, simulated flow, a market-making bot with a
fair-value model, and ground-truth validation via calibration and coherence analysis.
Built in Python; an optional C++ port of the book core comes later. The engine is
venue-agnostic (a CLOB is a CLOB); the prediction-market specialisation lives in the
pricing and analysis layers, and it's what unlocks the ground-truth validation that makes
the project distinctive.

Pseudocode below is signatures + logic-in-comments, not finished code — the instructive
parts (the matching walk, the fair-value update, the coherence check, the markout
decomposition) are left for you to implement. Data-holder files are given near-complete.

---

## 1. The arc

```
[order book + matching]  →  [simulated flow]  →  [MM bot + fair value]  →  [validation]
   venue-agnostic core       noise + informed      micro → Bayesian         Brier / log loss
   correct, tested           over a resolving      quoting, skew,           vs ground truth,
                             latent probability    resolution-aware         coherence arbitrage
```

Correctness and analysis are the payload; speed is not the point (that's the optional C++
hedge). One CV entry spanning all four layers — the *span* is the signal.

---

## 2. File & component structure

```
predmarket-mm/
├── README.md                     # the writeup — design decisions + results, front and centre
├── requirements.txt              # sortedcontainers, numpy, pandas, matplotlib, pytest
├── src/
│   ├── orderbook/
│   │   ├── order.py              # Order, Side / OrderType enums
│   │   ├── trade.py              # Trade record (frozen)
│   │   └── book.py               # OrderBook: add, cancel, MATCH; best bid/ask/mid/micro
│   ├── market/
│   │   └── contract.py           # binary contract: complementary YES/NO, [0,1] bounds, resolution
│   ├── flow/
│   │   ├── value_process.py      # latent "true" probability + terminal resolution
│   │   └── traders.py            # NoiseTrader, InformedTrader
│   ├── strategy/
│   │   ├── fair_value.py         # micro-price → independent estimate → Bayesian update
│   │   └── market_maker.py       # quoting, inventory skew, resolution-aware widening, limits
│   ├── portfolio.py              # inventory, cash, P&L, resolution settlement
│   ├── sim/
│   │   └── engine.py             # event loop; Mode A (synthetic) & Mode B (replay + fill model)
│   └── analysis/
│       ├── metrics.py            # markout, P&L decomposition, fill rate, inventory stats
│       ├── calibration.py        # Brier, log loss, reliability curve
│       └── coherence.py          # complementary-set arbitrage detection (executable prices)
├── tests/
│   ├── test_book.py              # the load-bearing suite: no crossed book, conservation, priority, fuzz
│   ├── test_fair_value.py        # Bayesian update behaves; micro-price bounds
│   └── test_coherence.py         # detects a planted arb; ignores a fee-killed one
└── notebooks/
    └── experiments.ipynb         # feature-effect experiments, calibration, charts
```

Note: `matching` is *not* a separate file — the matching logic lives inside `book.py` as
what happens when an incoming order crosses. `collateral`/position accounting folds into
`portfolio.py` at first; split it out only if it grows.

---

## 3. What to start on, and the build order

**Start with `order.py`, then `book.py`.** Everything else consumes the book: flow
generates orders that go into it, the bot quotes into it, the analysis reads its state.
It's also the only component with a self-contained correctness test — you can prove it
right with hand-written orders before any randomness, strategy, or prediction-market
machinery exists. And it's your first true CV bullet. Nothing precedes it in code; only
the reading in File 2 precedes it at all.

Build bottom-up; each layer depends only on the tested layer beneath it:

1. `order.py`, `trade.py` — data holders.
2. `book.py` — rest-only `add` → accessors → `cancel` → matching walk → market orders. **Tests green (incl. fuzz) before moving on.**
3. `contract.py` — binary contract, complementary YES/NO, resolution.
4. `value_process.py`, `traders.py` — the latent resolving probability and the flow.
5. `portfolio.py` — inventory, cash, P&L, resolution settlement.
6. `fair_value.py` — micro-price baseline → independent estimate → Bayesian update.
7. `market_maker.py` — quoting, skew, resolution-aware widening, limits.
8. `engine.py` — Mode A first: wire flow + bot + book into the event loop.
9. `analysis/` — `metrics.py` (markout, decomposition), then `calibration.py`, `coherence.py`.
10. `engine.py` Mode B — real-data replay + the fill model.
11. `notebooks/experiments.ipynb` — the experiments and charts.

The order matters because after step 2 you already have a runnable, testable thing, and
every later step adds one capability you can test against the tested layer below it.

---

## 4. File length scale (1 = trivial boilerplate, 10 = large)

| File | Length 1–10 | Where the effort goes |
|---|---|---|
| `order.py` | 2 | Data holders + enums |
| `trade.py` | 1 | One frozen record |
| `book.py` | **7** | **The core — matching walk, most of your time** |
| `contract.py` | 3 | Complementary pairing + resolution rules |
| `value_process.py` | 2 | A seedable random walk that resolves |
| `traders.py` | 4 | Base class + noise + informed |
| `portfolio.py` | 4 | P&L accounting + settlement subtleties |
| `fair_value.py` | **6** | **Micro → independent → Bayesian; where edge lives** |
| `market_maker.py` | 5 | Skew + resolution-widening + limits |
| `engine.py` | 6 | Event loop + Mode A + Mode B fill model |
| `metrics.py` | 5 | Markout curve + decomposition |
| `calibration.py` | 3 | Brier, log loss, reliability binning |
| `coherence.py` | 4 | Executable-price arb detection + guards |
| `tests/test_book.py` | 6 | Example + invariant + fuzz |
| `experiments.ipynb` | — | Effort, not lines — the analysis |

Two files are 6–7 (`book.py`, `fair_value.py`), a cluster of 3–6 around them, and boilerplate
below. If `book.py` creeps toward 9, you're putting logic in it that belongs in the engine,
strategy, or analysis.

---

## 5. What to build — phases

- **Phase 0 — foundations (reading, no code).** Work through File 2 until you can explain
  adverse selection, price-time priority, the micro-price, and why a binary contract is a
  digital option. A few days.
- **Phase 1 — the book.** `order`, `trade`, `book`. Correct and tested to invariants + fuzz.
  This alone is a strong CV bullet and the foundation for everything.
- **Phase 2 — the market model.** `contract` (binary, complementary, resolution),
  `value_process` (resolving latent probability), `traders` (noise + informed). Now you can
  watch a synthetic prediction market evolve.
- **Phase 3 — the bot.** `portfolio`, `fair_value` (start at the micro-price baseline),
  `market_maker` (fixed spread → skew → resolution-aware widening). Wire into `engine` (Mode A).
- **Phase 4 — validation & analysis.** `metrics` (markout + decomposition), `calibration`
  (Brier/log loss vs the resolved value), `coherence` (arb detection). The experiments.
- **Phase 5 — real data (Mode B).** Replay Polymarket/Kalshi, add the fill model, re-score
  calibration and coherence against real resolved outcomes.
- **Later — C++ port** of the book core, differential-tested against the Python reference.

---

## 6. Design decisions — walk through your options

For each: the decision, the alternatives, and the reasoning — so you can weigh them yourself.

### 6.1 Prices as integer ticks (cents), not floats
**Alternatives:** floats; `Decimal`.
**Reasoning:** the book compares and matches on price constantly, and floats break exact
equality/ordering (`0.1 + 0.2 != 0.3`), silently corrupting matching. Prediction-market
contracts quote in integer cents (1–99), so integers are the natural representation anyway.
`Decimal` is exact but slower and unnecessary once prices are integers. **Your call:** none
really — use integer cents.

### 6.2 Time priority via a monotonic sequence number, not a timestamp
**Alternatives:** wall-clock or sim-clock timestamps.
**Reasoning:** in a discrete-event sim, multiple events can share the exact same virtual
time, so timestamps collide and FIFO ordering goes ambiguous and non-deterministic. A global
incrementing integer gives a strict, reproducible order — and reproducibility is the basis
of your controlled experiments. **Your call:** none — use a sequence number.

### 6.3 Price levels in a SortedDict
**Alternatives:** a heap; a plain dict + manually tracked best; a tick-indexed array.
**Reasoning:** you need cheap best-price access, insert, and — critically — cancel of an
arbitrary order, since most orders are cancelled not filled. A heap gives cheap best but
can't remove an interior element without O(n) bookkeeping; a plain dict makes finding the
new best after the top empties an O(n) scan; the tick-indexed array (index = price) is the
fast HFT choice but memory-heavy over wide ranges and best in C++. **Your call:** SortedDict
for Python. Note the tick-indexed array is more attractive for a prediction market than for
equities, because the price range is tiny (1–99 cents) — worth mentioning as a C++-port option.

### 6.4 A deque per price level, with a linked-list upgrade path
**Alternatives:** a Python list; an intrusive doubly-linked list + `{id → node}` map.
**Reasoning:** a level is FIFO; a deque is O(1) at both ends (append newest, popleft oldest)
— exactly the enqueue/dequeue pattern, where a list's O(n) front-pop would make every fill
slow. The deque's weakness is O(n) middle removal, which is what a cancel does. The
production fix is a doubly-linked list + `{id → node}` map for O(1) cancel-anywhere.
**Your call:** deque now (correct, readable); document the linked list as a deliberate
later optimisation. Knowing when *not* to optimise is itself the decision.

### 6.5 Active book: matching lives inside the book
**Alternatives:** a passive book + a standalone matching engine.
**Reasoning:** a single component owning the "never crossed" invariant is easier to test
(assert on the returned trades + book state). The matching logic mutates the book's internals
directly, so a separate engine would reach into them anyway. **Your call:** active book at
this scale; the separate-engine split only pays off at production scale.

### 6.6 Orders / trades: enums + dataclasses, with an immutable Trade
**Alternatives:** strings/bools for side/type; hand-written classes; mutable trades.
**Reasoning:** enums close the set of legal values and extend when new order types appear;
dataclasses cut boilerplate without losing methods. `Order` is mutable (its `remaining`
shrinks as it fills); `Trade` is frozen (a completed fact, and freezing makes it hashable
for serialisation). Intent (`Order`) vs event (`Trade`); one order can emit many trades.
**Your call:** none — this pairing is standard.

### 6.7 Time model: a hand-rolled event loop, not SimPy
**Alternatives:** SimPy; fixed time-steps.
**Reasoning:** a heap of `(time, seq, event)` popped in order is essentially what SimPy does
internally — writing it shows you understand discrete-event simulation. Fixed steps are
simpler but add grid artefacts and lose clean Poisson timing. **Your call:** hand-rolled if
exams allow (higher signal); SimPy if time is tight; fixed-step only as a last resort.

### 6.8 The market model: a latent probability that resolves
**Alternatives:** a fully endogenous price (no anchor); noise-only flow.
**Reasoning:** adverse selection only appears if some traders know something the maker
doesn't, so you need a latent value + informed traders. For a prediction market the latent
value is a probability in [0,1] that drifts and then *resolves* to 0 or 1 at a terminal date
— so informed flow reflects genuine probability updates and the resolution is observable
ground truth. **Your call:** how the latent probability moves (a bounded random walk, or a
logit-space walk that stays in (0,1)) and how noisy the informed signal is — that signal
strength is your "insider dial" for experiments.

### 6.9 Prediction-market instrument: complementary tokens & a merged book
**Alternatives:** model YES only; two fully independent books.
**Reasoning:** YES and NO are complementary (YES + NO = \$1). Modelling both, with the
constraint linking them, is what lets you study coherence/arbitrage. A "merged book" view —
where a resting NO bid at price *p* is economically a YES ask at *1−p* — captures that a
buyer of the set can source liquidity from either token. **Your call:** how far to go —
(a) two linked books with a coherence *check* across them (simpler, still gives the arbitrage
analysis), or (b) a fully merged book with collateral accounting that slots into
`book.submit()`. Start with (a); (b) is a strong extension. Verify outcomes are genuinely
exhaustive and mutually exclusive before treating a set as closed.

### 6.10 Fair-value model architecture: micro → independent → Bayesian
**Alternatives:** just quote the mid; a single black-box predictor.
**Reasoning:** layering separates "sensible baseline" from "edge." The micro-price baseline
needs no view (it's book-derived) and lets the bot provide liquidity from day one; the
independent estimate is where alpha lives; Bayesian updating is how you move fair value off
the baseline toward your view as evidence arrives. **Your call:** how to combine signals in
the update — a principled Bayesian posterior (clean story), or a weighted blend of
micro-price + independent estimate + flow signal (pragmatic). Either works; the Bayesian
version reads stronger and you've prototyped it already.

### 6.11 Resolution-aware quoting
**Alternatives:** quote the same spread throughout.
**Reasoning:** at resolution the price snaps discontinuously to 0 or 1, and whoever knows
first picks off stale quotes — a sharp adverse-selection hazard unique to these markets.
So widen spreads or pull quotes near resolution and around news. This is the
prediction-market analogue of volatility-widening in equities. **Your call:** the trigger —
time-to-resolution, a volatility/flow proxy, or an explicit "news event" flag you can toggle
in experiments.

### 6.12 P&L marking: conservative (exit side), plus resolution settlement
**Alternatives:** mark-to-mid; mark-to-last.
**Reasoning:** mark open inventory at the exit side (long at bid, short at ask), not mid —
mid flatters P&L by assuming you can close where no one trades. At resolution, settle
holdings to 0/1 (that's the terminal cash flow). Realised P&L via volume-weighted average
cost. **Your call:** none really — conservative marking + settlement is the honest choice.

### 6.13 Coherence detection: executable prices, net of costs
**Alternatives:** flag violations on headline/mid prices.
**Reasoning:** check the sum of *asks* (what you'd pay to buy the set) against \$1, and the
sum of *bids* against \$1 — never mids, because a mid "arb" usually vanishes at the spread.
Subtract fees and (for on-chain venues) gas; size by available depth; account for leg risk.
Most headline violations aren't real once frictions are in. **Your call:** whether to just
*report* real post-cost violation frequency (a market-efficiency finding) or *simulate
capturing* them and track P&L. Both are strong; reporting is less work.

### 6.14 Two evaluation modes: synthetic (A) + replay (B)
**Alternatives:** either alone.
**Reasoning:** Mode A gives controlled counterfactuals (re-run the identical world with one
knob changed) — the only way to make causal claims, and impossible on real data. Mode B
grounds the project in reality but your quotes were never in the historical book, so fills
need a *fill model* (a passive bid fills once a real trade prints at/below its price and the
queue ahead clears). **Your call:** how conservative the fill model is — strict
queue-position modelling (honest, harder) vs a simple "fills if a trade prints through the
price" (optimistic, easier). State whichever you pick and its limits.

### 6.15 Testing: three tiers
**Alternatives:** example tests only.
**Reasoning:** example tests confirm known cases; invariants (never crossed; shares
conserved) express correctness as always-true properties; the fuzz loop actively hunts for
the sequence that breaks them. **Your call:** none — do all three; the fuzz + invariants is
what separates you from toy projects.

---

## 7. Pseudocode frameworks

### `order.py`  (~2)
```python
from dataclasses import dataclass, field
from enum import Enum

class Side(Enum): BUY = 1; SELL = 2
class OrderType(Enum): LIMIT = 1; MARKET = 2

@dataclass
class Order:
    id: int
    side: Side
    type: OrderType
    price: int                    # TICKS (cents 1..99); ignored for market orders
    quantity: int
    remaining: int = field(init=False)
    seq: int = 0                  # set by the book on arrival (time priority)

    def __post_init__(self):
        self.remaining = self.quantity   # starts equal to quantity

    @property
    def is_filled(self) -> bool:
        return self.remaining == 0
```

### `trade.py`  (~1)
```python
from dataclasses import dataclass

@dataclass(frozen=True)            # immutable: a completed fact
class Trade:
    price: int
    quantity: int
    maker_id: int                  # resting (passive) order
    taker_id: int                  # incoming (aggressive) order
    seq: int
```

### `book.py`  (~7 — the core)
```python
from sortedcontainers import SortedDict
from collections import deque

class OrderBook:
    def __init__(self):
        # self.bids = SortedDict()   # tick -> deque[Order]; best bid = peekitem(-1)
        # self.asks = SortedDict()   # tick -> deque[Order]; best ask = peekitem(0)
        # self.locations = {}        # order_id -> (Side, tick)  for cancel
        # self._seq = 0
        ...

    def _next_seq(self): ...        # increment and return self._seq

    def best_bid(self): ...         # largest bid tick or None
    def best_ask(self): ...         # smallest ask tick or None
    def mid(self): ...              # (bid+ask)/2 if both sides else None
    def spread(self): ...           # ask - bid if both else None

    def micro_price(self):
        # book-derived fair value using top-of-book imbalance:
        #   I = Q_bid / (Q_bid + Q_ask)      where Q_* is size at best bid/ask
        #   micro = I * best_ask + (1 - I) * best_bid   ( = best_bid + I * spread )
        # return None if either side is empty
        ...

    def _rest(self, order):
        # side = self.bids if BUY else self.asks
        # if order.price not in side: side[order.price] = deque()
        # side[order.price].append(order)          # back = newest = time priority
        # self.locations[order.id] = (order.side, order.price)
        ...

    def add_limit_order(self, order) -> list:
        """Assign seq; match if crossing; rest remainder. Return list[Trade].
        POSTCONDITION: book not crossed."""
        # trades = []
        # opposite = self.asks if order.side is BUY else self.bids
        # while order.remaining > 0 and opposite non-empty:
        #     best_price, level = peek best of opposite  (asks->peekitem(0); bids->peekitem(-1))
        #     if BUY  and order.price < best_price: break     # no longer crosses
        #     if SELL and order.price > best_price: break
        #     resting = level[0]                              # front = oldest
        #     qty = min(order.remaining, resting.remaining)
        #     trades.append(Trade(best_price, qty, resting.id, order.id, self._next_seq()))
        #     order.remaining -= qty; resting.remaining -= qty
        #     if resting.remaining == 0: level.popleft(); del self.locations[resting.id]
        #     if len(level) == 0: del opposite[best_price]
        # if order.remaining > 0: self._rest(order)
        # return trades
        ...

    def add_market_order(self, order) -> list:
        # same loop as above but WITHOUT the price-limit checks; never rests —
        # discard any unfilled remainder (optionally log it). Return list[Trade].
        ...

    def cancel(self, order_id) -> bool:
        # look up (side, price) in self.locations; remove the order from that deque
        # (O(n) scan — deque); drop the level if empty; remove from locations.
        # Returns False if the id wasn't resting.
        # (O(1) upgrade: doubly-linked list + {id -> node}; splice in O(1).)
        ...
```

### `contract.py`  (~3)
```python
class BinaryMarket:
    """A single event with complementary YES/NO tokens on a [0,1]=(1..99c) grid."""
    def __init__(self, market_id):
        # self.yes_book = OrderBook(); self.no_book = OrderBook()
        # self.resolved = None        # None until resolution, then 0 or 1
        ...

    def complementary_price(self, tick):
        # a NO price p is economically a YES price (100 - p): return 100 - tick
        ...

    def resolve(self, outcome):        # outcome in {0, 1}
        # self.resolved = outcome; downstream: portfolio settles holdings to 0/1
        ...
```

### `value_process.py`  (~2)
```python
class ValueProcess:
    """Latent true probability in (0,1) that drifts, then resolves."""
    def __init__(self, p0, vol, resolve_time, seed=None): ...
    def step(self):
        # advance one tick; move p in LOGIT space so it stays in (0,1):
        #   x = logit(p); x += rng.gauss(0, vol); p = sigmoid(x); return p
        ...
    def outcome(self):
        # at resolve_time, draw the terminal outcome ~ Bernoulli(current p) -> 0/1
        ...
```

### `traders.py`  (~4)
```python
class BaseTrader:
    def generate_order(self, market, true_p): ...   # -> Order or None

class NoiseTrader(BaseTrader):
    def generate_order(self, market, true_p):
        # random side/size, price near the current mid — carries NO information.
        ...

class InformedTrader(BaseTrader):
    def generate_order(self, market, true_p):
        # compare true_p to the market's implied prob (mid/micro of YES):
        #   true_p notably above -> buy YES ; below -> sell YES (or buy NO)
        # give the signal NOISE/LAG (imperfect info) — strength is the "insider dial".
        ...
```

### `portfolio.py`  (~4)
```python
class Portfolio:
    def __init__(self):
        # self.position = 0     # +YES / -YES (short YES ~ long NO), in contracts
        # self.cash = 0; self.avg_cost = 0
        ...
    def on_fill(self, trade, our_side):
        # update cash/position; maintain volume-weighted avg_cost; realise P&L on the
        # portion that reduces/flips the position.
        ...
    def unrealised_pnl(self, market):
        # mark to the EXIT side: long -> best_bid, short -> best_ask (not mid).
        ...
    def settle(self, outcome):
        # at resolution: each YES contract pays `outcome` (0 or 1); book the cash flow.
        ...
```

### `fair_value.py`  (~6 — where edge lives)
```python
class FairValue:
    """Layered estimate of P(event). Output in (0,1)."""
    def __init__(self, prior_p, prior_strength):
        # store the prior as a distribution: e.g. Beta(a, b) with mean = prior_p and
        # a+b = prior_strength (confidence). Beta is conjugate for yes/no evidence.
        ...

    def baseline(self, market):
        # book-derived, no edge: the YES micro-price (bounded to (0,1)).
        ...

    def independent_estimate(self, features):
        # YOUR view of P(event) from an external model (base rate + hazard, a stats
        # model, etc.). This is the alpha layer — not derived from the market.
        ...

    def update(self, evidence):
        """Bayesian step. evidence = informed-looking flow and/or news.
        Posterior mean is the fair value — a PRECISION-WEIGHTED blend of prior and
        evidence, NOT a simple average."""
        # Beta case: a buy that looks informed -> a += w ; a sell -> b += w,
        #   where w scales with how INFORMATIVE the evidence looks (noisy flow -> small w).
        # fair_value = a / (a + b)              # posterior mean
        # (Normal case: posterior_mean =
        #   (mu_prior/var_prior + mu_evi/var_evi) / (1/var_prior + 1/var_evi))
        ...

    def value(self, market, features, evidence):
        # combine: start from prior, fold in independent_estimate and Bayesian updates;
        # optionally shrink toward baseline when you have little independent signal.
        # return one probability in (0,1).
        ...
```

### `market_maker.py`  (~5)
```python
class MarketMaker:
    def __init__(self, base_half_spread, max_position, fees, ...): ...

    def desired_quotes(self, market, portfolio, fair):
        """Produce (bid_tick, ask_tick, size) around `fair`. Layer:
          1. base:        fair ± base_half_spread
          2. cost floor:  half-spread >= fees + expected adverse selection + inv premium
          3. skew:        shift BOTH quotes against inventory (long -> lower to offload)
          4. resolution:  widen / pull quotes as time-to-resolution shrinks or on news
          5. limits:      at max_position, stop quoting the side that grows it
          6. clamp:       keep ticks within 1..99
        """
        ...

    def on_update(self, market, portfolio, fair):
        # cancel previous quotes; compute desired_quotes; submit the new pair.
        ...
```

### `sim/engine.py`  (~6)
```python
import heapq

class SimEngine:
    def __init__(self, market, value_process, traders, mm, portfolio, fair, mode="A"):
        # self.events = []    # heap of (time, seq, event)
        # self.log = []       # append trades, quotes, and periodic state snapshots
        ...

    def schedule(self, t, event): ...   # heappush with a tiebreak seq

    def run(self, until):
        """
        Mode A (synthetic): Poisson trader arrivals; step value_process as time advances;
        route each order into the book; on maker fills call portfolio.on_fill; trigger
        mm.on_update; at resolve_time call market.resolve + portfolio.settle. Snapshot
        mid/micro/position/P&L into self.log.

        Mode B (replay): synthetic traders OFF; feed historical messages to reconstruct
        the book. The bot's quotes were never in that book, so its fills come from a
        FILL MODEL, not the engine:
          your bid fills when a real trade prints at/below your price AND the size that
          was queued ahead of you at that price has cleared (price-time priority).
        """
        ...
```

### `analysis/metrics.py`  (~5)
```python
def markout(fills, mid_series, horizons=(1, 10, 60)):
    # for each fill at price P and time t, and each horizon h:
    #   signed_move = (mid[t+h] - P) * (+1 if we BOUGHT else -1)
    # positive = good; persistent negative at short h = adverse selection.
    # return average signed_move per horizon (the markout curve).
    ...

def decompose_pnl(fills, mid_series, fees):
    # split total P&L into:
    #   spread_captured  = half-spread earned at each fill
    #   adverse_selection = the negative markout term (prices moving against you after)
    #   inventory_pnl    = mark-to-market on the position as the mid drifts
    #   fees
    # return the components (they sum to total P&L).
    ...

def fill_rate(quoted_volume, filled_volume):
    # filled / quoted over a window — the "how much am I actually trading" dial.
    ...
```

### `analysis/calibration.py`  (~3)
```python
def brier(probs, outcomes):
    # mean( (p - o)^2 ) over resolved markets. Lower is better; range 0..1.
    ...

def log_loss(probs, outcomes):
    # -mean( o*ln(p) + (1-o)*ln(1-p) ). Punishes confident wrongness harder; clip p to
    # [eps, 1-eps] to avoid infinities.
    ...

def reliability(probs, outcomes, bins=10):
    # bin predictions; for each bin return (mean predicted, empirical frequency).
    # Plot vs the diagonal: flatter-than-diagonal = overconfident.
    ...
# The trader punchline: compute brier/log_loss for the MARKET's implied probs AND for
# your fair-value model over the same events. Lower than the market = measured edge.
```

### `analysis/coherence.py`  (~4)
```python
def find_arbitrage(books, fee_per_leg, gas=0):
    """books = the order books of a complete, mutually-exclusive, exhaustive outcome set.
    Use EXECUTABLE prices, net of costs."""
    # PRE-CHECK: assert the outcome set is exhaustive AND mutually exclusive.
    # buy-the-set arb : sum(best_ask_i) + costs < 1.0  -> lock in (1 - sum) per set
    # sell-the-set arb: sum(best_bid_i) - costs > 1.0  -> lock in (sum - 1) per set
    # size by the min depth across legs; report NET edge after fee_per_leg (+ gas).
    # (Complementary pair is the 2-outcome special case: YES_ask + NO_ask < 1, etc.)
    ...
```

---

## 8. Build checklist

- [ ] `order.py`, `trade.py`
- [ ] `book.py`: accessors + `_rest` + rest-only `add_limit_order`
- [ ] example tests green
- [ ] `book.py`: `cancel`, matching walk, `add_market_order`, `micro_price`
- [ ] invariant + fuzz tests green  ← do not proceed until this holds
- [ ] `contract.py`, `value_process.py`, `traders.py`
- [ ] `portfolio.py` (with `settle`)
- [ ] `fair_value.py`: baseline → independent → Bayesian `update`
- [ ] `market_maker.py`: base → skew → resolution-widening → limits
- [ ] `engine.py` Mode A; watch a synthetic market run end-to-end
- [ ] `metrics.py` (markout + decomposition), `calibration.py`, `coherence.py`
- [ ] `engine.py` Mode B + fill model
- [ ] `experiments.ipynb`: feature-effect experiments, calibration vs market, charts
- [ ] README: design decisions + measured results
- [ ] (later) C++ book core, differential-tested against this Python reference
