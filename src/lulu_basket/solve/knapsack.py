from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import islice
from math import gcd

from lulu_basket.errors import SolveError
from lulu_basket.solve.items import Item

MAX_STATES = 1_000_000


@dataclass(frozen=True)
class Combination:
    total_cents: int
    picks: tuple[tuple[Item, int], ...]


def top_combinations(
    items: Sequence[Item], target_cents: int, limit: int = 3
) -> list[Combination]:
    """Best combinations by total desc, unit count asc, then key asc.

    `items` must be sorted by (product_id, price_cents) with distinct keys, as build_items returns.
    """
    if not items:
        return []
    step = gcd(*(item.price_cents for item in items))
    units = target_cents // step
    prices = [item.price_cents // step for item in items]
    width = units // min(prices) + 1
    if (units + 1) * width > MAX_STATES:
        raise SolveError(
            f"search space too large (target {target_cents}, price step {step} cents)"
        )
    bounds = [
        units // price if item.cap is None else min(item.cap, units // price)
        for item, price in zip(items, prices)
    ]
    search = _Search(prices, bounds, units, width)
    return [
        Combination(total * step, tuple((items[i], n) for i, n in picks))
        for total, picks in islice(search.ordered(), limit)
    ]


class _Search:
    # A state (total, count) is bit total * width + count. Counts never spill into the next
    # row: count <= total // min price < width.
    def __init__(self, prices: list[int], bounds: list[int], units: int, width: int):
        self.prices = prices
        self.bounds = bounds
        self.width = width
        size = (units + 1) * width
        mask = (1 << size) - 1
        nbytes = (size + 7) // 8
        reach = 1
        # suffix[i]: states reachable with items i.. only, as bytes for O(1) bit tests
        # (shifting a big int to test one bit copies it).
        self.suffix = [b""] * len(prices) + [reach.to_bytes(nbytes, "little")]
        for i in reversed(range(len(prices))):
            shift = prices[i] * width + 1
            grown = reach
            for n in range(1, bounds[i] + 1):
                grown |= reach << n * shift
            reach = grown & mask
            self.suffix[i] = reach.to_bytes(nbytes, "little")
        self.reach = reach

    def ordered(self) -> Iterator[tuple[int, tuple[tuple[int, int], ...]]]:
        rows = self.reach
        while (total := (rows.bit_length() - 1) // self.width) > 0:
            row = rows >> total * self.width
            rows &= (1 << total * self.width) - 1
            for count in range(1, self.width):
                if row >> count & 1:
                    for picks in self._picks(total, count):
                        yield total, picks

    def _picks(self, total: int, count: int) -> Iterator[tuple[tuple[int, int], ...]]:
        path: list[tuple[int, int]] = []
        frames = [self._steps(0, total, count)]
        while frames:
            step = next(frames[-1], None)
            if step is None:
                frames.pop()
                if path:
                    path.pop()
                continue
            i, n, rest_total, rest_count = step
            path.append((i, n))
            if rest_total == 0:
                yield tuple(path)
                path.pop()
            else:
                frames.append(self._steps(i + 1, rest_total, rest_count))

    def _steps(self, start: int, total: int, count: int) -> Iterator[tuple[int, int, int, int]]:
        for i in range(start, len(self.prices)):
            if not self._has(i, total, count):
                return
            price = self.prices[i]
            for n in range(1, min(self.bounds[i], count, total // price) + 1):
                if self._has(i + 1, total - n * price, count - n):
                    yield i, n, total - n * price, count - n

    def _has(self, i: int, total: int, count: int) -> bool:
        bit = total * self.width + count
        return bool(self.suffix[i][bit >> 3] >> (bit & 7) & 1)
