Prediction market order book

simulated traders and price over stochastic process
market maker bot - arbitrage logic in prediction market 
    markout analysis - measure adverse selection, calibration/coherence analysis shows trader's judgement

# explained for CV


Order book:
Two sides,

Mode A simulation, value_process:

x is a hidden underlying value on the real line, log-odds so we don't have to clip to make it fit within (0,1), 
p = sigmoid(x), converting x to a probability in (0,1),
then every step x is affected by volatility scaled random walk pulled from a gaussian distribution,
and x is also affected by a volatility scaled drift to make p a martingale and correct for a drift towards 0.5,
this value process is also affected by jumps (simulated news events) both scheduled and unscheduled which spike volatility temporarily
informed traders see this x with noise added to it in logit space,
they trade towards it to simulate a more accurate estimate of the market. 
at the end the market resolves by rolling the final probability on a Bernoulli dist


Design decisions:
Logit space to stay within [0,1] probability space, avoids clipping which piles probability mass against boundaries, avoid asymmetric walk near boundary

Mode B simulation, from real data:



Strategy:

