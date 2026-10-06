import errno
import json
import os
import re
from types import SimpleNamespace

import pytest
from curl_cffi import requests as curl_requests

from lulu_basket.cli import main
from lulu_basket.scrape.fetch import TransportError
from lulu_basket.scrape.parse import BASE_URL
from lulu_basket.snapshot import load_snapshot

WOMEN = "/c/women-clothes/n14uwk"
SCRAPED_AT = "2026-10-06T12:00:00Z"
PRODUCT_URL = f"{BASE_URL}/p/item/p1"
TOTALS = re.compile(r"Total \$(\d+)\.(\d\d) ")
OLD_BYTES = b"previous snapshot, not even valid JSON\n"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(self, url, **kwargs):
        raise AssertionError(f"unexpected real request: {url}")

    monkeypatch.setattr(curl_requests.Session, "get", refuse)


def invoke(capsys, *argv, http_get=None, sleeps=None):
    sleep = (lambda seconds: None) if sleeps is None else sleeps.append
    code = main(list(argv), http_get=http_get, sleep=sleep)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def totals(out):
    return [int(d) * 100 + int(c) for d, c in TOTALS.findall(out)]


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
    return entry


def stock(site, *offers):
    """Women category with one SKU per (id, name, dollars) offer; returns the products."""
    products = [
        site.product(pid, name, colors=((dollars, True),)) for pid, name, dollars in offers
    ]
    site.add_category(WOMEN, [products])
    for product, (_, _, dollars) in zip(products, offers):
        site.add_product(product, [sku(price={"listPrice": str(dollars), "salePrice": None})])
    return products


def entry(product_id, name, price_cents, color="Black", size="4", cap=None, cap_source=None):
    return {
        "product_id": product_id,
        "name": name,
        "url": f"https://shop.lululemon.com/p/{product_id}",
        "color": color,
        "size": size,
        "price_cents": price_cents,
        "cap": cap,
        "cap_source": cap_source,
    }


def write_doc(path, skus, target=7500):
    doc = {"schema": 1, "scraped_at": SCRAPED_AT, "target_cents": target, "skus": skus}
    path.write_text(json.dumps(doc), encoding="utf-8")
    return str(path)


def pair_snapshot(path, a_cap=None, a_source=None):
    return write_doc(
        path,
        [
            entry("a", "Align Pant", 2500, "Black", "4", a_cap, a_source),
            entry("a", "Align Pant", 2500, "Black", "6", a_cap, a_source),
            entry("b", "Define Jacket", 3000, "Navy", "2"),
        ],
    )


# scrape

def test_scrape_writes_a_loadable_snapshot_and_logs_to_stderr(fake_site, tmp_path, capsys):
    stock(fake_site, ("a", "Align Pant", 25), ("b", "Define Jacket", 30))
    path = str(tmp_path / "snap.json")
    code, out, err = invoke(capsys, "scrape", "--snapshot", path, http_get=fake_site.http_get)
    assert (code, out) == (0, "")
    snap = load_snapshot(path)
    assert snap.target_cents == 7500
    assert [(s.product_id, s.price_cents) for s in snap.skus] == [("a", 2500), ("b", 3000)]
    lines = err.splitlines()
    assert "women-clothes page 1/1: 2 listed" in lines
    assert "products found 2, product pages fetched 2, SKUs kept 2" in lines
    assert not any(line.startswith("error") for line in lines)


def test_scrape_passes_target_to_the_crawl_and_the_snapshot(fake_site, tmp_path, capsys):
    stock(fake_site, ("a", "Align Pant", 25), ("b", "Define Jacket", 30))
    path = str(tmp_path / "snap.json")
    code, _, _ = invoke(
        capsys, "scrape", "--target", "2800", "--snapshot", path, http_get=fake_site.http_get
    )
    assert code == 0
    snap = load_snapshot(path)
    assert snap.target_cents == 2800
    assert [s.product_id for s in snap.skus] == ["a"]


def test_scrape_defaults_to_snapshot_json_in_the_cwd(fake_site, tmp_path, monkeypatch, capsys):
    stock(fake_site, ("a", "Align Pant", 25))
    monkeypatch.chdir(tmp_path)
    code, _, _ = invoke(capsys, "scrape", http_get=fake_site.http_get)
    assert code == 0
    assert load_snapshot(tmp_path / "snapshot.json").target_cents == 7500


@pytest.mark.parametrize(
    ("argv", "delay"), [(["--delay", "2.5"], 2.5), ([], 1.0), (["--delay", "0"], 0.0)]
)
def test_scrape_sleeps_delay_before_every_request_but_the_first(
    fake_site, tmp_path, capsys, argv, delay
):
    stock(fake_site, ("a", "Align Pant", 25))
    sleeps = []
    path = str(tmp_path / "snap.json")
    code, _, _ = invoke(
        capsys, "scrape", "--snapshot", path, *argv, http_get=fake_site.http_get, sleeps=sleeps
    )
    assert code == 0
    assert len(fake_site.requests) == 4
    assert sleeps == [delay] * 3


def test_default_transport_is_the_curl_session(fake_site, tmp_path, monkeypatch, capsys):
    stock(fake_site, ("a", "Align Pant", 25))
    sessions = []

    def get(self, url, **kwargs):
        sessions.append(self)
        status, text = fake_site.http_get(url)
        return SimpleNamespace(status_code=status, text=text, url=url)

    monkeypatch.setattr(curl_requests.Session, "get", get)
    path = str(tmp_path / "snap.json")
    code, _, _ = invoke(capsys, "scrape", "--snapshot", path, "--delay", "0")
    assert code == 0
    assert len(sessions) == 4
    assert sessions[0].impersonate == "chrome"
    assert load_snapshot(path).skus


# FR-3: every failure ends in exit 1, its own message, an untouched snapshot

def case_blocked_403(site):
    stock(site, ("p1", "Define Jacket", 50))
    site.responses[PRODUCT_URL] = (403, "Forbidden")
    return site.http_get, f"error: blocked by site after 4 attempts: {PRODUCT_URL}"


def case_access_denied_page(site):
    stock(site, ("p1", "Define Jacket", 50))
    site.responses[PRODUCT_URL] = (200, "<html>Access Denied</html>")
    return site.http_get, f"error: blocked by site after 4 attempts: {PRODUCT_URL}"


def case_transport_error(site):
    stock(site, ("p1", "Define Jacket", 50))

    def http_get(url):
        if url == PRODUCT_URL:
            raise TransportError("connection reset")
        return site.http_get(url)

    return http_get, f"error: request failed: connection reset: {PRODUCT_URL}"


def case_not_found(site):
    stock(site, ("p1", "Define Jacket", 50))
    del site.responses[PRODUCT_URL]
    return site.http_get, f"error: request failed: HTTP 404: {PRODUCT_URL}"


def case_no_next_data(site):
    stock(site, ("p1", "Define Jacket", 50))
    site.responses[PRODUCT_URL] = (200, "<html><body>maintenance</body></html>")
    return site.http_get, f"error: __NEXT_DATA__ not found: {PRODUCT_URL}"


def case_missing_field(site):
    stock(site, ("p1", "Define Jacket", 50))
    site.add_page(PRODUCT_URL, {"props": {"pageProps": {"dehydratedState": {"queries": []}}}})
    return site.http_get, f"error: missing field dehydratedState.queries[pdp:p1]: {PRODUCT_URL}"


def case_zero_products(site):
    return site.http_get, "error: no products found on category pages"


def case_bad_sku_price(site):
    (product,) = stock(site, ("p1", "Define Jacket", 50))
    site.add_product(product, [sku(price={"listPrice": "abc", "salePrice": None})])
    return (
        site.http_get,
        f"error: unparseable price 'abc': product p1 skus[0] on {PRODUCT_URL}",
    )


def case_bad_category_price(site):
    product = site.product("p1", colors=(("n/a", True),))
    site.add_category(WOMEN, [[product]])
    return (
        site.http_get,
        f"error: unparseable price 'n/a': product p1 color S1-C0 on {BASE_URL}{WOMEN}",
    )


def case_zero_eligible(site):
    (product,) = stock(site, ("p1", "Define Jacket", 50))
    site.add_product(product, [sku(isFinalSale=True)])
    return site.http_get, "error: no eligible SKUs after filtering"


FAILURES = [
    case_blocked_403,
    case_access_denied_page,
    case_transport_error,
    case_not_found,
    case_no_next_data,
    case_missing_field,
    case_zero_products,
    case_bad_sku_price,
    case_bad_category_price,
    case_zero_eligible,
]


@pytest.mark.parametrize("command", ["scrape", "run"])
@pytest.mark.parametrize("case", FAILURES, ids=lambda case: case.__name__)
def test_scrape_failure_exits_1_with_its_message_and_keeps_the_old_snapshot(
    fake_site, tmp_path, capsys, command, case
):
    http_get, expected = case(fake_site)
    path = tmp_path / "snapshot.json"
    path.write_bytes(OLD_BYTES)
    code, out, err = invoke(
        capsys, command, "--snapshot", str(path), "--delay", "0", http_get=http_get
    )
    assert code == 1
    assert out == ""
    assert err.splitlines()[-1] == expected
    assert path.read_bytes() == OLD_BYTES
    assert os.listdir(tmp_path) == ["snapshot.json"]


def test_failure_creates_no_snapshot(fake_site, tmp_path, capsys):
    http_get, _ = case_blocked_403(fake_site)
    code, _, _ = invoke(
        capsys, "scrape", "--snapshot", str(tmp_path / "snapshot.json"), http_get=http_get
    )
    assert code == 1
    assert os.listdir(tmp_path) == []


def test_retries_wait_5_then_15_then_45_seconds_before_failing(fake_site, tmp_path, capsys):
    http_get, _ = case_blocked_403(fake_site)
    sleeps = []
    invoke(
        capsys, "scrape", "--snapshot", str(tmp_path / "s.json"), "--delay", "0",
        http_get=http_get, sleeps=sleeps,
    )
    assert sleeps[-3:] == [5, 15, 45]


@pytest.mark.parametrize("command", ["scrape", "run"])
def test_unwritable_snapshot_path_exits_1_with_the_reason(fake_site, tmp_path, capsys, command):
    stock(fake_site, ("a", "Align Pant", 25))
    path = str(tmp_path / "missing-dir" / "snapshot.json")
    code, out, err = invoke(
        capsys, command, "--snapshot", path, "--delay", "0", http_get=fake_site.http_get
    )
    assert code == 1
    assert out == ""
    assert err.splitlines()[-1] == (
        f"error: cannot write snapshot {path}: {os.strerror(errno.ENOENT)}"
    )


# solve

def test_solve_prints_the_top_three_combinations(tmp_path, capsys):
    path = pair_snapshot(tmp_path / "snap.json")
    code, out, err = invoke(capsys, "solve", "--snapshot", path)
    assert (code, err) == (0, "")
    assert out == (
        "Target $75.00 · snapshot 2026-10-06T12:00:00Z\n"
        "\n"
        "#1  Total $75.00 ($0.00 below target)\n"
        "  3 × Align Pant  $25.00 each\n"
        "      Black: 4, 6\n"
        "      https://shop.lululemon.com/p/a\n"
        "\n"
        "#2  Total $60.00 ($15.00 below target)\n"
        "  2 × Define Jacket  $30.00 each\n"
        "      Navy: 2\n"
        "      https://shop.lululemon.com/p/b\n"
        "\n"
        "#3  Total $55.00 ($20.00 below target)\n"
        "  1 × Align Pant  $25.00 each\n"
        "      Black: 4, 6\n"
        "      https://shop.lululemon.com/p/a\n"
        "  1 × Define Jacket  $30.00 each\n"
        "      Navy: 2\n"
        "      https://shop.lululemon.com/p/b\n"
    )


def test_solve_with_a_stock_cap(tmp_path, capsys):
    path = pair_snapshot(tmp_path / "snap.json", a_cap=2, a_source="low_stock_count")
    code, out, _ = invoke(capsys, "solve", "--snapshot", path)
    assert code == 0
    assert totals(out) == [6000, 5500, 5000]
    assert "  2 × Align Pant  $25.00 each  [stock cap 2: low-stock count]\n" in out


def test_solve_without_a_feasible_combination_exits_0(tmp_path, capsys):
    path = write_doc(tmp_path / "snap.json", [entry("a", "Align Pant", 8000)])
    code, out, err = invoke(capsys, "solve", "--snapshot", path)
    assert (code, err) == (0, "")
    assert out == (
        "Target $75.00 · snapshot 2026-10-06T12:00:00Z\n\nNo feasible combination.\n"
    )


def test_solve_target_below_the_snapshot_target(tmp_path, capsys):
    path = pair_snapshot(tmp_path / "snap.json")
    code, out, _ = invoke(capsys, "solve", "--snapshot", path, "--target", "5000")
    assert code == 0
    assert out.startswith("Target $50.00 ")
    assert totals(out) == [5000, 3000, 2500]


def test_solve_target_above_the_snapshot_target_asks_for_a_new_scrape(tmp_path, capsys):
    path = pair_snapshot(tmp_path / "snap.json")
    code, out, err = invoke(capsys, "solve", "--snapshot", path, "--target", "10000")
    assert code == 1
    assert out == ""
    assert err == "error: target 10000 exceeds snapshot target 7500; re-run scrape --target 10000\n"


def test_solve_target_equal_to_the_snapshot_target_is_allowed(tmp_path, capsys):
    path = pair_snapshot(tmp_path / "snap.json")
    code, out, _ = invoke(capsys, "solve", "--snapshot", path, "--target", "7500")
    assert code == 0
    assert totals(out)[0] == 7500


def test_solve_defaults_to_snapshot_json_in_the_cwd(tmp_path, monkeypatch, capsys):
    pair_snapshot(tmp_path / "snapshot.json")
    monkeypatch.chdir(tmp_path)
    code, out, _ = invoke(capsys, "solve")
    assert code == 0
    assert out.startswith("Target $75.00 ")


def test_solve_missing_snapshot_exits_1(tmp_path, capsys):
    path = str(tmp_path / "nope.json")
    code, out, err = invoke(capsys, "solve", "--snapshot", path)
    assert (code, out) == (1, "")
    assert err == f"error: snapshot not found: {path}; run scrape first\n"


def test_solve_invalid_snapshot_exits_1(tmp_path, capsys):
    path = tmp_path / "snap.json"
    path.write_text('{"schema": 2}', encoding="utf-8")
    code, out, err = invoke(capsys, "solve", "--snapshot", str(path))
    assert (code, out) == (1, "")
    assert err == f"error: invalid snapshot {path}: schema must be 1\n"


def test_solve_search_space_guard_exits_1(tmp_path, capsys):
    path = write_doc(tmp_path / "snap.json", [entry("a", "Penny", 1)])
    code, out, err = invoke(capsys, "solve", "--snapshot", path)
    assert (code, out) == (1, "")
    assert err == "error: search space too large (target 7500, price step 1 cents)\n"


# run

def test_run_scrapes_then_prints_the_combinations(fake_site, tmp_path, capsys):
    stock(fake_site, ("a", "Align Pant", 25), ("b", "Define Jacket", 30))
    path = str(tmp_path / "snap.json")
    code, out, err = invoke(capsys, "run", "--snapshot", path, http_get=fake_site.http_get)
    assert code == 0
    assert totals(out) == [7500, 6000, 5500]
    assert out.startswith("Target $75.00 · snapshot ")
    assert "3 × Align Pant  $25.00 each" in out
    assert "products found 2, product pages fetched 2, SKUs kept 2" in err.splitlines()
    assert load_snapshot(path).target_cents == 7500


def test_run_uses_one_target_for_scrape_and_solve(fake_site, tmp_path, capsys):
    stock(fake_site, ("a", "Align Pant", 25), ("b", "Define Jacket", 30))
    path = str(tmp_path / "snap.json")
    code, out, _ = invoke(
        capsys, "run", "--target", "5000", "--snapshot", path, http_get=fake_site.http_get
    )
    assert code == 0
    assert totals(out) == [5000, 3000, 2500]
    assert load_snapshot(path).target_cents == 5000


def test_run_passes_delay_to_the_scrape(fake_site, tmp_path, capsys):
    stock(fake_site, ("a", "Align Pant", 25))
    sleeps = []
    path = str(tmp_path / "snap.json")
    code, _, _ = invoke(
        capsys, "run", "--snapshot", path, "--delay", "3", http_get=fake_site.http_get,
        sleeps=sleeps,
    )
    assert code == 0
    assert sleeps == [3.0] * 3


def test_run_with_a_failing_scrape_prints_nothing_and_ignores_the_old_snapshot(
    fake_site, tmp_path, capsys
):
    http_get, expected = case_blocked_403(fake_site)
    path = pair_snapshot(tmp_path / "snap.json")
    before = (tmp_path / "snap.json").read_bytes()
    code, out, err = invoke(
        capsys, "run", "--snapshot", path, "--delay", "0", http_get=http_get
    )
    assert code == 1
    assert out == ""
    assert err.splitlines()[-1] == expected
    assert (tmp_path / "snap.json").read_bytes() == before


def test_run_solve_failure_exits_1_and_keeps_the_new_snapshot(fake_site, tmp_path, capsys):
    (product,) = stock(fake_site, ("p1", "Penny", 1))
    fake_site.add_product(product, [sku(price={"listPrice": "0.01", "salePrice": None})])
    path = str(tmp_path / "snap.json")
    code, out, err = invoke(capsys, "run", "--snapshot", path, http_get=fake_site.http_get)
    assert (code, out) == (1, "")
    assert err.splitlines()[-1] == (
        "error: search space too large (target 7500, price step 1 cents)"
    )
    assert load_snapshot(path).skus[0].price_cents == 1


# usage errors

@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["bogus"],
        ["solve", "--target", "0"],
        ["solve", "--target", "-5"],
        ["solve", "--target", "abc"],
        ["solve", "--target", "7500.5"],
        ["scrape", "--target", "0"],
        ["run", "--target", "abc"],
        ["scrape", "--delay", "-1"],
        ["scrape", "--delay", "abc"],
        ["run", "--delay", "nan"],
        ["run", "--delay", "inf"],
        ["solve", "--delay", "1"],
    ],
)
def test_usage_errors_exit_2(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage:" in captured.err
