'''
Markout and P&L decomposition.

This is what turns "my P&L fell" into "my P&L fell BECAUSE of adverse
selection". Without it, the flow experiment produces a number with no
explanation attached.

INPUTS, both produced by the engine with no extra work:
    fills            - portfolio.fills, a list of (trade, our_side). trade.time
                       is set because the engine lends the book its clock.
    reference_series - [(time, micro_price)] from engine.log. Micro, not mid:
                       mid ignores queue imbalance, so a fill that happened
                       precisely because the book was one-sided would be
                       measured against a reference that cannot see that.
'''

import bisect
import math

# Horizons in SIM TIME, not events. With resolve_time 1.0 and ~200 arrivals per
# unit time, 0.005 is about one event and 0.05 about ten. Short horizons show
# temporary impact; settlement_markout below shows the permanent damage.
DEFAULT_HORIZONS = (0.005, 0.02, 0.05)


def _times_of(reference_series):
    times = []
    for time, _ in reference_series:
        times.append(time)
    return times


def reference_at(reference_series, times, time, strict=False):
    '''
    The reference price as of `time`, or None if the run had not started.

    Step-function lookup, NOT interpolation: interpolating invents a price that
    never existed, and across a news jump it would smear out exactly the gap
    being measured.

    strict=True takes the last snapshot STRICTLY BEFORE `time`. This matters
    more than it looks. The engine snapshots AFTER handling each event, so the
    snapshot stamped at a fill's own timestamp already contains that fill's
    impact - the sweep has eaten the quote and moved the touch. Measuring
    spread capture against it would credit the maker with price impact caused
    by the very trade that hurt it, and would hide the same move from the
    adverse-selection term. Pre-trade for "where was the market when I traded",
    post-trade for "where is it now".

    `times` is passed in rather than rebuilt, because this is called once per
    fill per horizon and rebuilding it here would make the analysis quadratic.
    '''
    if strict:
        index = bisect.bisect_left(times, time) - 1
    else:
        index = bisect.bisect_right(times, time) - 1
    if index < 0:
        return None
    return reference_series[index][1]


def markout(fills, reference_series, horizons=DEFAULT_HORIZONS):
    '''
    Signed price move after each fill, quantity-weighted, per horizon.

        signed_move = (reference[t + h] - fill_price) * our_side.sign

    Positive is good. Measured from the FILL PRICE, so a passive fill starts
    roughly one half-spread ahead; what matters is how that number DECAYS as
    the horizon grows.

    Fills with no reference at t+h are SKIPPED, not substituted with the last
    known price. Substituting reports zero markout for the fills closest to
    resolution, which are the most toxic ones in the run.
    '''
    times = _times_of(reference_series)
    curve = {}

    for horizon in horizons:
        total_move = 0.0
        total_quantity = 0

        for trade, our_side in fills:
            if trade.time is None:
                continue
            future = reference_at(reference_series, times, trade.time + horizon)
            if future is None:
                continue
            total_move += (future - trade.price) * our_side.sign * trade.quantity
            total_quantity += trade.quantity

        if total_quantity == 0:
            curve[horizon] = None
        else:
            curve[horizon] = total_move / total_quantity

    return curve


def decompose_pnl(fills, reference_series, total_pnl, horizon=0.05,
                  fee_per_contract=0.0):
    '''
    Split total P&L into four parts that SUM to it.

        spread_capture    (reference_at_fill - price) * sign * qty
        adverse_selection (reference[t+h] - reference[t]) * sign * qty
        fees              -fee_per_contract * contracts
        inventory         THE RESIDUAL - mark-to-market plus settlement

    Inventory is the residual deliberately. It forces the parts to sum to the
    total by construction, so the decomposition can never quietly disagree with
    the P&L it claims to explain. Computing all four independently and finding
    they nearly add up is an afternoon lost to a rounding difference.

    The two measured terms do not double count: spread capture is price versus
    reference AT the fill, adverse selection is reference at t versus t+h.
    '''
    times = _times_of(reference_series)

    spread_capture = 0.0
    adverse_selection = 0.0
    contracts = 0

    for trade, our_side in fills:
        contracts += trade.quantity
        if trade.time is None:
            continue

        now = reference_at(reference_series, times, trade.time, strict=True)
        if now is None:
            continue

        spread_capture += (now - trade.price) * our_side.sign * trade.quantity

        future = reference_at(reference_series, times, trade.time + horizon)
        if future is None:
            continue
        adverse_selection += (future - now) * our_side.sign * trade.quantity

    fees = -fee_per_contract * contracts
    inventory = total_pnl - spread_capture - adverse_selection - fees

    return {
        "spread_capture": spread_capture,
        "adverse_selection": adverse_selection,
        "fees": fees,
        "inventory": inventory,
        "total": total_pnl,
        "contracts": contracts,
    }


def settlement_markout(fills, outcome):
    '''
    Markout measured all the way to RESOLUTION, in ticks per contract.

        (outcome * 100 - price) * sign

    In a resolving market this is the honest long-horizon markout, and it
    exists here in a way it cannot for equities: there is a terminal truth to
    mark against.

    WHY IT IS NEEDED alongside the short-horizon curve, and the most useful
    thing the analysis layer found. An aggressive sweep displaces the touch, so
    micro-price markout at one or ten events captures TEMPORARY impact, which
    mean-reverts as noise traders refill the level. The information the
    informed trader acted on is only fully revealed at settlement. Measuring
    only short horizons therefore understates adverse selection badly in this
    market structure: the damage is real but it does not show up in the mid
    until the answer does.
    '''
    total = 0.0
    quantity = 0
    payoff = outcome * 100
    for trade, our_side in fills:
        total += (payoff - trade.price) * our_side.sign * trade.quantity
        quantity += trade.quantity
    if quantity == 0:
        return None
    return total / quantity


def rms_inventory(log):
    '''
    Root mean square position. RMS, not mean: a maker that sits at +50 then -50
    has a mean near zero and has been carrying enormous risk throughout.
    '''
    total = 0.0
    count = 0
    for row in log:
        total += row["position"] ** 2
        count += 1
    if count == 0:
        return 0.0
    return math.sqrt(total / count)


def edge_per_contract(total_pnl, fills):
    '''Per CONTRACT, not per fill.'''
    contracts = 0
    for trade, _ in fills:
        contracts += trade.quantity
    if contracts == 0:
        return None
    return total_pnl / contracts


def summarise(engine, fee_per_contract=0.0, horizons=DEFAULT_HORIZONS):
    '''
    One call per run for the sweeps. Returns a flat dict so a list of these
    goes straight into a DataFrame.

    Rows with micro_price None are dropped: the book was one-sided and there
    was no reference to measure against.
    '''
    reference_series = []
    for row in engine.log:
        if row["micro_price"] is not None:
            reference_series.append((row["time"], row["micro_price"]))

    fills = engine.portfolio.fills
    total_pnl = engine.portfolio.realised_pnl
    if engine.value_process.outcome is None:
        raise ValueError("summarise expects a resolved market; run past resolve_time")

    curve = markout(fills, reference_series, horizons)
    parts = decompose_pnl(fills, reference_series, total_pnl,
                          fee_per_contract=fee_per_contract)

    summary = {
        "total_pnl": total_pnl,
        "fills": len(fills),
        "contracts": parts["contracts"],
        "spread_capture": parts["spread_capture"],
        "adverse_selection": parts["adverse_selection"],
        "inventory": parts["inventory"],
        "rms_inventory": rms_inventory(engine.log),
        "edge_per_contract": edge_per_contract(total_pnl, fills),
        "trades_in_book": len(engine.book.trades),
        "settlement_markout": settlement_markout(fills, engine.value_process.outcome),
    }
    for horizon in horizons:
        summary["markout_" + str(horizon)] = curve[horizon]
    return summary
