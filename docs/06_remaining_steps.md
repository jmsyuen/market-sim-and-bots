# Remaining work — step by step

One file, one step at a time. Each step ends with something you can run.
Tick them off here.

Status when this was written: `fair_value.py` done, 17 tests green.
Total suite: 72 passing.

---

## STEP 1 — wire FairValue into MarketMaker  (20 min)

**Goal:** `MarketMaker` quotes around the Bayesian estimate instead of nothing.

- [ ] `_reference(book, time)` — note the extra `time` parameter, decay needs it

```python
def _reference(self, book, time):
    if self.fair_value is not None:
        return self.fair_value.value(book, time)
    return book.micro_price
```

- [ ] `quotes(book, portfolio, time)` — assembly with every feature off:

```python
reference = self._reference(book, time)
if reference is None:
    return None

half = self._half_spread(time)

bid = clamp_tick(round(reference - half))
ask = clamp_tick(round(reference + half))
if bid >= ask:
    return None

return (bid, ask, self.size)
```

- [ ] `_half_spread(time)` — just the base and the cost floor for now:

```python
half_spread = self.base_half_spread
if half_spread < self.fee_per_contract:
    half_spread = self.fee_per_contract
return half_spread
```

**Test:** with `fair_value=None` and everything off, quotes match
`FixedSpreadMaker` at the same `base_half_spread`. If they don't, stop — the
difference is plumbing, and every later comparison would inherit it.

---

## STEP 2 — inventory skew  (30 min)

**Goal:** the CV's "inventory skew".

- [ ] Constant volatility first. `vol_estimate` starts at 0.0, which would make
      the skew vanish, so use a fixed placeholder until step 3:

```python
def _reservation_price(self, reference, position, time):
    time_left = self.decision_time - time
    if time_left < 0:
        time_left = 0.0
    vol = self.vol_estimate
    if vol <= 0.0:
        vol = 1.0          # placeholder until step 3
    return reference - position * self.risk_aversion * (vol ** 2) * time_left
```

- [ ] In `quotes`, centre on the reservation price:

```python
centre = self._reservation_price(reference, portfolio.position, time)
bid = clamp_tick(round(centre - half))
ask = clamp_tick(round(centre + half))
```

**Sign check before running anything.** `position = +10`, `risk_aversion = 0.1`,
`time_left = 1`, `vol = 1` → `r = reference - 1`. BELOW the reference. If yours
is above, the skew is accelerating inventory.

**Tests:** long moves both quotes down, short moves both up, the SPREAD is
unchanged, `risk_aversion = 0` centres exactly on the reference.

---

## STEP 3 — volatility scaling  (30 min)

**Goal:** the CV's "volatility scaled spreads".

- [ ] `_update_volatility(reference, time)`:

```python
if self._last_reference is None or self._last_time is None:
    self._last_reference = reference
    self._last_time = time
    return

dt = time - self._last_time
if dt <= 0:
    return

move = (reference - self._last_reference) / math.sqrt(dt)
decay = 0.5 ** (dt / self.vol_half_life)
self.vol_estimate = decay * self.vol_estimate + (1 - decay) * abs(move)

self._last_reference = reference
self._last_time = time
```

- [ ] Add one line to `_half_spread`: `half_spread += self.vol_sensitivity * self.vol_estimate`
- [ ] Call `_update_volatility` in `quotes`, AFTER `_reference` and BEFORE
      `_reservation_price` — the skew reads `vol_estimate`.
- [ ] Drop the placeholder in `_reservation_price` now that vol is real.

**Tests:** a fast-moving reference raises the estimate; a static one decays it;
the estimate is the same whether fed at one requote rate or double it.

---

## STEP 4 — metrics.py  (60 min) ← the hard middle

**Goal:** CV bullet 2. This is the one to push through.

- [ ] `reference_at` with bisect. Hoist the times list in the callers.
- [ ] `markout` — quantity-weighted, skip fills with no future reference
- [ ] `decompose_pnl` — spread capture, adverse selection, fees, inventory as
      the RESIDUAL so the four sum to the total by construction
- [ ] `rms_inventory`, `edge_per_contract`, `summarise`

**Test:** the four components sum to total P&L. That one assertion catches most
of what can go wrong here.

---

## STEP 5 — the signal_noise sweep  (30 min)

**Goal:** the number that makes bullet 2 true.

- [ ] Loop `signal_noise` over `[0.5, 0.2, 0.08, 0.02, 0.0]`, 40 seeds each
- [ ] Record: P&L, fill count, spread capture, markout at each horizon
- [ ] Expect fill count and spread capture roughly FLAT while markout
      deteriorates and P&L collapses. That is the whole story: the loss is
      adverse selection, not less trading.

Baseline from the fixed-spread control, for comparison:

| half_spread | signal_noise | P&L | peak abs position |
|---|---|---|---|
| 10 | 0.5 | +82 | 30.6 |
| 10 | 0.02 | −950 | 47.6 |

---

## STEP 6 — calibration.py  (40 min)

**Goal:** bullet 4, first half.

- [ ] `brier`, `log_loss` — ten lines between them
- [ ] `collect(build_engine, seeds)` — one market per seed, take the prediction
      from the LAST snapshot before `decision_time`, not the final row
- [ ] Vary `p0` across seeds or every prediction clusters at 0.5
- [ ] Score the market's implied probability AND `FairValue.probability`
      against the same outcomes

**The punchline:** lower Brier than the market is measured edge. Also report the
base-rate benchmark, `p0 * (1 - p0)`, so the numbers have something to beat.

---

## STEP 7 — two books  (40 min)

**Goal:** prerequisite for coherence. Nothing to detect with one book.

- [ ] `SimEngine` takes `books` as a dict or pair instead of one `book`
- [ ] Each arrival picks a book (coin flip in `_handle_arrival`)
- [ ] NO-book traders reference `100 - true_p`
- [ ] The maker quotes the YES book only, for now

---

## STEP 8 — contract.py + coherence.py  (60 min)

**Goal:** bullet 4, second half.

- [ ] `BinaryMarket.complementary_price` — one line
- [ ] `implied_yes_from_no` — **the best NO ask implies a YES bid.** Write the
      test before the code; getting this backwards manufactures arbitrage
      everywhere and the numbers look exciting rather than wrong.
- [ ] `executable_cost_to_buy_set` — walk `book.depth()` level by level, not
      `best_ask * quantity`
- [ ] `find_arbitrage` — fees are PER LEG, so doubled for a pair
- [ ] `violation_frequency` — headline vs executable vs net, and the survival
      rate

**The reportable number** is the survival rate with its cost assumptions
attached, e.g. "38% of apparent violations survived executable prices and a
1-tick-per-leg fee". A number without assumptions is not credible.

---

## STEP 9 — README  (45 min)

- [ ] What it is, in three sentences
- [ ] The four layers
- [ ] Design decisions — lift from `docs/design_decisions.md`, it is written
      for this
- [ ] Results: the sweep table, the calibration scores, the survival rate
- [ ] Limitations, honestly — the list at the end of `design_decisions.md`

---

## Deferred — not needed for the CV

Marked so they don't creep back in:

- `risk_aversion` frontier sweep (bullet 3 claims the feature exists, not that
  a frontier was measured)
- News and resolution widening, and the scheduled-vs-unscheduled asymmetry
  experiment — the most distinctive thing here, and the first to add back
- Position limits
- Reliability curve
- Mint and merge
- Mode B replay
- The RNG-cadence fix in `value_process` (see `design_decisions.md`)

---

## If time runs out

Stop at the end of whatever step you are on, run the suite, commit. A repo
with steps 1–6 finished and 7–9 untouched is coherent. A repo with nine
half-finished steps is not.
