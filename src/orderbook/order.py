# submit order instruction

from dataclasses import dataclass, field
from enum import Enum # enums are like variables with defined possible values


# never accept a raw int or string for these params - convert at the boundary when accepting new data; eg. importing Polymarket data later convert "side": "buy" with Side(row["side"].upper())
class Side(Enum):
    # treat Side as a var which only takes these two distinct values: BUY/SELL 
    BUY = 1
    SELL = 2

    @property # turns a method into an attribute, so call without () like Side.opposite, runs everytime accessed as doesn't exist until called
    def opposite(self) -> "Side":
        # used by book.py to pick side to match against, and by Trade.maker_side
        if self is Side.BUY:
            return Side.SELL
        else:
            return Side.BUY

class OrderType(Enum):
    LIMIT = 1       # fill on this price only, never worse, allows partial fills
    MARKET = 2      # take any price; price is None


class TimeInForce(Enum):
    GTC = 1         # good till cancelled - rest in the book until filled or pulled
    IOC = 2         # immediate or cancel - fill what you can now, discard the rest
    FOK = 3         # fill or kill - fill everything or nothing


@dataclass(kw_only=True)
class Order:
    # one instruction, construct with keywords: Order(id=1, side=Side.BUY, ...)

    id: int                                 # unique; the BOOK enforces uniqueness
    side: Side
    quantity: int                           # original size - never changes
    price: int | None = None                # ticks (cents); None for MARKET
    type: OrderType = OrderType.LIMIT
    tif: TimeInForce = TimeInForce.GTC
    trader_id: int | None = None

    remaining: int = field(init=False)      # derived, then mutated by fill()
    seq: int = field(init=False, default=0)  # time priority - assigned by the book

    def __post_init__(self) -> None:
        # validate - reject nonsense at construction, not mid-match:
        self.remaining = self.quantity

        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive, got {self.quantity}")

        # LIMIT -> price is not None and price > 0
        if self.type is OrderType.LIMIT and (self.price is None or self.price <= 0): 
            raise ValueError(f"limit order price must be positive, got {self.price}")
        
        # MARKET -> price is None (a market order has no limit)
        if self.type is OrderType.MARKET and self.price is not None:
            raise ValueError(f"market order price must be None, got {self.price}")

        # MARKET + GTC is contradictory (nothing to rest) - force IOC or raise
        if self.type is OrderType.MARKET and self.tif is TimeInForce.GTC:
            raise ValueError(f"market order cannot be GTC, got {self.tif}")

        # enforce int price 
        if self.price is not None and not isinstance(self.price, int):
            raise TypeError(f"price must be an integer tick, got {type(self.price).__name__}")
        


    @property
    def is_filled(self) -> bool:
        return self.remaining == 0

    @property
    def filled_quantity(self) -> int:
        # feeds the fill-rate metric later
        return self.quantity - self.remaining

    def fill(self, quantity: int) -> None:
        # don't oversell an order or drive remaining negative - the invariant lives in one place.
        # only place remaining should change

        if quantity <= 0 or quantity > self.remaining:
            raise ValueError(f"fill quantity must be positive and <= remaining, got {quantity} for order {self.id}")
        self.remaining -= quantity

