# one price level: a FIFO queue of resting orders, as an intrusive doubly-linked
# list so that cancelling an arbitrary order is O(1).
#
# why this replaced the deque: a deque is O(1) at both ends, which covers
# append-newest and take-oldest, but removal from the MIDDLE is O(n) - and that
# is exactly what a cancel does. in real flow most orders are cancelled rather
# than filled, so the middle is the common case, not the edge case.
#
# "intrusive" means the prev/next pointers live on the Order itself rather than
# in wrapper Node objects with a separate {id -> node} dict. that costs Order a
# little purity - it now knows it lives in a list - and buys one fewer
# allocation and one fewer dict entry per order. Order already carries `seq`
# stamped by the book, so it was never a pure data holder.
#
# the whole refactor is cheap because book.resting already maps id -> Order and
# Order already carries .side and .price, so a cancel finds both WHICH order and
# WHICH level in O(1). the only slow step left was the deque scanning itself to
# locate the element, and pointers remove that. this is the payoff from having
# dropped self.locations: no new index is needed, just two fields on Order.


class PriceLevel:
    """FIFO queue at one price. head = oldest = fills first, tail = newest."""

    # fixed shape and high cardinality, so slots pays here for the same reason
    # it pays on Trade.
    __slots__ = ("head", "tail", "count")

    def __init__(self) -> None:
        self.head = None
        self.tail = None
        self.count = 0

    @property
    def front(self):
        """The order that fills next, or None if the level is empty.

        Deliberately NOT __getitem__. `level.front` is honest about what is
        actually cheap; `level[3]` would invite someone to reintroduce an O(n)
        walk later without noticing they had.
        """
        return self.head

    def append(self, order) -> None:
        """Enqueue at the back. Newest last is what time priority means."""
        order.prev = self.tail
        order.next = None

        if self.tail is None:
            self.head = order
        else:
            self.tail.next = order

        self.tail = order
        self.count += 1

    def remove(self, order) -> None:
        """Splice out in O(1).

        The prev-side and next-side updates are independent, and getting only
        one of them right leaves FORWARD iteration perfectly intact while the
        backward chain silently rots. Every example test would still pass. That
        is why book.assert_invariants walks the list in both directions.
        """
        # deque.remove() raised ValueError on a missing element. intrusive
        # removal has no such protection - it would happily corrupt two lists -
        # so the check is re-created here.
        #
        # this catches the realistic bug, which is removing an order that was
        # already removed: both its pointers are None and it is not the head.
        # it does NOT catch passing an order that is interior to a DIFFERENT
        # level; book._remove locates the level from order.side and order.price,
        # so it always hands over the right one.
        if order is not self.head and order.prev is None:
            raise ValueError(
                f"order {order.id} is not resting in the level at {order.price}"
            )

        if order.prev is None:
            self.head = order.next
        else:
            order.prev.next = order.next

        if order.next is None:
            self.tail = order.prev
        else:
            order.next.prev = order.prev

        # clear the pointers so a stale Order reference cannot be spliced back
        # into a list and duplicate itself, and so the already-removed check
        # above keeps working.
        order.prev = None
        order.next = None
        self.count -= 1

    def __len__(self) -> int:
        return self.count

    def __iter__(self):
        """Walk front to back.

        A generator rather than a materialised list: size_at, depth and
        assert_invariants call this constantly, and allocating a list on every
        call would hand back the performance this refactor exists to win.
        """
        current = self.head
        while current is not None:
            # capture the successor BEFORE yielding. if the caller removes
            # `current` while iterating, remove() sets current.next to None and
            # reading it afterwards would truncate the walk.
            following = current.next
            yield current
            current = following
