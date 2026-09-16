import pytest
from src.orderbook.order import Order, OrderType, Side, TimeInForce
from src.orderbook.price_level import PriceLevel


def make_order(order_id, quantity=10):
    return Order(
        id=order_id,
        side=Side.BUY,
        price=40,
        quantity=quantity,
        type=OrderType.LIMIT,
        tif=TimeInForce.GTC,
    )


def ids(level):
    result = []
    for order in level:
        result.append(order.id)
    return result


def assert_bidirectional(level):
    """Forward and backward walks must be exact reverses, and count must agree.

    A remove() that updates only one of the two pointers passes ids() and fails
    here - which is the entire reason this helper exists.
    """
    forward = ids(level)

    backward = []
    node = level.tail
    while node is not None:
        backward.append(node.id)
        node = node.prev
    backward.reverse()

    assert forward == backward
    assert level.count == len(forward)

    if level.head is None:
        assert level.tail is None
    else:
        assert level.head.prev is None
        assert level.tail.next is None


@pytest.fixture
def level():
    # the post-yield check runs after every test in this file, so a pointer bug
    # surfaces at the test that caused it
    fresh = PriceLevel()
    yield fresh
    assert_bidirectional(fresh)


def test_empty_level(level):
    assert len(level) == 0
    assert level.front is None
    assert ids(level) == []


def test_append_preserves_arrival_order(level):
    for order_id in (1, 2, 3):
        level.append(make_order(order_id))

    assert ids(level) == [1, 2, 3]
    assert level.front.id == 1           # oldest fills first
    assert len(level) == 3


def test_remove_head(level):
    orders = []
    for order_id in (1, 2, 3):
        order = make_order(order_id)
        orders.append(order)
        level.append(order)

    level.remove(orders[0])

    assert ids(level) == [2, 3]
    assert level.front.id == 2


def test_remove_tail(level):
    orders = []
    for order_id in (1, 2, 3):
        order = make_order(order_id)
        orders.append(order)
        level.append(order)

    level.remove(orders[2])

    assert ids(level) == [1, 2]
    assert level.tail.id == 2


def test_remove_interior(level):
    # the case the deque did in O(n). removing from the middle is what a cancel
    # usually is, and it is the only case where BOTH pointer updates matter.
    orders = []
    for order_id in (1, 2, 3, 4, 5):
        order = make_order(order_id)
        orders.append(order)
        level.append(order)

    level.remove(orders[2])

    assert ids(level) == [1, 2, 4, 5]
    assert orders[1].next is orders[3]
    assert orders[3].prev is orders[1]


def test_remove_only_order_empties_level(level):
    order = make_order(1)
    level.append(order)

    level.remove(order)

    assert len(level) == 0
    assert level.head is None
    assert level.tail is None
    assert level.front is None


def test_remove_clears_the_orders_pointers(level):
    orders = []
    for order_id in (1, 2, 3):
        order = make_order(order_id)
        orders.append(order)
        level.append(order)

    level.remove(orders[1])

    # a removed order must not still point into the list, or a stale reference
    # could be spliced back in and duplicate it
    assert orders[1].prev is None
    assert orders[1].next is None


def test_remove_twice_raises(level):
    # deque.remove() raised on a missing element; intrusive removal has to
    # re-create that check or it corrupts the list instead of complaining
    order = make_order(1)
    other = make_order(2)
    level.append(order)
    level.append(other)

    level.remove(order)

    with pytest.raises(ValueError):
        level.remove(order)


def test_iteration_survives_removal_of_the_yielded_order(level):
    # _match's STP branch removes the order it is looking at. the walk must not
    # truncate when that happens, which is why __iter__ captures the successor
    # before it yields.
    orders = []
    for order_id in (1, 2, 3, 4):
        order = make_order(order_id)
        orders.append(order)
        level.append(order)

    visited = []
    for order in level:
        visited.append(order.id)
        level.remove(order)

    assert visited == [1, 2, 3, 4]
    assert len(level) == 0


def test_bidirectional_after_mixed_sequence(level):
    orders = {}
    for order_id in range(1, 9):
        order = make_order(order_id)
        orders[order_id] = order
        level.append(order)
        assert_bidirectional(level)

    for order_id in (4, 1, 8, 6, 2):
        level.remove(orders[order_id])
        assert_bidirectional(level)

    assert ids(level) == [3, 5, 7]

    level.append(make_order(9))
    assert ids(level) == [3, 5, 7, 9]
