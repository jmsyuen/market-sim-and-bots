market sim and bot

# description
composition




# design decisions

price-time priority - best price then earliest order fills
price level - 2dp but in system as integers / 100 not floats
time level priority - using a global monotonic sequence number assigned at receival not timestamp (price, seq)
make order quantity mutable, reduce as you fill the order, but keep records for logs
partial fills left as resting

book is uncrossable when idle
also design a visualiser with best price


explain enums, why not just bools 
explain dataclasses python, why not use sql and is it more convenient, does it just hold data records in a python file
explain the mapping concept
explain resting orders
explain why we are separating python files like order and trade, will they contain methods later
quick refresh on limit order, market order
explain how we upgrade to o(1) for the cancel function with double linked list

give me the most important information a typical quant trader has to trade with, can they typically access the whole order book and see for example the price and volume at each level.


what can i add to this project to make it impressive and stand out on my cv, to increase my chances of impressing a top quant firm for a trader role?

project for quant prep



program an application replicating a trading simulator of a market eg representing oil market, displaying order book and price levels much like one at a quant firm would use to test its interns, with news updates and other bot traders with the price displayed matching incoming trades. allow the user to place trades that will influence the price, for now no limit on direction or inventory. include varieties of bots, but mostly the competent ones trade around a fair value estimate, of which they narrow down over time using the news updates, starting very vague.
in this mode for now there is one 'true' value that is resolved at the end of the trading session lets say 5 mins, in later modes this true value will be moving like a real market but slower.


later show hints where i should trade and why, explaining the techniques and reasoning behind the trade. 



can we trade pair volatility spread of any two instruments in the dataset?