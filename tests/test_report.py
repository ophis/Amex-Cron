import pytest

from lulu_basket.snapshot import CAP_LOW_STOCK_COUNT, CAP_LOW_STOCK_NO_COUNT, Sku, Snapshot
from lulu_basket.solve.items import build_items
from lulu_basket.solve.knapsack import Combination
from lulu_basket.solve.report import format_usd, render

SCRAPED_AT = "2026-10-06T12:00:00Z"
URL = "https://shop.lululemon.com/p/align"


def sku(color="Black", size="4", cap=None, cap_source=None, product_id="p1", price_cents=2500,
        name='Align High-Rise Pant 25"', url=URL):
    return Sku(product_id, name, url, color, size, price_cents, cap, cap_source)


def item(*skus):
    (built,) = build_items(skus, 100_000)
    return built


def snapshot(*skus, target_cents=7500, scraped_at=SCRAPED_AT):
    return Snapshot(scraped_at, target_cents, tuple(skus))


def combo(total_cents, *picks):
    return Combination(total_cents, tuple(picks))


def test_format_usd():
    assert [format_usd(c) for c in (7500, 0, 5, 99, 123456)] == [
        "$75.00", "$0.00", "$0.05", "$0.99", "$1234.56"
    ]


def test_spec_example_layout_is_exact():
    capped = item(
        sku("Black", "4", 2, CAP_LOW_STOCK_COUNT),
        sku("Black", "6", 2, CAP_LOW_STOCK_COUNT),
        sku("True Navy", "2", 2, CAP_LOW_STOCK_COUNT),
    )
    out = render(snapshot(), 7500, [combo(5000, (capped, 2))])
    assert out == (
        "Target $75.00 · snapshot 2026-10-06T12:00:00Z\n"
        "\n"
        "#1  Total $50.00 ($25.00 below target)\n"
        '  2 × Align High-Rise Pant 25"  $25.00 each  [stock cap 2: low-stock count]\n'
        "      Black: 4, 6 · True Navy: 2\n"
        f"      {URL}\n"
    )


def test_header_uses_requested_target_not_snapshot_target():
    out = render(snapshot(target_cents=7500), 5000, [])
    assert out.splitlines()[0] == "Target $50.00 · snapshot 2026-10-06T12:00:00Z"


def test_combinations_are_numbered_with_gap_and_separated_by_a_blank_line():
    a = item(sku(product_id="a", price_cents=2500, name="Alpha"))
    b = item(sku(product_id="b", price_cents=3000, name="Beta"))
    out = render(
        snapshot(),
        7500,
        [combo(7500, (a, 3)), combo(7000, (a, 1), (b, 1)), combo(7499, (a, 1))],
    )
    lines = out.splitlines()
    assert lines[2] == "#1  Total $75.00 ($0.00 below target)"
    assert "#2  Total $70.00 ($5.00 below target)" in lines
    assert "#3  Total $74.99 ($0.01 below target)" in lines
    assert lines[lines.index("#2  Total $70.00 ($5.00 below target)") - 1] == ""
    assert lines[lines.index("#3  Total $74.99 ($0.01 below target)") - 1] == ""
    assert "  3 × Alpha  $25.00 each" in lines
    assert "  1 × Alpha  $25.00 each" in lines
    assert "  1 × Beta  $30.00 each" in lines


def test_every_pick_of_a_combination_is_listed_in_order():
    a = item(sku(product_id="a", name="Alpha", url="https://x/a"))
    b = item(sku(product_id="b", name="Beta", url="https://x/b", price_cents=3000))
    out = render(snapshot(), 7500, [combo(7000, (a, 2), (b, 1))])
    assert out.index("2 × Alpha") < out.index("https://x/a") < out.index("1 × Beta")
    assert out.index("1 × Beta") < out.index("https://x/b")


@pytest.mark.parametrize(
    ("source", "note"),
    [
        (CAP_LOW_STOCK_COUNT, "[stock cap 1: low-stock count]"),
        (CAP_LOW_STOCK_NO_COUNT, "[stock cap 1: low stock, no count]"),
    ],
)
def test_cap_one_item_bought_once_shows_cap_note(source, note):
    capped = item(sku(cap=1, cap_source=source))
    out = render(snapshot(), 7500, [combo(2500, (capped, 1))])
    assert f'  1 × Align High-Rise Pant 25"  $25.00 each  {note}\n' in out


def test_cap_note_absent_below_cap_or_without_cap():
    capped = item(sku(cap=3, cap_source=CAP_LOW_STOCK_COUNT))
    uncapped = item(sku(product_id="p2", name="Plain"))
    out = render(snapshot(), 7500, [combo(5000, (capped, 2)), combo(5000, (uncapped, 2))])
    assert "stock cap" not in out
    assert "  2 × Plain  $25.00 each\n" in out


def test_cap_note_shown_when_count_equals_cap_of_three():
    capped = item(sku(cap=3, cap_source=CAP_LOW_STOCK_NO_COUNT))
    out = render(snapshot(), 7500, [combo(7500, (capped, 3))])
    assert "$25.00 each  [stock cap 3: low stock, no count]\n" in out


def test_sizes_limited_to_skus_with_unlimited_or_sufficient_cap():
    capped = item(
        sku("Black", "2", 1, CAP_LOW_STOCK_NO_COUNT),
        sku("Black", "4", 2, CAP_LOW_STOCK_COUNT),
        sku("Navy", "6", 3, CAP_LOW_STOCK_COUNT),
        sku("Navy", "8", 1, CAP_LOW_STOCK_COUNT),
    )
    once = render(snapshot(), 7500, [combo(2500, (capped, 1))])
    twice = render(snapshot(), 7500, [combo(5000, (capped, 2))])
    assert "      Black: 2, 4 · Navy: 6, 8\n" in once
    assert "      Black: 4 · Navy: 6\n" in twice
    assert "      Navy: 6\n" in render(snapshot(), 7500, [combo(7500, (capped, 3))])


def test_uncapped_sku_stays_listed_for_any_count_and_capped_skus_drop_out():
    mixed = item(
        sku("Black", "2", None, None),
        sku("Black", "4", 1, CAP_LOW_STOCK_COUNT),
        sku("Navy", "6", 2, CAP_LOW_STOCK_COUNT),
    )
    out = render(snapshot(), 7500, [combo(7500, (mixed, 3))])
    assert "      Black: 2\n" in out
    assert "Navy" not in out


def test_colors_grouped_in_first_seen_order_with_sizes_in_input_order():
    grouped = item(
        sku("True Navy", "8"),
        sku("Black", "6"),
        sku("True Navy", "2"),
        sku("Black", "4"),
        sku("Red", "10"),
    )
    out = render(snapshot(), 7500, [combo(2500, (grouped, 1))])
    assert "      True Navy: 8, 2 · Black: 6, 4 · Red: 10\n" in out


def test_no_feasible_combination():
    assert render(snapshot(), 7500, []) == (
        "Target $75.00 · snapshot 2026-10-06T12:00:00Z\n"
        "\n"
        "No feasible combination.\n"
    )


def test_control_characters_removed_from_every_site_sourced_string():
    dirty = item(
        sku(
            color="Bl\x1b[0mack\x00",
            size="4\n",
            name="Align\r\n Pant\t\x07 25\x7f\x85",
            url="https://x/\x00p\x1f",
        )
    )
    snap = snapshot(scraped_at="2026-10-06\x0cT12:00:00Z\x1b")
    out = render(snap, 7500, [combo(2500, (dirty, 1))])
    assert out == (
        "Target $75.00 · snapshot 2026-10-06T12:00:00Z\n"
        "\n"
        "#1  Total $25.00 ($50.00 below target)\n"
        "  1 × Align Pant 25  $25.00 each\n"
        "      Bl[0mack: 4\n"
        "      https://x/p\n"
    )


def test_non_control_unicode_is_kept():
    fancy = item(sku(color="Noir™ é", size="XL·2", name="Wunder​Train 25”"))
    out = render(snapshot(), 7500, [combo(2500, (fancy, 1))])
    assert "Wunder​Train 25”" in out
    assert "      Noir™ é: XL·2\n" in out


def test_colors_that_differ_only_by_control_characters_share_one_group():
    both = item(sku("Black", "4"), sku("Bl\x00ack", "6"))
    out = render(snapshot(), 7500, [combo(2500, (both, 1))])
    assert "      Black: 4, 6\n" in out
