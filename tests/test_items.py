from lulu_basket.snapshot import CAP_LOW_STOCK_COUNT, CAP_LOW_STOCK_NO_COUNT, Sku
from lulu_basket.solve.items import Item, build_items


def sku(product_id="p1", price_cents=2500, cap=None, cap_source=None, color="Black", size="4"):
    return Sku(
        product_id,
        f"Name {product_id} {color}",
        f"https://shop.lululemon.com/p/{product_id}/{color}",
        color,
        size,
        price_cents,
        cap,
        cap_source,
    )


def test_groups_by_product_and_price_keeping_skus_in_input_order():
    black = sku("p1", 2500, color="Black")
    navy = sku("p1", 2500, color="Navy", size="6")
    dearer = sku("p1", 3000)
    other = sku("p2", 2500)
    items = build_items([black, dearer, other, navy], 7500)
    assert items == [
        Item("p1", black.name, black.url, 2500, None, None, (black, navy)),
        Item("p1", dearer.name, dearer.url, 3000, None, None, (dearer,)),
        Item("p2", other.name, other.url, 2500, None, None, (other,)),
    ]


def test_drops_skus_priced_above_target():
    at_target = sku("p1", 7500)
    items = build_items([sku("p2", 7501), at_target], 7500)
    assert [(i.product_id, i.price_cents) for i in items] == [("p1", 7500)]


def test_sorted_by_product_then_price():
    skus = [sku("b", 1000), sku("a", 3000), sku("b", 900), sku("a", 1000), sku("ab", 100)]
    items = build_items(skus, 7500)
    assert [(i.product_id, i.price_cents) for i in items] == [
        ("a", 1000),
        ("a", 3000),
        ("ab", 100),
        ("b", 900),
        ("b", 1000),
    ]


def test_no_cap_if_any_sku_uncapped():
    skus = [sku(cap=2, cap_source=CAP_LOW_STOCK_COUNT), sku(color="Navy")]
    [item] = build_items(skus, 7500)
    assert (item.cap, item.cap_source) == (None, None)


def test_cap_is_max_sku_cap_with_its_source():
    [count_wins] = build_items(
        [
            sku(cap=1, cap_source=CAP_LOW_STOCK_NO_COUNT),
            sku(cap=3, cap_source=CAP_LOW_STOCK_COUNT, color="Navy"),
        ],
        7500,
    )
    [no_count_wins] = build_items(
        [
            sku(cap=4, cap_source=CAP_LOW_STOCK_NO_COUNT),
            sku(cap=2, cap_source=CAP_LOW_STOCK_COUNT, color="Navy"),
        ],
        7500,
    )
    assert (count_wins.cap, count_wins.cap_source) == (3, CAP_LOW_STOCK_COUNT)
    assert (no_count_wins.cap, no_count_wins.cap_source) == (4, CAP_LOW_STOCK_NO_COUNT)


def test_low_stock_count_wins_cap_ties():
    no_count = sku(cap=2, cap_source=CAP_LOW_STOCK_NO_COUNT)
    count = sku(cap=2, cap_source=CAP_LOW_STOCK_COUNT, color="Navy")
    for skus in ([no_count, count], [count, no_count]):
        [item] = build_items(skus, 7500)
        assert (item.cap, item.cap_source) == (2, CAP_LOW_STOCK_COUNT)


def test_no_skus_no_items():
    assert build_items([], 7500) == []
