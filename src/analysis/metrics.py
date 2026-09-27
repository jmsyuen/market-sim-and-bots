'''
Markout and P&L decomposition.

This file is what turns "my P&L fell" into "my P&L fell BECAUSE of adverse
selection", which is the difference between CV bullet 2 being a claim and being
a measurement.

INPUTS, both produced by the engine with no extra work:
    fills      - portfolio.fills, a list of (trade, our_side) pairs. trade.time
                 is set because the engine lends the book its clock.
    reference_series - [(time, micro_price)] pulled out of engine.log. Use
                 micro_price, not mid: mid ignores queue imbalance, so a fill
                 that happened precisely because the book was one-sided gets
                 measured against a reference that cannot see that.
'''

import bisect

# markout horizons in SIM TIME units, not events. With resolve_time = 1.0 and
# ~200 arrivals per unit time, 0.005 is roughly one event and 0.05 is roughly
# ten. Short horizons show adverse selection; long ones drown in drift.
DEFAULT_HORIZONS = (0.005, 0.02, 0.05)


def reference_at(reference_series, time):
    '''
    The most recent reference at or before `time`, or None if there is none.

    bisect over a pre-sorted list, not a linear scan: markout calls this once
    per fill per horizon, so a scan makes the whole analysis quadratic in a run
    with a few thousand fills.

    Step-function lookup (last known value), NOT interpolation. Interpolating
    between two quotes invents a price that never existed, and near a news jump
    it would smear the gap you are specifically trying to measure.
    '''
    # times = [t for t, _ in reference_series] -- hoist this OUT of the loop in
    # the callers below; rebuilding it per fill is the quadratic trap again.
    # index = bisect.bisect_right(times, time) - 1
    # if index < 0: return None
    # return reference_series[index][1]
    ...


def markout(fills, reference_series, horizons=DEFAULT_HORIZONS):
    '''
    The signed price move after each fill, averaged per horizon.

        signed_move = (reference[t + h] - fill_price) * our_side.sign

    Positive is good: the price moved our way after we traded. PERSISTENTLY
    NEGATIVE AT SHORT HORIZONS IS ADVERSE SELECTION - the counterparty knew
    something, and the price kept going the way they pushed it.

    Returns {horizon: mean signed move in ticks}. Weight by quantity, not by
    fill count: one 10-lot pickoff should not count the same as one 1-lot.

    Skip fills with no reference at t+h (the run ended). Do NOT substitute the
    last known price - that silently reports zero markout for exactly the fills
    that happened closest to resolution, which are the most toxic ones.
    '''
    # hoist the times list once
    # for each horizon:
    #     total_move = 0.0
    #     total_quantity = 0
    #     for trade, our_side in fills:
    #         future = reference_at(...)   at trade.time + horizon
    #         if future is None: continue
    #         total_move += (future - trade.price) * our_side.sign * trade.quantity
    #         total_quantity += trade.quantity
    #     record total_move / total_quantity  (guard total_quantity == 0)
    ...


def decompose_pnl(fills, reference_series, total_pnl,
                  horizon=0.05, fee_per_contract=0.0):
    '''
    Split total P&L into four parts that SUM to it.

        spread_capture    = (reference_at_fill - price) * sign * quantity
                            summed. What you earned for providing liquidity:
                            you bought below the reference or sold above it.

        adverse_selection = (reference_at(t+h) - reference_at(t)) * sign * qty
                            summed. How the reference itself moved after you
                            traded. Negative means you were picked off.

        fees              = -fee_per_contract * total contracts

        inventory         = the RESIDUAL. Mark-to-market on the position as the
                            reference drifts, plus settlement.

    Making inventory the residual is deliberate: it forces the four parts to
    sum to the total by construction, so the decomposition can never quietly
    disagree with the P&L it claims to explain. Computing all four
    independently and finding they nearly add up is how you spend an afternoon
    chasing a rounding difference.

    Note the two terms are measured against the SAME reference at the SAME
    instant, so they do not double count: spread capture is price versus
    reference at t, adverse selection is reference at t versus reference at
    t+h.

    Returns a dict. Assert the four sum to total_pnl in the test.
    '''
    ...


def rms_inventory(log):
    '''
    Root mean square position across the run. The risk half of the risk/return
    frontier.

    RMS, not mean: a maker that sits at +50 then -50 has a mean near zero and
    has been carrying enormous risk the whole time.
    '''
    ...


def edge_per_contract(total_pnl, fills):
    '''
    Total P&L divided by contracts traded. The return half of the frontier.

    Per CONTRACT, not per fill. Trading 1000 contracts badly and 10 well should
    not look like a 50/50 split.
    '''
    ...


def summarise(engine, fee_per_contract=0.0):
    '''
    One call the experiments notebook can use per run.

    Pull reference_series out of engine.log, skipping rows where micro_price is
    None (the book was one-sided). Return a flat dict of every number above
    plus the markout curve, so a sweep is just a list of these fed to a
    DataFrame.
    '''
    ...
