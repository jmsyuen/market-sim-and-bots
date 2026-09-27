'''
Runs every experiment and prints the results table.

    python experiments.py

Each experiment holds everything fixed except one dial, which is the only way
to make a causal claim. That is Mode A's whole reason for existing: the same
world can be re-run with one knob changed, which is impossible on real data.
'''

import random
import statistics
from itertools import count

from src.analysis import calibration, coherence, metrics
from src.market.value_process import ValueProcess
from src.orderbook.book import OrderBook
from src.orderflow.traders import InformedTrader, NoiseTrader
from src.portfolio import Portfolio
from src.sim.engine import FixedSpreadMaker, SimEngine
from src.strategy.fair_value import FairValue
from src.strategy.market_maker import MarketMaker

ARRIVAL_RATE = 200.0
MM_RATE = 100.0
SEEDS = 60


def build(seed, signal_noise=0.05, maker=None, p0=0.5, two_books=False,
          news=(), jump_vol=0.0):
    '''
    One market. Every component gets its OWN seeded RNG stream so that changing
    the maker does not shift the traders' draws - otherwise two runs are
    different worlds and the comparison means nothing.
    '''
    book = OrderBook(seq_source=count(1))
    no_book = None
    if two_books:
        no_book = OrderBook(seq_source=count(10_000_000))

    vp = ValueProcess(p0=p0, vol=1.0, resolve_time=1.0, seed=seed,
                      news_times=news, jump_vol=jump_vol)
    traders = [
        NoiseTrader(trader_id=1, rng=random.Random(seed + 100)),
        NoiseTrader(trader_id=2, rng=random.Random(seed + 200)),
        InformedTrader(trader_id=3, rng=random.Random(seed + 300),
                       signal_noise=signal_noise),
    ]
    if maker is None:
        maker = FixedSpreadMaker(trader_id=9, half_spread=3, size=5)
    portfolio = Portfolio()
    return SimEngine(book=book, value_process=vp, traders=traders,
                     market_maker=maker, portfolio=portfolio,
                     rng=random.Random(seed), arrival_rate=ARRIVAL_RATE,
                     mm_update_rate=MM_RATE, no_book=no_book)


def control_maker():
    return FixedSpreadMaker(trader_id=9, half_spread=3, size=5)


def skew_maker(risk_aversion=0.02, vol_sensitivity=0.0, use_fair_value=False):
    fair = None
    if use_fair_value:
        fair = FairValue(prior_strength=20.0, evidence_weight=0.05, half_life=0.05)
    return MarketMaker(trader_id=9, base_half_spread=3, size=5,
                       max_position=None, risk_aversion=risk_aversion,
                       vol_sensitivity=vol_sensitivity, decision_time=1.0,
                       fair_value=fair)


def average(rows, key):
    values = []
    for row in rows:
        if row[key] is not None:
            values.append(row[key])
    if len(values) == 0:
        return None
    return statistics.fmean(values)


def run_sweep(make_maker, noises, seeds=SEEDS):
    table = []
    for noise in noises:
        rows = []
        for seed in range(seeds):
            engine = build(seed, signal_noise=noise, maker=make_maker())
            engine.run(until=1.0)
            rows.append(metrics.summarise(engine))
        table.append({
            "signal_noise": noise,
            "pnl": average(rows, "total_pnl"),
            "contracts": average(rows, "contracts"),
            "spread_capture": average(rows, "spread_capture"),
            "adverse": average(rows, "adverse_selection"),
            "markout_short": average(rows, "markout_0.005"),
            "markout_long": average(rows, "markout_0.05"),
            "rms_inv": average(rows, "rms_inventory"),
            "settle_mk": average(rows, "settlement_markout"),
        })
    return table


print("=" * 78)
print("EXPERIMENT 1 - adverse selection vs signal quality (control maker)")
print("=" * 78)
noises = [0.50, 0.20, 0.10, 0.05, 0.02]
control = run_sweep(control_maker, noises)
print(f"{'noise':>7} {'P&L':>9} {'contracts':>10} {'spread cap':>11} "
      f"{'mk 0.005':>9} {'mk 0.05':>9} {'mk settle':>10}")
for row in control:
    print(f"{row['signal_noise']:>7.2f} {row['pnl']:>9.1f} {row['contracts']:>10.1f} "
          f"{row['spread_capture']:>11.1f} "
          f"{row['markout_short']:>9.3f} {row['markout_long']:>9.3f} "
          f"{row['settle_mk']:>10.3f}")

print()
print("=" * 78)
print("EXPERIMENT 2 - strategy layers, at signal_noise = 0.05")
print("=" * 78)
configs = [
    ("control (fixed spread)", lambda: control_maker()),
    ("+ inventory skew", lambda: skew_maker(risk_aversion=0.02)),
    ("+ vol-scaled spread", lambda: skew_maker(risk_aversion=0.02, vol_sensitivity=1.0)),
    ("+ Bayesian fair value", lambda: skew_maker(risk_aversion=0.02, vol_sensitivity=1.0,
                                                 use_fair_value=True)),
]
print(f"{'configuration':>24} {'P&L':>9} {'RMS inv':>9} {'contracts':>10} "
      f"{'spread cap':>11} {'adverse':>9}")
for name, make in configs:
    rows = []
    for seed in range(SEEDS):
        engine = build(seed, signal_noise=0.05, maker=make())
        engine.run(until=1.0)
        rows.append(metrics.summarise(engine))
    print(f"{name:>24} {average(rows, 'total_pnl'):>9.1f} "
          f"{average(rows, 'rms_inventory'):>9.1f} "
          f"{average(rows, 'contracts'):>10.1f} "
          f"{average(rows, 'spread_capture'):>11.1f} "
          f"{average(rows, 'adverse_selection'):>9.1f}")

print()
print("=" * 78)
print("EXPERIMENT 3 - calibration vs resolved outcomes")
print("=" * 78)
# ONE MARKET GIVES ONE OUTCOME, so calibration needs hundreds of independent
# resolved markets. p0 is varied across seeds or every forecast clusters at 0.5
# and the score says nothing.
market_probs = []
model_probs = []
outcomes = []
for seed in range(400):
    p0 = 0.1 + 0.8 * ((seed * 37) % 100) / 100.0
    fair = FairValue(prior_strength=20.0, evidence_weight=0.05, half_life=0.05)
    maker = MarketMaker(trader_id=9, base_half_spread=3, size=5, max_position=None,
                        risk_aversion=0.02, vol_sensitivity=1.0,
                        decision_time=1.0, fair_value=fair)
    engine = build(seed, signal_noise=0.05, maker=maker, p0=p0)
    engine.run(until=1.0)

    # the LAST snapshot before resolution. the final row is post-resolution and
    # would be 0 or 1, which would score a perfect Brier and mean nothing.
    last_micro = None
    for row in engine.log:
        if row["time"] < 1.0 and row["micro_price"] is not None:
            last_micro = row["micro_price"]
    if last_micro is None or engine.value_process.outcome is None:
        continue

    model_tick = fair.value(engine.book, 0.999)
    if model_tick is None:
        continue

    market_probs.append(last_micro / 100.0)
    model_probs.append(model_tick / 100.0)
    outcomes.append(engine.value_process.outcome)

print(f"resolved markets: {len(outcomes)}   base rate: {sum(outcomes)/len(outcomes):.3f}")
benchmark = calibration.base_rate_benchmark(outcomes)
market_score = calibration.score(market_probs, outcomes)
model_score = calibration.score(model_probs, outcomes)
print(f"{'forecaster':>22} {'Brier':>8} {'log loss':>10}")
print(f"{'base rate (benchmark)':>22} {benchmark:>8.4f} {'-':>10}")
print(f"{'market (micro-price)':>22} {market_score['brier']:>8.4f} "
      f"{market_score['log_loss']:>10.4f}")
print(f"{'Bayesian fair value':>22} {model_score['brier']:>8.4f} "
      f"{model_score['log_loss']:>10.4f}")

print()
print("=" * 78)
print("EXPERIMENT 4 - coherence arbitrage, YES/NO pair")
print("=" * 78)
pairs = []
for seed in range(200):
    maker = MarketMaker(trader_id=9, base_half_spread=3, size=5, max_position=None,
                        risk_aversion=0.02, vol_sensitivity=1.0, decision_time=1.0)
    engine = build(seed, signal_noise=0.05, maker=maker, two_books=True)
    engine.run(until=1.0)
    pairs.append((engine.book, engine.no_book))

for fee in [0.0, 0.5, 1.0]:
    stats = coherence.violation_frequency(pairs, fee_per_leg=fee, gas=0.0)
    survival = stats["survival_rate"]
    if survival is None:
        survival_text = "n/a"
    else:
        survival_text = f"{survival:.1%}"
    print(f"fee/leg {fee:>4} ticks  snapshots {stats['snapshots']:>4}  "
          f"headline {stats['headline']:>4}  executable {stats['executable']:>4}  "
          f"net {stats['net']:>4}  survival {survival_text}")
