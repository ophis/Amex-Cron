import re
from datetime import UTC, datetime

import pytest

from lulu_basket.errors import ScrapeError
from lulu_basket.scrape.fetch import Fetcher
from lulu_basket.scrape.parse import BASE_URL
from lulu_basket.scrape.scrape import CATEGORIES, scrape
from lulu_basket.snapshot import CAP_LOW_STOCK_COUNT, CAP_LOW_STOCK_NO_COUNT, Sku

TARGET = 7500
WOMEN = "/c/women-clothes/n14uwk"
MEN = "/c/men-clothes/n1oxc7"
ACCESSORIES = "/c/accessories/n1dslk"
ABSENT = object()
TRIM_MARKER = re.compile(r"<\d+ more \w+ trimmed>")


def sku(**overrides):
    entry = {
        "size": "4",
        "inseam": None,
        "color": {"name": "Black"},
        "available": True,
        "isFinalSale": False,
        "isLowStock": False,
        "lowStockMessage": None,
        "price": {"listPrice": "50", "salePrice": None},
    }
    entry.update(overrides)
    return {key: value for key, value in entry.items() if value is not ABSENT}


def url_of(product):
    return BASE_URL + product["attributes"]["url"]


def run(site, target=TARGET, delay=0, sleeps=None, logs=None):
    logs = [] if logs is None else logs
    sleep = (lambda seconds: None) if sleeps is None else sleeps.append
    snapshot = scrape(target, Fetcher(site.http_get, sleep, delay), logs.append)
    return snapshot, logs


def shop(site, skus, product_id="p1", name="Define Jacket"):
    """One product with the given SKUs on the women category."""
    product = site.product(product_id, name)
    site.add_category(WOMEN, [[product]])
    site.add_product(product, skus)
    return product


def error_of(site, **kwargs):
    with pytest.raises(ScrapeError) as exc:
        run(site, **kwargs)
    return str(exc.value)


def drop_trim_markers(value):
    if isinstance(value, list):
        return [drop_trim_markers(v) for v in value if not _is_marker(v)]
    if isinstance(value, dict):
        return {k: drop_trim_markers(v) for k, v in value.items()}
    return value


def _is_marker(value):
    return isinstance(value, str) and TRIM_MARKER.fullmatch(value) is not None


def test_categories():
    assert CATEGORIES == (
        ("women-clothes", WOMEN),
        ("men-clothes", MEN),
        ("accessories", ACCESSORIES),
    )


# crawl


def test_pagination_follows_next_links_until_absent(fake_site):
    first, second, third = (fake_site.product(f"p{i}") for i in (1, 2, 3))
    fake_site.add_category(WOMEN, [[first], [second], [third]])
    for product in (first, second, third):
        fake_site.add_product(product, [sku()])
    snapshot, _ = run(fake_site)
    women = BASE_URL + WOMEN
    assert fake_site.requests == [
        women,
        f"{women}?page=2",
        f"{women}?page=3",
        BASE_URL + MEN,
        BASE_URL + ACCESSORIES,
        url_of(first),
        url_of(second),
        url_of(third),
    ]
    assert [s.product_id for s in snapshot.skus] == ["p1", "p2", "p3"]


@pytest.mark.parametrize(
    "total_count, pages, allowed",
    [(40, 3, True), (40, 4, False), (41, 4, True), (41, 5, False)],
)
def test_pagination_limit_is_ceil_total_over_40_plus_2(fake_site, total_count, pages, allowed):
    product = fake_site.product("p1")
    fake_site.add_category(
        WOMEN, [[] for _ in range(pages - 1)] + [[product]], total_count=total_count
    )
    fake_site.add_product(product, [sku()])
    if allowed:
        snapshot, _ = run(fake_site)
        assert [s.product_id for s in snapshot.skus] == ["p1"]
        return
    limit = -(-total_count // 40) + 2
    refused = f"{BASE_URL}{WOMEN}?page={limit + 1}"
    assert error_of(fake_site) == f"pagination did not terminate: {refused}"
    assert refused not in fake_site.requests


@pytest.mark.parametrize(
    "total_count, pages, ended_early",
    [(80, 1, False), (81, 1, True), (120, 2, False), (121, 2, True), (1130, 1, True)],
)
def test_pagination_stopping_short_of_total_count_fails(fake_site, total_count, pages, ended_early):
    product = fake_site.product("p1")
    fake_site.add_category(
        WOMEN, [[] for _ in range(pages - 1)] + [[product]], total_count=total_count
    )
    fake_site.add_product(product, [sku()])
    if not ended_early:
        snapshot, _ = run(fake_site)
        assert [s.product_id for s in snapshot.skus] == ["p1"]
        return
    last = BASE_URL + WOMEN + ("" if pages == 1 else f"?page={pages}")
    assert error_of(fake_site) == f"pagination ended early: {last}"
    assert BASE_URL + MEN not in fake_site.requests


def test_missing_continuation_page_fails_the_scrape(fake_site):
    fake_site.add_category(WOMEN, [[fake_site.product("p1")], [fake_site.product("p2")]])
    del fake_site.responses[f"{BASE_URL}{WOMEN}?page=2"]
    assert error_of(fake_site) == f"request failed: HTTP 404: {BASE_URL}{WOMEN}?page=2"


def test_zero_products_fails(fake_site):
    assert error_of(fake_site) == "no products found on category pages"


def test_duplicate_products_keep_the_first_seen_and_are_fetched_once(fake_site):
    first = fake_site.product("p1", name="First")
    again = fake_site.product("p1", name="Second")
    other = fake_site.product("p2")
    fake_site.add_category(WOMEN, [[first, other], [again]])
    fake_site.add_category(ACCESSORIES, [[again]])
    fake_site.add_product(first, [sku()])
    fake_site.add_product(other, [sku()])
    snapshot, logs = run(fake_site)
    assert fake_site.requests.count(url_of(first)) == 1
    assert [(s.product_id, s.name) for s in snapshot.skus] == [("p1", "First"), ("p2", "Product")]
    assert "products found 2, product pages fetched 2, SKUs kept 2" in logs


def test_products_are_taken_in_category_then_first_seen_order(fake_site):
    women, men, accessory = (fake_site.product(i) for i in ("w", "m", "a"))
    fake_site.add_category(WOMEN, [[women]])
    fake_site.add_category(MEN, [[men]])
    fake_site.add_category(ACCESSORIES, [[accessory]])
    for product in (women, men, accessory):
        fake_site.add_product(product, [sku()])
    snapshot, _ = run(fake_site)
    assert [s.product_id for s in snapshot.skus] == ["w", "m", "a"]
    assert fake_site.requests[3:] == [url_of(women), url_of(men), url_of(accessory)]


def test_prefilter_fetches_only_products_with_an_available_color_within_target(fake_site):
    kept = fake_site.product("kept", colors=[(60, True)])
    at_target = fake_site.product("at_target", colors=[(75, True)])
    over = fake_site.product("over", colors=[(80, True)])
    cheap_but_unavailable = fake_site.product("cheap_unavailable", colors=[(50, False), (90, True)])
    none_available = fake_site.product("none_available", colors=[(10, False)])
    fake_site.add_category(
        WOMEN, [[over, kept], [cheap_but_unavailable, at_target, none_available]]
    )
    fake_site.add_product(kept, [sku()])
    fake_site.add_product(at_target, [sku()])
    snapshot, _ = run(fake_site)
    assert fake_site.requests[-2:] == [url_of(kept), url_of(at_target)]
    assert len(fake_site.requests) == 3 + 1 + 2
    assert [s.product_id for s in snapshot.skus] == ["kept", "at_target"]


def test_every_request_goes_through_the_fetcher(fake_site):
    shop(fake_site, [sku()])
    sleeps = []
    run(fake_site, delay=7, sleeps=sleeps)
    assert sleeps == [7] * (len(fake_site.requests) - 1)


def test_missing_product_page_fails_the_scrape(fake_site):
    product = fake_site.product("p1")
    fake_site.add_category(WOMEN, [[product]])
    assert error_of(fake_site) == f"request failed: HTTP 404: {url_of(product)}"


# classification


def test_classification_order_and_counts(fake_site):
    over = {"listPrice": "80", "salePrice": None}
    skus = [
        sku(available=ABSENT),
        sku(available=False, isFinalSale=ABSENT),
        sku(isFinalSale="yes"),
        sku(available=False, isFinalSale=True, color=ABSENT, size=ABSENT, price=ABSENT),
        sku(available=False),
        sku(isFinalSale=True, price=over),
        sku(price=over),
        sku(price=over, lowStockMessage="0 left"),
        sku(color={"name": "Kept"}),
    ]
    shop(fake_site, skus)
    snapshot, logs = run(fake_site)
    assert [s.color for s in snapshot.skus] == ["Kept"]
    assert "excluded SKUs: final sale 1, unavailable 2, missing flag 3, over target 2" in logs


def test_excluded_counters_are_listed_when_zero(fake_site):
    shop(fake_site, [sku()])
    _, logs = run(fake_site)
    assert "excluded SKUs: final sale 0, unavailable 0, missing flag 0, over target 0" in logs


def test_price_uses_sale_price_when_set_else_list_price(fake_site):
    shop(
        fake_site,
        [
            sku(color={"name": "Sale"}, price={"listPrice": "108", "salePrice": "40.5"}),
            sku(color={"name": "List"}, price={"listPrice": "50", "salePrice": None}),
            sku(color={"name": "Over"}, price={"listPrice": "50", "salePrice": "76"}),
        ],
    )
    snapshot, _ = run(fake_site)
    assert [(s.color, s.price_cents) for s in snapshot.skus] == [("Sale", 4050), ("List", 5000)]


def test_price_at_target_is_kept(fake_site):
    shop(fake_site, [sku(price={"listPrice": "75", "salePrice": None})])
    snapshot, _ = run(fake_site)
    assert [s.price_cents for s in snapshot.skus] == [7500]


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({}, "4"),
        ({"inseam": '28"'}, '4 / 28"'),
        ({"inseam": ABSENT}, "4"),
        ({"size": "ONE SIZE"}, "ONE SIZE"),
    ],
)
def test_size_includes_inseam_when_present(fake_site, overrides, expected):
    shop(fake_site, [sku(**overrides)])
    snapshot, _ = run(fake_site)
    assert snapshot.skus[0].size == expected


# caps


@pytest.mark.parametrize(
    "message, low_stock, cap, source",
    [
        ("Only 2 left", True, 2, CAP_LOW_STOCK_COUNT),
        ("Only 2 left", None, 2, CAP_LOW_STOCK_COUNT),
        ("Only 12 left in stock, 3 in carts", False, 12, CAP_LOW_STOCK_COUNT),
        (None, True, 1, CAP_LOW_STOCK_NO_COUNT),
        ("Low stock", True, 1, CAP_LOW_STOCK_NO_COUNT),
        (None, False, None, None),
        (None, None, None, None),
        ("Low stock", False, None, None),
    ],
)
def test_caps(fake_site, message, low_stock, cap, source):
    shop(fake_site, [sku(lowStockMessage=message, isLowStock=low_stock)])
    snapshot, _ = run(fake_site)
    assert [(s.cap, s.cap_source) for s in snapshot.skus] == [(cap, source)]


def test_sku_with_zero_left_is_excluded_as_unavailable(fake_site):
    shop(
        fake_site,
        [
            sku(color={"name": "Gone"}, lowStockMessage="0 left", isLowStock=True),
            sku(color={"name": "Here"}),
        ],
    )
    snapshot, logs = run(fake_site)
    assert [s.color for s in snapshot.skus] == ["Here"]
    assert "excluded SKUs: final sale 0, unavailable 1, missing flag 0, over target 0" in logs


def test_one_aggregated_warning_for_low_stock_skus_without_count(fake_site):
    shop(
        fake_site,
        [
            sku(isLowStock=True),
            sku(isLowStock=True, color={"name": "Navy"}),
            sku(isLowStock=True, lowStockMessage="Only 2 left", color={"name": "Red"}),
        ],
    )
    _, logs = run(fake_site)
    warnings = [line for line in logs if line.startswith("warning:")]
    assert warnings == ["warning: 2 low-stock SKUs have no count in lowStockMessage; capped at 1"]


def test_no_warning_without_uncounted_low_stock_skus(fake_site):
    shop(fake_site, [sku(lowStockMessage="Only 2 left", isLowStock=True), sku(isLowStock=None)])
    _, logs = run(fake_site)
    assert not [line for line in logs if line.startswith("warning:")]


# validation of kept SKUs


@pytest.mark.parametrize(
    "overrides, path",
    [
        ({"color": ABSENT}, "color.name"),
        ({"color": {}}, "color.name"),
        ({"color": {"name": ""}}, "color.name"),
        ({"color": {"name": 7}}, "color.name"),
        ({"color": "Black"}, "color.name"),
        ({"size": ABSENT}, "size"),
        ({"size": ""}, "size"),
        ({"size": 4}, "size"),
    ],
)
def test_kept_sku_missing_color_or_size_fails(fake_site, overrides, path):
    product = shop(fake_site, [sku(available=False), sku(**overrides)])
    assert error_of(fake_site) == (
        f"missing field skus[1].{path}: product p1 on {url_of(product)}"
    )


@pytest.mark.parametrize("inseam", ["", 28, False, ['28"']])
def test_kept_sku_with_malformed_inseam_fails(fake_site, inseam):
    product = shop(fake_site, [sku(available=False), sku(inseam=inseam)])
    assert error_of(fake_site) == f"missing field skus[1].inseam: product p1 on {url_of(product)}"


@pytest.mark.parametrize("price", [ABSENT, None, "50", 50, ["50"]])
def test_kept_sku_with_non_dict_price_fails(fake_site, price):
    product = shop(fake_site, [sku(price=price)])
    assert error_of(fake_site) == f"missing field skus[0].price: product p1 on {url_of(product)}"


def test_final_sale_sku_without_a_color_is_excluded_not_rejected(fake_site):
    shop(fake_site, [sku(isFinalSale=True, color=ABSENT), sku(color={"name": "Kept"})])
    snapshot, logs = run(fake_site)
    assert [s.color for s in snapshot.skus] == ["Kept"]
    assert "excluded SKUs: final sale 1, unavailable 0, missing flag 0, over target 0" in logs


def test_color_is_validated_before_the_price_comparison(fake_site):
    product = shop(fake_site, [sku(color=ABSENT, price={"listPrice": "80", "salePrice": None})])
    assert error_of(fake_site) == (
        f"missing field skus[0].color.name: product p1 on {url_of(product)}"
    )


@pytest.mark.parametrize(
    "price, shown",
    [
        ({"listPrice": "12.345", "salePrice": None}, "'12.345'"),
        ({"listPrice": "0", "salePrice": None}, "'0'"),
        ({"listPrice": "50", "salePrice": "free"}, "'free'"),
        ({"listPrice": None, "salePrice": None}, "None"),
        ({}, "None"),
    ],
)
def test_kept_sku_with_bad_price_fails(fake_site, price, shown):
    product = shop(fake_site, [sku(price=price)])
    assert error_of(fake_site) == (
        f"unparseable price {shown}: product p1 skus[0] on {url_of(product)}"
    )


def test_non_dict_sku_entry_fails(fake_site):
    product = shop(fake_site, [sku(), "<1 more skus trimmed>"])
    assert error_of(fake_site) == f"missing field skus[1]: product p1 on {url_of(product)}"


def test_no_eligible_skus_fails(fake_site):
    shop(fake_site, [sku(available=False), sku(isFinalSale=True), sku(isFinalSale=ABSENT)])
    assert error_of(fake_site) == "no eligible SKUs after filtering"


def test_no_eligible_skus_when_every_product_is_prefiltered(fake_site):
    fake_site.add_category(WOMEN, [[fake_site.product("p1", colors=[(80, True)])]])
    assert error_of(fake_site) == "no eligible SKUs after filtering"


def test_no_eligible_skus_logs_the_exclusion_counts_before_failing(fake_site):
    shop(fake_site, [sku(available=False), sku(isFinalSale=True), sku(isFinalSale=ABSENT)])
    logs = []
    assert error_of(fake_site, logs=logs) == "no eligible SKUs after filtering"
    assert logs[-1] == "excluded SKUs: final sale 1, unavailable 1, missing flag 1, over target 0"


def test_products_without_skus_contribute_nothing(fake_site):
    empty = fake_site.product("empty")
    full = fake_site.product("full")
    fake_site.add_category(WOMEN, [[empty, full]])
    fake_site.add_product(empty, [])
    fake_site.add_product(full, [sku()])
    snapshot, _ = run(fake_site)
    assert [s.product_id for s in snapshot.skus] == ["full"]


# snapshot and log


def test_snapshot_header(fake_site):
    shop(fake_site, [sku()])
    before = datetime.now(UTC).replace(microsecond=0)
    snapshot, _ = run(fake_site, target=6000)
    after = datetime.now(UTC)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", snapshot.scraped_at)
    stamp = datetime.strptime(snapshot.scraped_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert before <= stamp <= after
    assert snapshot.target_cents == 6000
    assert isinstance(snapshot.skus, tuple)


def test_sku_record_has_every_field(fake_site):
    product = shop(
        fake_site,
        [sku(inseam='28"', lowStockMessage="Only 2 left", isLowStock=True)],
        name="Align Pant",
    )
    snapshot, _ = run(fake_site)
    assert snapshot.skus == (
        Sku(
            product_id="p1",
            name="Align Pant",
            url=url_of(product),
            color="Black",
            size='4 / 28"',
            price_cents=5000,
            cap=2,
            cap_source=CAP_LOW_STOCK_COUNT,
        ),
    )


def test_log_lines(fake_site):
    first, second = fake_site.product("p1"), fake_site.product("p2")
    fake_site.add_category(WOMEN, [[first], [second]])
    fake_site.add_product(first, [sku(), sku(available=False), sku(isLowStock=True)])
    fake_site.add_product(second, [sku(isFinalSale=True)])
    _, logs = run(fake_site)
    assert logs == [
        "women-clothes page 1/2: 1 listed",
        "women-clothes page 2/2: 1 listed",
        "men-clothes page 1/1: 0 listed",
        "accessories page 1/1: 0 listed",
        "product pages 2/2",
        "products found 2, product pages fetched 2, SKUs kept 2",
        "excluded SKUs: final sale 1, unavailable 1, missing flag 0, over target 0",
        "warning: 1 low-stock SKUs have no count in lowStockMessage; capped at 1",
    ]


@pytest.mark.parametrize(
    "count, expected",
    [
        (1, ["1/1"]),
        (25, ["25/25"]),
        (26, ["25/26", "26/26"]),
        (50, ["25/50", "50/50"]),
        (51, ["25/51", "50/51", "51/51"]),
    ],
)
def test_product_page_progress_every_25_and_at_the_end(fake_site, count, expected):
    products = [fake_site.product(f"p{i}") for i in range(count)]
    fake_site.add_category(WOMEN, [products])
    for product in products:
        fake_site.add_product(product, [sku()])
    _, logs = run(fake_site)
    assert [line for line in logs if line.startswith("product pages")] == [
        f"product pages {progress}" for progress in expected
    ]


# real samples


def test_crawl_of_real_samples(fake_site, load_fixture):
    category = drop_trim_markers(load_fixture("category.json"))
    page = next(
        query
        for query in category["props"]["pageProps"]["dehydratedState"]["queries"]
        if query["queryKey"][0] == "catalogPageData"
    )["state"]["data"]["pages"][0]
    del page["data"]["relationships"]["products"]["links"]["next"]
    page["data"]["attributes"]["totalCount"] = 3
    fake_site.add_page(BASE_URL + WOMEN, category)

    def product_page(fixture, product_id):
        data = drop_trim_markers(load_fixture(fixture))
        for query in data["props"]["pageProps"]["dehydratedState"]["queries"]:
            if query["queryKey"][0] == "pdp" and isinstance(query["state"], dict):
                query["queryKey"][1] = product_id
        return data

    jacket = f"{BASE_URL}/p/define-jacket-nulu/hnsjuvo8dn"
    hoodie = f"{BASE_URL}/p/scuba-evolve-oversized-half-zip-hoodie/lp4yqrz3sp"
    jogger = f"{BASE_URL}/p/dance-studio-jogger-29/o2dx4njotf"
    fake_site.add_page(jacket, product_page("product_define_jacket.json", "hnsjuvo8dn"))
    fake_site.add_page(hoodie, product_page("product_align_pant.json", "lp4yqrz3sp"))
    fake_site.add_page(jogger, product_page("product_crossbody_bag.json", "o2dx4njotf"))

    snapshot, logs = run(fake_site, target=15000)

    jacket_name = "Define Jacket *Nulu"
    hoodie_name = "Scuba Evolve Oversized Half-Zip Hoodie"
    jogger_name = "Dance Studio Mid-Rise Jogger *Full Length"
    navy = "True Navy/Mirror Silver/Mirror Silver"
    beach = "Beach Ball Blue/Silver"
    one_size = "ONE SIZE"
    assert snapshot.skus == (
        Sku("hnsjuvo8dn", jacket_name, jacket, "Black", "0", 12800, 1, CAP_LOW_STOCK_NO_COUNT),
        Sku("hnsjuvo8dn", jacket_name, jacket, navy, "14", 12800, None, None),
        Sku(
            "lp4yqrz3sp", hoodie_name, hoodie, "Phantom Camo Black Multi", '2 / 28"', 10800,
            1, CAP_LOW_STOCK_NO_COUNT,
        ),
        Sku("lp4yqrz3sp", hoodie_name, hoodie, "Pink Pearl", '10 / 28"', 10800, None, None),
        Sku("o2dx4njotf", jogger_name, jogger, beach, one_size, 7800, None, None),
        Sku("o2dx4njotf", jogger_name, jogger, "Light Ivory/Gold", one_size, 7800, None, None),
        Sku("o2dx4njotf", jogger_name, jogger, "Black/Gold", one_size, 7800, None, None),
    )
    assert "excluded SKUs: final sale 6, unavailable 5, missing flag 0, over target 0" in logs
    assert "warning: 2 low-stock SKUs have no count in lowStockMessage; capped at 1" in logs
