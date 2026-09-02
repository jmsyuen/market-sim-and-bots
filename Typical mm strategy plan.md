# Typical market making strategy broken down


Concepts and how to counter:
Adverse selection:
Directional risk:
	inv skew - shift off centre given position you're holding
	hedge - when past a threshold (eg more than taker fee)
volatility spread scaling - width of spread


Overview of a solid example strategy:
	post new quote:
		calculate current fv and current market mid (our edge)
		adjust for inv skew, check against position limit
		volatility scaled spread
		must cover fees


Approach logic of example task ladder:

1. quoting a fixed spread
	Loop:
	cancel/modify current quotes
	requote:
		centre around market mid
		check against position limit, don't post side which would exceed limit

	Checks: 
		set limit to 5 and assert that it doesn't break
		show me the test cases and outputs
	Problems:
		Inventory directional risk

2. skew and widen
	Inv Skew:
	Shift both sides of quote off centre by amount proportional to position, better price to those who lift side you don't want
	Widen:
	Scale with volatility 

	Add to fv calculation:
	fair: mid - k * position 
		sweep k to see PnL std changes rather than PnL mean
	spread: base * (1 + alpha * recent_vol)

	Problems:
		Skew is slow, only unwinds when someone decides to trade
	

3. hedge in another related instrument
	Hedge opposite direction in related instrument cheaper per unit exposure

	Checks: 
		Definition of position (filled quantity only vs with working orders)
		Hedge logic: run a sim with 0 volatility, hedged PnL should be roughly 0. Else, hedge ratio or sign is wrong.
		Always opposite direction - flip hedge when position flips
	Problems:
		Not all counterparties have same knowledge, some more informed.

4. adverse selection
	Measure it:
	After each fill, look where market mid appears a few ticks later.
	Watch if fills systematically followed by moves against you

	Act:
	Widen or pull, not skew harder
	Simple version:
	Track the post-fill move of market mid over average of last N fills on each side. Widen the side that moves against you.




# Hedging

Deliberately give up upside to remove downside with OPPOSITE direction in similar instrument
Isolate risk you actually want

1. Be clear which risk you want to remove:
	mm in ETF exposed to direction, volatility, basis, lack of liquidity -> hedge with future removes the directional risk
2. Costs:
	Pay spread and fees on hedge, hedge itself still has risk
3. Hedges are imperfect. Basis risk:
	Risk of hedge and position don't move together as expected
	Still smaller than removed risk, but not 0.
	
Measure with hedge ratio: how much hedge per unit of position
eg. etf against future on same index -> roughly ratio of notional values
if future has 10x notional per contract, 10 etf shares hedged by 1 future

When to hedge: can't for all as costs
Small exposure - inv skew
Large past a threshold - hedge
	Setting the threshold: too tight -> lose to fees, too wide -> lose to one adverse selection move



Related terminology:

ETF: different wrapper around same exposure


Future: unlike options, trade at fixed price in fixed time
Cheap, more liquid than ETF, usually tracks underlying asset very closely subject to supply and demand.
Indexed futures typically tighter spreads, more depth
Leveraged - full exposure for fraction of capital

Put simply for hedging, usually can neutralise risk by taking OPPOSITE position in other


bid ask, someone buy/sell
you buy high sell low at current price

limit order -  limit price willing to trade at, fok
market order - specified quantity through multiple levels, not recommended by optiver





# My strategy from Da Vinci OA
bear in mind the setup was different: rfq, no fees, dataset available, no depth information, trade happens within 0.15 of market mid price

2 parts:
fair value model
quoting strategy

data analysis on the given dataset, test variety of strategies on this, using half of the data as in sample then test on second half as out of sample to bring out overfitted parameters - settled with ema30s over lead lag

counter adverse selection:
inventory skew - off centre quotes when taking directional risk
volatility scaled spread - widen with sharp moves
monitor for adverse selection, watch the moves of market and trades with you post-fill execution, can counter by stopping inventory skew and widen spread to discourage trades
no related instruments, so no hedging possible

test both sets of parameters, but optimise for robustness instead of overfitting parameters