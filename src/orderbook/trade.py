# create an immutable record history of a trade

from dataclasses import dataclass
from .order import Side


# basic dataclass syntax (already built when called with @):
# __repr__ shows the function name and parameters instead of the object memory address
# __eq__ compares the values of the fields instead of the object memory address
# __slots__ replaces auto-generated dict per instance saving memory with array of descriptors instead.
# can call __slots__ which gives ('price', 'quantity', ...), don't do for order.py
# importing a file executes it before caching

@dataclass(frozen=True, slots=True) 
class Trade:
    # one fill between a resting (maker) order and an incoming (taker) order

    price: int          # in ticks; ALWAYS the resting order's price
    quantity: int       # contracts filled on this execution

    #data for logging
    maker_id: int       # resting / passive order
    taker_id: int       # incoming / aggressive order
    seq: int            # book sequence number

    taker_side: Side   
    time: float | None = None       # sim clock, stamped by whoever has one
    # | or, default value None

    # run on generation
    def __post_init__(self) -> None:
        # frozen blocks assignment not reads so validating works here
        if self.price <= 0:
            raise ValueError(f"trade price must be positive, got {self.price}")
        if self.quantity <= 0:
            raise ValueError(f"trade quantity must be positive, got {self.quantity}")
        if self.maker_id == self.taker_id:
            raise ValueError(f"self-trade: order {self.maker_id} matched itself")

        

    @property
    def GetNotionalValue(self) -> int:
        # cash value of fill, ticks x contracts (cents)
        return self.price * self.quantity

