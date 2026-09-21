Prediction market order book

simulated traders and price over stochastic process
market maker bot - arbitrage logic in prediction market 
    markout analysis - measure adverse selection, calibration/coherence analysis shows trader's judgement

# explained for CV


Order book:
Two sides,

Mode A simulation, value_process:

there is an underlying true_x value, of which x is a random walk action based on a random sample from a gaussian distribution in unbounded logit space (log-odds), then converted to a probability value in [0,1] using the sigmoid function. 
informed traders see this value + a noise factor to not have a dominant edge in the market. 
    they trade towards it to simulate a more accurate estimate of the market. 
the market has its own price based on the orderbooks.
at the end, the final true_p value is rolled to resolve to 1/0.
We also include in this simulated version news events, scheduled and unscheduled using a Poisson process, where volatility increases temporarily and the true_p is scaled and the noise traders are more active.

Design decisions:
Logit space to stay within [0,1] probability space, avoids clipping which piles probability mass against boundaries, avoid asymmetric walk near boundary

Mode B simulation, from real data:



Strategy:

