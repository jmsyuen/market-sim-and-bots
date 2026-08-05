market sim and bot

# OVERVIEW PLAN
composition

prediction market order book
matching engine
prediction market - market resolves to a ground truth

simulated traders and price over stochastic process
market maker bot - arbitrage logic in prediction market 
    markout analysis - measure adverse selection, calibration/coherence analysis shows trader's judgement
    


## subsections (features to build)
## book


## bot
logic:
core loop is the same as any MM, to profit from noise: estimate fair value, manage inventory with skew, requote as things change with bayesian updating, scale spread with volatility
quoted spread must cover fees, expected adverse selection, inventory-risk premium, (venue fees)

Bayesian fair value → where the centre of your quote sits
Volatility-scaled spread → how wide you quote around it
Inventory skew → how far you shift off centre given the position you're holding

resolution jump risk - widen spreads or pull quotes near resolution and news events

2 edges:
1. informational edge knowing true prob better than market
2. liquidity compensation - spread is a fee you're paid for a service, providing immediacy and bearing inventory and adverse-selection risk of holding other side

Fair value model:
1. baseline (book-derived micro-price, no edge) 
2. independent estimate (our edge) our own P(event), external of the market, lean into disagreements
3. bayesian updating - start from prior probability eg. opening price, update as evidence arrives - news, informed-looking order flow - use Bayes' rule which says the posterior mean is fair value 

Steps to build fair value model:
1. define information set - micro-price from book imbalance, trade flow, time-to-resolution, others
2. set a prior
3. define update rule - bayesian update or weighted blend of these signals, use posterior mean model, output probability
4. validate with brier/log loss against ground truth - on simulated data and real data (need fill model)



encapsulated feature toggles (to test each one and results)
metrics logging (mean/max |inventory|, fill rate, P&L, P&L variance/Sharpe.)
seeding for random data to be reproducible
plotting of bot performance using brier score (mse vs resolved value) against market, lower score than market is our measured edge, and our objective when tuning our model, and log loss for overconfidence



## Points for CV (2 trader, 1 engineering for rigor)
robustness - validated no book cross, n million random operations, no invariant violations (order book working as intended), coherence violations (arbitrage opportunites frequency and hit rate)
volatility (spread) widening, inventory skew, measured and analysed for results - see decomposition
measured brier score edge vs market, log loss overconfidence


(vol-widening cut adverse-selection losses by Y%.")
frame prediction market as applied methodology (ground truth validation) not because its new area - and depth always trumps
prediction unlocks calibration/coherence analysis for trader's judgement

# design decisions

price-time priority - best price then earliest order fills
price level - 2dp but in system as integers / 100 not floats
time level priority - using a global monotonic sequence number assigned at receival not timestamp (price, seq)
make order quantity mutable, reduce as you fill the order, but keep records for logs
partial fills left as resting
(tail latency 99percentile discussed, volatility spikes are where you get lose)
bot feature effect (result of adjusting a parameter on identical simulated data)
arbitrage (on chain gas cost, operator venue cuts, actual spread not headline prices)
resolution jump risk - at resolution price discontinuously snaps to either side, those who know first pick off your stale quotes, widen spreads or pull quotes near resolution and news events
spread captured by providing liquidity risks filling to informed flow

prediction vs exchange - prediction slower, python could compete, but harder to profit: thin liquidity, events idiosyncratic (specific) so less statistical regularity to exploit, real edge often needs domain forecasting (politics, sports)

the posterior mean minimises expected squared error, which is what Brier score measures.


also design a visualiser with best price?

# terminology

deque - doubly linked list for o(1) when popping front too instead of normal list o(n) when shifting everything forwards
order - instruction order (mutable)
trade - record of executed trade (immutable)

limit order - execute at this price only
market order - execute all volume, regardless of price

makers - place resting orders, provides liquidiy, shows on market 
takers - complete the resting orders to remove orders from the market
fill rate - how much of posted quotes actually trades (low - too wide from trading value or passive)
markout - standard way to measure adverse selection on a fill, fair price some time t later, plot on several horizons (markout curve) 1s, 10s, 1min - bought at P and price moves up is markout +x good, vs bought and price moves down
    (consistent negative short-horizon markout means you're being adversely selected)

decomposition - splitting PnL sources = +spread captured (half), inventory PnL as market drift, -adverse selection losses (markout), -fees
book imbalance - which side has more resting size (short-term directional pressure)
micro-price - uses imbalance to estimate fair value (weighted imbalance) - heavy bids mean fv closer to ask than midpoint
micro = I·P_ask + (1 − I)·P_bid = P_bid + I·spread
AS Avellaneda Stoikov micro price model also models how imbalance predicts future mid

posterior mean - a point estimate after observing data, between prior beliefs and observed evidence - simplified, a weighted average of prior mean and sample data mean based on confidence
(weights determined by the precision (inverse variance) or effective sample size of the prior and the data)
In the clean conjugate-normal case: posterior mean = (μ_prior/σ²_prior + μ_evidence/σ²_evidence) / (1/σ²_prior + 1/σ²_evidence)

