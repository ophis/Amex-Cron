import itertools
import random
import time

import pytest

from lulu_basket.errors import SolveError
from lulu_basket.snapshot import CAP_LOW_STOCK_COUNT, Sku
from lulu_basket.solve.items import Item, build_items
from lulu_basket.solve.knapsack import Combination, top_combinations


def item(product_id, price_cents, cap=None):
    return Item(
        product_id,
        f"Name {product_id}",
        f"https://shop.lululemon.com/p/{product_id}",
        price_cents,
        cap,
        None if cap is None else CAP_LOW_STOCK_COUNT,
        (),
    )


def summary(combos):
    return [
        (c.total_cents, tuple((it.product_id, it.price_cents, n) for it, n in c.picks))
        for c in combos
    ]


def test_prd_example():
    a, b = item("A", 2500), item("B", 3000)
    assert top_combinations([a, b], 7500) == [
        Combination(7500, ((a, 3),)),
        Combination(6000, ((b, 2),)),
        Combination(5500, ((a, 1), (b, 1))),
    ]


def test_prd_example_with_cap():
    a, b = item("A", 2500, cap=2), item("B", 3000)
    assert top_combinations([a, b], 7500) == [
        Combination(6000, ((b, 2),)),
        Combination(5500, ((a, 1), (b, 1))),
        Combination(5000, ((a, 2),)),
    ]


def test_no_feasible_combination():
    assert top_combinations([item("A", 8000)], 7500) == []
    assert top_combinations([], 7500) == []


def test_fewer_than_limit_returns_all():
    assert summary(top_combinations([item("A", 3000)], 7500)) == [
        (6000, (("A", 3000, 2),)),
        (3000, (("A", 3000, 1),)),
    ]


def test_caps_respected():
    assert summary(top_combinations([item("A", 1000, cap=2)], 7500)) == [
        (2000, (("A", 1000, 2),)),
        (1000, (("A", 1000, 1),)),
    ]


def test_equal_totals_fewer_units_first():
    assert summary(top_combinations([item("A", 1000), item("B", 2000)], 2000)) == [
        (2000, (("B", 2000, 1),)),
        (2000, (("A", 1000, 2),)),
        (1000, (("A", 1000, 1),)),
    ]


def test_equal_totals_and_counts_order_by_product_then_price():
    items = [item("A", 1000), item("A", 2000), item("B", 1000), item("B", 2000)]
    assert summary(top_combinations(items, 3000, limit=4)) == [
        (3000, (("A", 1000, 1), ("A", 2000, 1))),
        (3000, (("A", 1000, 1), ("B", 2000, 1))),
        (3000, (("A", 2000, 1), ("B", 1000, 1))),
        (3000, (("B", 1000, 1), ("B", 2000, 1))),
    ]


def test_equal_totals_and_counts_order_by_count_within_item():
    items = [item("A", 1000), item("B", 1000), item("C", 1000)]
    assert summary(top_combinations(items, 2000)) == [
        (2000, (("A", 1000, 1), ("B", 1000, 1))),
        (2000, (("A", 1000, 1), ("C", 1000, 1))),
        (2000, (("A", 1000, 2),)),
    ]


def brute_force(items, target, limit):
    bounds = [
        target // it.price_cents if it.cap is None else min(it.cap, target // it.price_cents)
        for it in items
    ]
    found = []
    for counts in itertools.product(*(range(b + 1) for b in bounds)):
        total = sum(it.price_cents * n for it, n in zip(items, counts))
        if total == 0 or total > target:
            continue
        picks = tuple((it, n) for it, n in zip(items, counts) if n > 0)
        key = tuple((it.product_id, it.price_cents, n) for it, n in picks)
        found.append(((-total, sum(counts), key), Combination(total, picks)))
    found.sort(key=lambda entry: entry[0])
    return [combo for _, combo in found[:limit]]


PRICE_POOLS = (range(100, 4001), range(100, 4001, 100), range(500, 4001, 500))


def random_instance(rng):
    pool = rng.choice(PRICE_POOLS)
    size = rng.randint(2, 6)
    keys = set()
    while len(keys) < size:
        keys.add((rng.choice("abc"), rng.choice(pool)))
    items = [item(pid, price, cap=rng.choice([None, 1, 2, 3])) for pid, price in sorted(keys)]
    return items, rng.randint(1000, 7500)


@pytest.mark.parametrize("seed", range(200))
def test_matches_brute_force(seed):
    items, target = random_instance(random.Random(seed))
    assert top_combinations(items, target) == brute_force(items, target, 3)


def test_search_space_guard():
    with pytest.raises(SolveError) as exc:
        top_combinations([item("A", 2), item("B", 4)], 7500)
    assert str(exc.value) == "search space too large (target 7500, price step 2 cents)"


def test_search_space_guard_boundary():
    single = [item("A", 1, cap=1)]
    assert summary(top_combinations(single, 999)) == [(1, (("A", 1, 1),))]
    with pytest.raises(SolveError) as exc:
        top_combinations(single, 1000)
    assert str(exc.value) == "search space too large (target 1000, price step 1 cents)"


def test_nfr1_500_items_within_100ms():
    rng = random.Random(1)
    skus = []
    for i in range(500):
        cap = rng.randint(1, 3) if rng.random() < 0.2 else None
        skus.append(
            Sku(
                f"p{i:03d}",
                f"Item {i}",
                f"https://shop.lululemon.com/p/item-{i}/p{i:03d}",
                "Black",
                "M",
                rng.randint(5, 75) * 100,
                cap,
                None if cap is None else CAP_LOW_STOCK_COUNT,
            )
        )
    timings = []
    for _ in range(3):
        start = time.perf_counter()
        combos = top_combinations(build_items(skus, 7500), 7500)
        timings.append(time.perf_counter() - start)
    assert len(combos) == 3
    assert min(timings) < 0.1
