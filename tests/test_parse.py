import pytest

from lulu_basket.errors import ScrapeError
from lulu_basket.scrape.parse import (
    BASE_URL,
    CategoryPage,
    CategoryProduct,
    extract_next_data,
    parse_category_page,
    parse_price_cents,
    parse_product_page,
)

URL = "https://shop.lululemon.com/c/women-clothes/n14uwk"
PRODUCT_URL = "https://shop.lululemon.com/p/define-jacket-nulu/hnsjuvo8dn"
PAGE = "dehydratedState.queries[catalogPageData].state.data.pages[0]"
ABSENT = object()


def category_color(list_price=100, sale_price=ABSENT, available=True, color_id="S1-C1"):
    price = {"listPrice": list_price, "currencyCode": "USD"}
    if sale_price is not ABSENT:
        price["salePrice"] = sale_price
    return {
        "id": color_id,
        "price": price,
        "availability": {"isAvailable": available, "fulfillmentType": "ship"},
    }


def category_product(product_id="p1", colors=None):
    if colors is None:
        colors = [category_color(), category_color(color_id="S1-C2")]
    return {
        "id": product_id,
        "type": "products",
        "attributes": {
            "name": "Define Jacket",
            "url": "/p/define-jacket/p1",
            "styles": [{"id": "S1", "colors": colors}],
        },
    }


def category_data(products=None, total=1130, next_link="/v1/next"):
    if products is None:
        products = [category_product()]
    links = {"self": "/v1/self"}
    if next_link is not ABSENT:
        links["next"] = next_link
    page = {
        "data": {
            "attributes": {"totalCount": total},
            "relationships": {"products": {"links": links}},
        },
        "included": [{"id": "n14uwk", "type": "category-page-data"}, *products],
    }
    query = {
        "queryKey": ["catalogPageData", "cdp", {"hash": "n14uwk"}],
        "state": {"data": {"pages": [page]}},
    }
    return {"props": {"pageProps": {"dehydratedState": {"queries": [{"queryKey": ["navData"]}, query]}}}}


def category_page(data):
    return data["props"]["pageProps"]["dehydratedState"]["queries"][1]["state"]["data"]["pages"][0]


def only_product(data):
    return category_page(data)["included"][1]


def pdp_query(product_id, skus):
    return {
        "queryKey": ["pdp", product_id, "v1", "en-us"],
        "state": {"data": {"skus": skus}},
    }


def product_data(*queries):
    return {"props": {"pageProps": {"dehydratedState": {"queries": list(queries)}}}}


def test_base_url():
    assert BASE_URL == "https://shop.lululemon.com"


# extract_next_data


def test_extract_next_data_returns_the_json_object(next_data_html):
    data = {"props": {"pageProps": {"a": [1, 2]}}, "page": "/c/[...slug]"}
    assert extract_next_data(next_data_html(data), URL) == data


def test_extract_next_data_accepts_type_before_id():
    html = '<script type="application/json" id="__NEXT_DATA__">{"a": 1}</script>'
    assert extract_next_data(html, URL) == {"a": 1}


@pytest.mark.parametrize(
    "html",
    [
        "<html><body>Access Denied</body></html>",
        "",
        '<script id="other">{"a": 1}</script>',
        '<script data-id="__NEXT_DATA__">{"a": 1}</script>',
        '<script id="__NEXT_DATA__" type="application/json">{not json</script>',
        '<script id="__NEXT_DATA__" type="application/json"></script>',
        '<script id="__NEXT_DATA__" type="application/json">[1, 2]</script>',
    ],
)
def test_extract_next_data_rejects_missing_script_or_bad_json(html):
    with pytest.raises(ScrapeError) as exc:
        extract_next_data(html, URL)
    assert str(exc.value) == f"__NEXT_DATA__ not found: {URL}"


# parse_price_cents


@pytest.mark.parametrize(
    "value, cents",
    [
        (128, 12800),
        (1, 100),
        ("128", 12800),
        ("12.5", 1250),
        ("12.50", 1250),
        ("0.01", 1),
        ("0.5", 50),
        ("99.99", 9999),
    ],
)
def test_parse_price_cents_accepts(value, cents):
    result = parse_price_cents(value, "here")
    assert result == cents
    assert type(result) is int


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        "12.345",
        "-1",
        "0",
        "0.00",
        0,
        -5,
        None,
        12.5,
        128.0,
        "",
        " 12",
        "12 ",
        "12\n",
        "12.",
        ".5",
        "1e3",
        "$12",
        "1,000",
        "١٢",
        ["12"],
    ],
)
def test_parse_price_cents_rejects(value):
    with pytest.raises(ScrapeError) as exc:
        parse_price_cents(value, "product p1 on u")
    assert str(exc.value) == f"unparseable price {value!r}: product p1 on u"


# parse_category_page: real fixture


def test_category_fixture(load_fixture):
    page = parse_category_page(load_fixture("category.json"), URL)

    assert page == CategoryPage(
        products=(
            CategoryProduct(
                id="hnsjuvo8dn",
                name="Define Jacket *Nulu",
                url="https://shop.lululemon.com/p/define-jacket-nulu/hnsjuvo8dn",
                min_available_price_cents=7900,
            ),
            CategoryProduct(
                id="lp4yqrz3sp",
                name="Scuba Evolve Oversized Half-Zip Hoodie",
                url="https://shop.lululemon.com/p/scuba-evolve-oversized-half-zip-hoodie/lp4yqrz3sp",
                min_available_price_cents=12800,
            ),
            CategoryProduct(
                id="o2dx4njotf",
                name="Dance Studio Mid-Rise Jogger *Full Length",
                url="https://shop.lululemon.com/p/dance-studio-jogger-29/o2dx4njotf",
                min_available_price_cents=4900,
            ),
        ),
        has_next=True,
        total_count=1130,
    )


def test_category_dataclasses_are_frozen():
    page = parse_category_page(category_data(), URL)
    with pytest.raises(AttributeError):
        page.has_next = False
    with pytest.raises(AttributeError):
        page.products[0].name = "x"


# parse_category_page: prices


@pytest.mark.parametrize(
    "sale_price, expected",
    [(ABSENT, 10000), (None, 10000), (80, 8000), ("79.5", 7950)],
)
def test_category_price_prefers_non_null_sale_price(sale_price, expected):
    colors = [category_color(list_price=100, sale_price=sale_price)]
    page = parse_category_page(category_data([category_product(colors=colors)]), URL)
    assert page.products[0].min_available_price_cents == expected


def test_category_price_accepts_string_list_price():
    colors = [category_color(list_price="12.5")]
    page = parse_category_page(category_data([category_product(colors=colors)]), URL)
    assert page.products[0].min_available_price_cents == 1250


def test_category_min_price_ignores_unavailable_colors_and_spans_styles():
    product = category_product(
        colors=[
            category_color(list_price=20, available=False, color_id="S1-A"),
            category_color(list_price=90, color_id="S1-B"),
        ]
    )
    product["attributes"]["styles"].append(
        {"id": "S2", "colors": [category_color(list_price=60, sale_price=55, color_id="S2-A")]}
    )
    page = parse_category_page(category_data([product]), URL)
    assert page.products[0].min_available_price_cents == 5500


def test_category_min_price_is_none_when_no_color_is_available():
    colors = [category_color(available=False)]
    page = parse_category_page(category_data([category_product(colors=colors)]), URL)
    assert page.products[0].min_available_price_cents is None


@pytest.mark.parametrize(
    "overrides, bad_value",
    [
        ({"list_price": "abc"}, "abc"),
        ({"list_price": 0}, 0),
        ({"list_price": True}, True),
        ({"list_price": 100, "sale_price": "12.345"}, "12.345"),
        ({"list_price": 100, "sale_price": 0}, 0),
        ({"list_price": 100, "sale_price": -1, "available": False}, -1),
    ],
)
def test_category_unparseable_price_names_product_and_color(overrides, bad_value):
    colors = [category_color(**overrides)]
    with pytest.raises(ScrapeError) as exc:
        parse_category_page(category_data([category_product(colors=colors)]), URL)
    assert str(exc.value) == f"unparseable price {bad_value!r}: product p1 color S1-C1 on {URL}"


def test_category_unused_list_price_is_not_parsed_when_sale_price_is_used():
    colors = [category_color(list_price="n/a", sale_price=50)]
    page = parse_category_page(category_data([category_product(colors=colors)]), URL)
    assert page.products[0].min_available_price_cents == 5000


# parse_category_page: has_next and total_count


@pytest.mark.parametrize(
    "next_link, expected",
    [("/v1/categories/n14uwk/products?page=2", True), (ABSENT, False), ("", False), (None, False), (2, False), (True, False)],
)
def test_category_has_next_only_for_non_empty_string(next_link, expected):
    page = parse_category_page(category_data(next_link=next_link), URL)
    assert page.has_next is expected


@pytest.mark.parametrize("missing", ["links", "products", "relationships"])
def test_category_has_next_false_when_links_branch_is_absent(missing):
    data = category_data()
    relationships = category_page(data)["data"]["relationships"]
    if missing == "links":
        del relationships["products"]["links"]
    elif missing == "products":
        del relationships["products"]
    else:
        del category_page(data)["data"]["relationships"]
    assert parse_category_page(data, URL).has_next is False


@pytest.mark.parametrize("total", [None, True, False, "1130", 1130.0, ABSENT])
def test_category_total_count_must_be_int(total):
    data = category_data()
    attributes = category_page(data)["data"]["attributes"]
    if total is ABSENT:
        del attributes["totalCount"]
    else:
        attributes["totalCount"] = total
    with pytest.raises(ScrapeError) as exc:
        parse_category_page(data, URL)
    assert str(exc.value) == f"missing field {PAGE}.data.attributes.totalCount: {URL}"


def test_category_total_count_is_returned():
    assert parse_category_page(category_data(total=302), URL).total_count == 302


def test_category_without_products_entries_is_an_empty_page():
    page = parse_category_page(category_data(products=[]), URL)
    assert page.products == ()


def test_category_ignores_non_product_included_entries():
    data = category_data()
    category_page(data)["included"].extend(["junk", None, {"type": "other", "id": "x"}])
    assert [p.id for p in parse_category_page(data, URL).products] == ["p1"]


# parse_category_page: missing fields


def drop_query(data):
    queries = data["props"]["pageProps"]["dehydratedState"]["queries"]
    del queries[1]


def set_pages(value):
    def apply(data):
        data["props"]["pageProps"]["dehydratedState"]["queries"][1]["state"]["data"]["pages"] = value

    return apply


@pytest.mark.parametrize(
    "mutate, path",
    [
        (drop_query, "dehydratedState.queries[catalogPageData]"),
        (lambda d: d.clear(), "dehydratedState.queries[catalogPageData]"),
        (lambda d: d["props"]["pageProps"]["dehydratedState"].update(queries="x"), "dehydratedState.queries[catalogPageData]"),
        (set_pages([]), PAGE),
        (set_pages(None), PAGE),
        (set_pages(["x"]), PAGE),
        (lambda d: category_page(d).pop("included"), f"{PAGE}.included"),
        (lambda d: category_page(d).update(included={}), f"{PAGE}.included"),
    ],
)
def test_category_page_level_missing_fields(mutate, path):
    data = category_data()
    mutate(data)
    with pytest.raises(ScrapeError) as exc:
        parse_category_page(data, URL)
    assert str(exc.value) == f"missing field {path}: {URL}"


def pop_color(key, subkey=None):
    def apply(product):
        color = product["attributes"]["styles"][0]["colors"][1]
        if subkey is None:
            color.pop(key)
        else:
            color[key].pop(subkey)

    return apply


def set_color(key, subkey, value):
    def apply(product):
        product["attributes"]["styles"][0]["colors"][1][key][subkey] = value

    return apply


COLOR = "attributes.styles[0].colors[1]"


@pytest.mark.parametrize(
    "mutate, path",
    [
        (lambda p: p.pop("id"), "id"),
        (lambda p: p.update(id=""), "id"),
        (lambda p: p.update(id=7), "id"),
        (lambda p: p.pop("attributes"), "attributes.name"),
        (lambda p: p["attributes"].pop("name"), "attributes.name"),
        (lambda p: p["attributes"].update(name=""), "attributes.name"),
        (lambda p: p["attributes"].update(name=None), "attributes.name"),
        (lambda p: p["attributes"].pop("url"), "attributes.url"),
        (lambda p: p["attributes"].update(url="p/define-jacket/p1"), "attributes.url"),
        (lambda p: p["attributes"].update(url="https://shop.lululemon.com/p/x/p1"), "attributes.url"),
        (lambda p: p["attributes"].update(url=None), "attributes.url"),
        (lambda p: p["attributes"].pop("styles"), "attributes.styles"),
        (lambda p: p["attributes"].update(styles=[]), "attributes.styles"),
        (lambda p: p["attributes"].update(styles={}), "attributes.styles"),
        (lambda p: p["attributes"]["styles"][0].pop("colors"), "attributes.styles[0].colors"),
        (lambda p: p["attributes"]["styles"][0].update(colors=[]), "attributes.styles[0].colors"),
        (lambda p: p["attributes"]["styles"].append({"id": "S2"}), "attributes.styles[1].colors"),
        (pop_color("price"), f"{COLOR}.price.listPrice"),
        (pop_color("price", "listPrice"), f"{COLOR}.price.listPrice"),
        (set_color("price", "listPrice", None), f"{COLOR}.price.listPrice"),
        (pop_color("availability"), f"{COLOR}.availability.isAvailable"),
        (pop_color("availability", "isAvailable"), f"{COLOR}.availability.isAvailable"),
        (set_color("availability", "isAvailable", "true"), f"{COLOR}.availability.isAvailable"),
        (set_color("availability", "isAvailable", 1), f"{COLOR}.availability.isAvailable"),
        (set_color("availability", "isAvailable", None), f"{COLOR}.availability.isAvailable"),
    ],
)
def test_category_product_missing_fields(mutate, path):
    data = category_data()
    mutate(only_product(data))
    with pytest.raises(ScrapeError) as exc:
        parse_category_page(data, URL)
    product_label = "?" if path == "id" else "p1"
    assert str(exc.value) == f"missing field {path}: product {product_label} on {URL}"


def test_category_product_missing_field_aborts_even_when_other_products_are_fine():
    data = category_data([category_product("p1"), category_product("p2")])
    del category_page(data)["included"][2]["attributes"]["name"]
    with pytest.raises(ScrapeError, match="missing field attributes.name: product p2 on"):
        parse_category_page(data, URL)


# parse_product_page


@pytest.mark.parametrize(
    "fixture, product_id",
    [
        ("product_define_jacket.json", "hnsjuvo8dn"),
        ("product_align_pant.json", "qxsqxy9hy2"),
        ("product_crossbody_bag.json", "n4g2nr4v61"),
    ],
)
def test_product_fixture_skus_are_returned_unchanged(load_fixture, fixture, product_id):
    data = load_fixture(fixture)
    expected = next(
        q["state"]["data"]["skus"]
        for q in data["props"]["pageProps"]["dehydratedState"]["queries"]
        if q["queryKey"][:2] == ["pdp", product_id]
    )

    skus = parse_product_page(data, product_id, PRODUCT_URL)

    assert skus == expected
    assert len(skus) == 7  # the samples keep 6 SKUs plus a "trimmed" marker string
    assert {"id", "size", "color", "available", "isFinalSale", "price"} <= skus[0].keys()


def test_product_fixture_with_sibling_pdp_queries_selects_by_product_id(load_fixture):
    data = load_fixture("product_align_pant.json")
    pdp_ids = [
        q["queryKey"][1]
        for q in data["props"]["pageProps"]["dehydratedState"]["queries"]
        if q["queryKey"][0] == "pdp"
    ]
    assert pdp_ids == ["qxsqxy9hy2", "voifnqeejx", "is0lhqmzr4"]

    with pytest.raises(ScrapeError) as exc:
        parse_product_page(data, "voifnqeejx", PRODUCT_URL)
    assert str(exc.value) == (
        f"missing field dehydratedState.queries[pdp:voifnqeejx].state.data.skus: {PRODUCT_URL}"
    )


def test_product_skus_come_from_the_query_for_the_product_id_not_the_first_pdp():
    sibling = [{"id": "sibling"}]
    wanted = [{"id": "wanted-1"}, {"id": "wanted-2"}]
    data = product_data(
        {"queryKey": ["navData", "alpine"]},
        pdp_query("other", sibling),
        pdp_query("p1", wanted),
    )
    assert parse_product_page(data, "p1", PRODUCT_URL) == wanted


def test_product_pdp_query_must_be_named_pdp():
    data = product_data({"queryKey": ["alpineInventory", "p1", "en-us"], "state": {"data": {"skus": [{}]}}})
    with pytest.raises(ScrapeError) as exc:
        parse_product_page(data, "p1", PRODUCT_URL)
    assert str(exc.value) == f"missing field dehydratedState.queries[pdp:p1]: {PRODUCT_URL}"


@pytest.mark.parametrize(
    "data",
    [
        {},
        product_data(),
        product_data(pdp_query("other", [])),
        product_data({"queryKey": ["pdp"]}),
        product_data({"queryKey": "pdp"}),
        product_data("junk"),
    ],
)
def test_product_missing_pdp_query(data):
    with pytest.raises(ScrapeError) as exc:
        parse_product_page(data, "p1", PRODUCT_URL)
    assert str(exc.value) == f"missing field dehydratedState.queries[pdp:p1]: {PRODUCT_URL}"


@pytest.mark.parametrize(
    "query",
    [
        {"queryKey": ["pdp", "p1"]},
        {"queryKey": ["pdp", "p1"], "state": "<trimmed>"},
        {"queryKey": ["pdp", "p1"], "state": {"data": {}}},
        {"queryKey": ["pdp", "p1"], "state": {"data": {"skus": None}}},
        {"queryKey": ["pdp", "p1"], "state": {"data": {"skus": {"id": "1"}}}},
        {"queryKey": ["pdp", "p1"], "state": {"data": {"skus": "x"}}},
    ],
)
def test_product_skus_must_be_a_list(query):
    with pytest.raises(ScrapeError) as exc:
        parse_product_page(product_data(query), "p1", PRODUCT_URL)
    assert str(exc.value) == f"missing field dehydratedState.queries[pdp:p1].state.data.skus: {PRODUCT_URL}"


def test_product_empty_skus_is_allowed():
    assert parse_product_page(product_data(pdp_query("p1", [])), "p1", PRODUCT_URL) == []


def test_product_skus_are_not_validated_here():
    skus = [{"available": "yes"}, "junk", None]
    assert parse_product_page(product_data(pdp_query("p1", skus)), "p1", PRODUCT_URL) == skus
