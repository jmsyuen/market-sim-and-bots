
class OrderBook:
    def __init__(self):
        self.time = 0
        #self.bids = 
        #self.asks = 
        pass

    def _next_time_tick(self):
        self.time += 1
        return self.time

    # getters
    def best_bid(self):
        return

    def best_ask(self):
        return

    def get_midpoint(self):
        return 

    def get_spread(self):
        return
    # internal

    def _rest(self):
        # add to corresponding book side
        # book_side = 
        return

    def add_limit_order(self):
        return

    def cancel(self):
        #drop price key if no exhausted level
        #deque is o(n), upgrade to o(1) for doubly linked list per level

        return


    # optional for analysis later to plot depth of book
    def depth(self):
        return #price and quantity for each side